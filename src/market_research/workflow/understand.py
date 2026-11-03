"""Interpret once, freeze user constraints and retain explicit assumptions."""
import re
from ..common import identity, read_json, ROOT
from ..config import validate_config
from ..llm.client import complete
from ..business.domain import classify, prompt_context, active
from ..llm.plan import seasonal_months
from .trend_queries import research_focus


def plan_payload(config):
    return {"brief": config["brief"], "chosen_niches": config["niches"], "explicit_category": config["category"],
        "business": config.get("business", {"profile": "general", "categories": []}), "business_context": prompt_context(config),
        "research_focus": research_focus(config),
        "explicit_constraints": {k: config[k] for k in ("selling_months", "price_range", "required_features", "excluded_features", "preferences", "preparation_days")},
        "validation_context": {k: config[k] for k in ("as_of_date", "history_years", "target_year", "trends")}, "default_months": list(range(1, 13))}


def interpret(run, client, config, *, validated_draft=None):
    if validated_draft is not None:
        draft = validated_draft
    elif config["mode"] == "offline":
        saved = read_json(ROOT / "examples/archive-plan.json")
        if not saved:
            raise ValueError("Thiếu bộ dữ liệu mẫu lưu trữ")
        recorded_names = {n.get("name_vi", n["name"]) for n in saved["niches"]} | {n["name"] for n in saved["niches"]}
        if (config["category"] and config["category"] != saved["category"]) or any(n["name"] not in recorded_names for n in config["niches"]):
            raise ValueError("Offline chỉ phát lại danh mục/niche của bộ Q4; dùng live cho phạm vi mới")
        draft = {"category": saved["category"], "niches": [
            {"name": n.get("name_vi", n["name"]), "name_en": n["name"], "seeds": [f["keyword"] for f in saved["families"] if f["niche_id"] == n["id"]], "seed_labels": {f["keyword"]: f.get("name_vi", f["name"]) for f in saved["families"] if f["niche_id"] == n["id"]}, "customer_hypothesis": "Chưa có khảo sát khách hàng; đối chiếu listing/review"}
            for n in saved["niches"]], "summary_vi": "Phát lại nghiên cứu quà và decor Q4 đã lưu ngày 22/10/2026.", "selling_months": [10, 11, 12], "assumptions": ["Offline chỉ phát lại phạm vi bộ Q4 đã thu thập; không phải khám phá mới từ mô tả."]}
    elif config["niches"] and all(n.get("seeds") for n in config["niches"]):
        draft = {"category": config["category"] or config["brief"], "niches": config["niches"], "assumptions": []}
    elif config["llm"]["enabled"]:
        draft = complete(client, "understand", plan_payload(config))
    else:
        raise ValueError("Mô tả tự do cần LLM để dịch và xác định phạm vi; hoặc nhập niche/seeds trong cấu hình structured")
    niches = draft.get("niches")
    if not isinstance(niches, list) or not 1 <= len(niches) <= 5:
        raise ValueError("Kế hoạch AI cần 1–5 niche hợp lệ")
    # Explicit user niches cannot silently disappear or be replaced by AI suggestions.
    if config["niches"]:
        for index, original in enumerate(config["niches"]):
            proposed = next((n for n in niches if n.get("name", "").casefold() == original["name"].casefold()), None)
            if proposed is None:
                proposed = {**original, "seeds": niches[index].get("seeds", []) if index < len(niches) else []}
            else:
                proposed = {**proposed, **original, "seeds": original.get("seeds") or proposed.get("seeds")}
            if index == 0:
                preserved = []
            preserved.append(proposed)
        niches = preserved
    result = {**config, "category": config["category"] or draft.get("category"), "interpretation": draft.get("summary_vi") or config["brief"]}
    if draft.get("plan_adjustments"):
        result["plan_adjustments"] = draft["plan_adjustments"]
        run.log("understand", "plan_normalized", "Giới hạn nhóm ý tưởng theo phạm vi workflow; giữ phần dư để kiểm tra", adjustments=draft["plan_adjustments"])
    if draft.get("seed_quality_adjustments"):
        result["seed_quality_adjustments"] = draft["seed_quality_adjustments"]
        run.log("understand", "plan_seed_filter", "Loại riêng seed AI chưa phù hợp tìm kiếm; giữ các nhóm và seed hợp lệ", adjustments=draft["seed_quality_adjustments"])
    if draft.get("business_rule_adjustments"):
        result["business_rule_adjustments"] = draft["business_rule_adjustments"]
        run.log("understand", "business_rules_deduplicated", "Giữ kiểm tra phạm vi công ty ở bộ lọc domain; loại điều kiện listing trùng lặp do AI tự thêm", adjustments=draft["business_rule_adjustments"])
    if not isinstance(result["category"], str) or not result["category"].strip():
        raise ValueError("Kế hoạch thiếu chủ đề chính")
    for field in ("selling_months", "price_range", "preparation_days"):
        if result[field] is None:
            result[field] = draft.get(field)
    if config["selling_months"] is None and re.search(r"\b(noel|giáng sinh|christmas)\b", config["brief"], re.I) and not re.search(r"quanh năm|cả năm|year.round|all year", config["brief"], re.I) and result.get("selling_months") in (None, list(range(1, 13))):
        result["selling_months"] = [11, 12]
        run.log("understand", "season_window", "Brief nêu Noel nhưng model trả cả năm: dùng kỳ bán tháng 11–12 trong phạm vi thu thập đã chọn")
    season_assumptions = []
    inferred_months = seasonal_months(result.get("selling_months"), config["selling_months"], config.get("trends", {}), config["brief"])
    if inferred_months != result.get("selling_months"):
        run.log("understand", "seasonal_selling_window", "Chỉ dùng kỳ bán suy ra trong các tháng lịch sử người dùng chọn", proposed=result.get("selling_months"), selected=inferred_months)
        result["selling_months"] = inferred_months
        season_assumptions.append("Kỳ bán suy ra chỉ nằm trong các tháng lịch sử đã chọn: " + ", ".join(map(str, inferred_months)) + "; cần xác nhận kế hoạch bán thực tế.")
    result["selling_months"] = result["selling_months"] or list(range(1, 13))
    for field in ("preferences", "required_features", "excluded_features"):
        if not result[field]:
            result[field] = draft.get(field) or []
    result["niches"] = []
    domain_exclusions = []
    for n in niches:
        if not isinstance(n, dict) or not isinstance(n.get("name"), str) or not isinstance(n.get("seeds"), list) or not n["seeds"]:
            raise ValueError("Niche cần tên và seed truy vấn")
        if any(not isinstance(s, str) or not 2 <= len(s) <= 200 or not s.isascii() for s in n["seeds"]):
            raise ValueError("Seed cần cụm từ tiếng Anh hợp lệ")
        customer = n.get("customer_hypothesis")
        seeds = list(dict.fromkeys(n["seeds"]))
        if active(config):
            supported = []
            for seed in seeds:
                fit = classify(seed, config)
                if fit["status"] == "allowed":
                    supported.append(seed)
                else:
                    domain_exclusions.append({"keyword": seed, "niche_name": n["name"], "reason": fit["reason"], "kind": "company_domain", "business_fit": fit})
            seeds = supported
            if not seeds:
                raise ValueError("Niche '" + n["name"] + "' không còn seed thuộc nhóm hàng công ty. Chọn áo/quà in ấn, lịch/sổ, móc khóa, túi, phụ kiện điện thoại không cấp điện hoặc decor đơn giản; không dùng thực phẩm, mỹ phẩm hay thiết bị.")
        result["niches"].append({**n, "id": identity("N", n["name"]), "seeds": seeds, "customer_hypothesis": customer if isinstance(customer, str) and customer else "Đối tượng sử dụng cần kiểm chứng từ listing và phản hồi"})
    if domain_exclusions:
        result["business_exclusions"] = domain_exclusions
        run.log("understand", "company_seed_filter", "Đã loại seed ngoài domain công ty trước khi tìm Trends", exclusions=domain_exclusions)
    assumptions = draft.get("assumptions") or []
    if not isinstance(assumptions, list) or any(not isinstance(a, str) for a in assumptions):
        raise ValueError("Kế hoạch AI cần danh sách giả định dạng văn bản")
    result["assumptions"] = list(dict.fromkeys(config["assumptions"] + assumptions + season_assumptions))
    if not 3 <= len(niches) <= 5:
        result["assumptions"].append("Phạm vi có dưới 3 niche; chưa đủ cấu trúc 3–5 niche của Task 1.")
    result = validate_config(result)
    run.checkpoint("normalized_config", result)
    from ..common import write_json
    write_json(run.path / "normalized_config.json", result)
    return result
