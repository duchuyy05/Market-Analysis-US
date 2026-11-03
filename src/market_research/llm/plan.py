"""Validate the effective brief plan before accepting an LLM response.

The interpreter and this check use the same explicit-input precedence: missing
scalar constraints and empty feature defaults allow inference; constraints the
user actually supplied win over model output. No keywords are translated or
invented here. A bounded excess of model-proposed niches is deferred with an
audit note; other invalid effective plans enter the bounded LLM repair path.
"""
from copy import deepcopy
from datetime import date
import re
import unicodedata

from ..common import today
from ..config import validate_config


SCALARS = ("selling_months", "price_range", "preparation_days")
FEATURES = ("preferences", "required_features", "excluded_features")
NICHE_FIELDS = {"name", "name_en", "customer_hypothesis", "seeds", "id", "seed_labels"}
_PUNCTUATION = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2212": "-",
})


def _deduplicate_business_rules(draft, explicit, business_config):
    """Company capability rules are checked by the domain classifier, not title matching."""
    from ..business.domain import active
    if not active(business_config):
        return
    removed = []
    for field in ("required_features", "excluded_features"):
        if explicit.get(field):
            continue
        retained = []
        for value in draft[field]:
            text = " ".join(value.casefold().split())
            if field == "required_features":
                words = set(re.findall(r"\w+", text))
                process_words = set("có thể gia công in khắc thêu hoặc và chế tác theo yêu cầu cá nhân hóa 刻度".split())
                category_words = set("thuộc một trong các nhóm".split()) | set(business_config["business"].get("categories", []))
                duplicate = bool(re.fullmatch(r"phải là sản phẩm vật lý(?: thực tế)?|must be (?:a )?physical product|within (?:the )?selected company categories|can be (?:printed|engraved|embroidered|fabricated)(?:(?:,| and| or)\s*(?:printed|engraved|embroidered|fabricated))*", text)
                    or (text.startswith("có thể gia công") and words <= process_words)
                    or (text.startswith("thuộc") and words <= category_words))
            else:
                duplicate = bool(re.fullmatch(r"(?:sản phẩm )?điện tử(?: có cấp điện)?|thực phẩm(?:,? đồ uống)?|mỹ phẩm(?:,? (?:thuốc|dược phẩm))?|thiết bị y tế|máy in(?: hoặc thiết bị sản xuất)?|food|drinks|cosmetics|medicines|pharmaceuticals|powered electronics|medical devices|production machinery", text))
            if duplicate:
                removed.append({"field": field, "value": value, "handled_by": "business_domain"})
            else:
                retained.append(value)
        draft[field] = retained
    if removed:
        draft["business_rule_adjustments"] = {"removed_duplicate_rules": removed,
            "note": "Phạm vi công ty vẫn được kiểm tra bằng bộ lọc domain; không dùng nguyên câu mô tả năng lực làm đặc tính phải xuất hiện trên listing."}


def _seed(value):
    if not isinstance(value, str):
        raise ValueError("Seed cần cụm từ tiếng Anh hợp lệ")
    # Normalize only typography/spacing. Accented words are deliberately not
    # transliterated: doing so would silently change the proposed search term.
    value = " ".join(unicodedata.normalize("NFKC", value).translate(_PUNCTUATION).split())
    if not 2 <= len(value) <= 200 or not value.isascii():
        raise ValueError("Seed cần cụm từ tiếng Anh ASCII, dài 2–200 ký tự")
    return value


def seasonal_months(months, explicit, trends, brief):
    """Limit only inferred selling months to an explicitly seasonal collection."""
    if explicit is not None or (trends or {}).get("history_scope") != "seasonal":
        return months
    scope = list((trends or {}).get("history_months") or [])
    if not scope:
        return months
    inferred = months or []
    if not inferred or inferred == list(range(1, 13)):
        christmas = bool(re.search(r"\b(noel|giáng sinh|christmas)\b", brief or "", re.I))
        inferred = [11, 12] if christmas else scope
    covered = sorted(set(inferred) & set(scope))
    return covered or sorted(set(scope))


def _niches(draft, chosen, quality_exclusions=None):
    if not isinstance(draft, list):
        raise ValueError("Kế hoạch AI cần danh sách niche")
    if not isinstance(chosen, list):
        raise ValueError("Niche đã chọn cần là danh sách")
    # Validate generated structure before merging explicit user metadata. A
    # malformed JSON fragment hidden inside an object key must enter repair,
    # even though Python can otherwise parse the surrounding JSON object.
    for index, item in enumerate(draft):
        if not isinstance(item, dict):
            raise ValueError("Niche AI cần là một object hợp lệ")
        original = next((value for value in chosen if isinstance(value, dict) and isinstance(value.get("name"), str)
                         and value["name"].casefold() == str(item.get("name", "")).casefold()), {})
        if not original and index < len(chosen) and isinstance(chosen[index], dict):
            original = chosen[index]
        unknown = set(item) - NICHE_FIELDS - set(original)
        if unknown:
            raise ValueError("Niche AI có trường không hỗ trợ hoặc mảnh JSON bị lồng vào tên trường: " + ", ".join(str(key)[:100] for key in sorted(unknown, key=str)))
    if chosen:
        preserved = []
        for index, original in enumerate(chosen):
            if not isinstance(original, dict) or not isinstance(original.get("name"), str):
                raise ValueError("Niche đã chọn cần tên hợp lệ")
            proposed = next((n for n in draft if isinstance(n, dict) and
                             isinstance(n.get("name"), str) and
                             n["name"].casefold() == original["name"].casefold()), None)
            if proposed is None:
                fallback = draft[index].get("seeds", []) if index < len(draft) and isinstance(draft[index], dict) else []
                proposed = {**original, "seeds": original.get("seeds") or fallback}
            else:
                proposed = {**proposed, **original, "seeds": original.get("seeds") or proposed.get("seeds")}
            preserved.append(proposed)
        draft = preserved
    if not 1 <= len(draft) <= 5:
        raise ValueError(f"Kế hoạch AI cần 1–5 niche hợp lệ; nhận được {len(draft)} nhóm")
    output = []
    for item in draft:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("Niche cần tên không rỗng")
        seeds = item.get("seeds")
        if not isinstance(seeds, list) or not seeds:
            raise ValueError("Niche cần danh sách seed không rỗng")
        normalized = {**item, "name": item["name"].strip(), "seeds": list(dict.fromkeys(_seed(s) for s in seeds))}
        explicit = next((value for value in chosen if isinstance(value, dict) and str(value.get("name", "")).casefold() == item["name"].casefold()), {})
        from ..workflow.trend_queries import search_phrase_issue
        accepted, rejected = [], []
        for seed in normalized["seeds"]:
            issue = None if seed in explicit.get("seeds", []) else search_phrase_issue(seed)
            if issue:
                rejected.append({"niche": normalized["name"], "keyword": seed, "reason": issue})
            else:
                accepted.append(seed)
        if not accepted:
            raise ValueError(rejected[0]["reason"] + ": " + rejected[0]["keyword"])
        normalized["seeds"] = accepted
        if quality_exclusions is not None:
            quality_exclusions.extend(rejected)
        for key in ("name_en", "customer_hypothesis"):
            if key in normalized and normalized[key] is not None and not isinstance(normalized[key], str):
                raise ValueError(f"Niche {key} cần là văn bản")
            if normalized.get(key) is None:
                normalized.pop(key, None)
        output.append(normalized)
    return output


def validate_plan(result, payload):
    """Return a normalized draft; raise ValueError for an invalid effective plan.

    Optional legacy response fields may be absent. The returned object is a
    plan, not a validated run config; generated IDs and run state remain the
    interpreter's responsibility.
    """
    if not isinstance(result, dict) or not isinstance(payload, dict):
        raise ValueError("Kế hoạch và input LLM phải là JSON object")
    draft = deepcopy(result)
    explicit = payload.get("explicit_constraints", {})
    explicit = {} if explicit is None else explicit
    if not isinstance(explicit, dict):
        raise ValueError("Điều kiện đã nhập cần là object")
    for field in SCALARS:
        if explicit.get(field) is not None:
            draft[field] = explicit[field]
    for field in FEATURES:
        # The standard payload includes [] for fields the user did not fill.
        # Do not erase a model inference with that unspecified default.
        if field in explicit and explicit[field] is not None and explicit[field] != []:
            draft[field] = explicit[field]

    explicit_category = payload.get("explicit_category")
    if explicit_category is not None and not isinstance(explicit_category, str):
        raise ValueError("Danh mục đã nhập cần là văn bản")
    category = explicit_category or draft.get("category")
    if not isinstance(category, str) or not category.strip():
        raise ValueError("Kế hoạch thiếu chủ đề chính (category)")
    draft["category"] = category.strip()
    proposed = draft.get("niches", [])
    chosen = payload.get("chosen_niches", [])
    draft.pop("plan_adjustments", None)
    draft.pop("seed_quality_adjustments", None)
    draft.pop("business_rule_adjustments", None)
    # An LLM may enumerate the company catalog instead of obeying the requested
    # plan size. Keep a bounded source-ordered subset, never fabricate groups or
    # call it a market ranking. Explicit user niches still follow strict limits.
    if not chosen and isinstance(proposed, list) and 5 < len(proposed) <= 20:
        draft["plan_adjustments"] = {
            "kind": "niche_overflow", "proposed_count": len(proposed), "retained_count": 5,
            "selection": "model_order_not_market_rank", "deferred_niches": deepcopy(proposed[5:]),
        }
        proposed = proposed[:5]
        assumptions = draft.get("assumptions") or []
        if isinstance(assumptions, list):
            draft["assumptions"] = assumptions + [
                f"Model đề xuất {draft['plan_adjustments']['proposed_count']} niche; giữ 5 nhóm đầu theo thứ tự phản hồi để đúng phạm vi workflow. Các nhóm còn lại được lưu trong plan_adjustments.deferred_niches; đây không phải xếp hạng thị trường."
            ]
    quality_exclusions = []
    draft["niches"] = _niches(proposed, chosen, quality_exclusions)
    if quality_exclusions:
        draft["seed_quality_adjustments"] = {"kind": "generated_seed_filter", "excluded": quality_exclusions,
            "retained_keywords": sum(len(niche["seeds"]) for niche in draft["niches"]),
            "note": "Chỉ loại seed AI chưa phù hợp tìm kiếm; giữ nguyên các nhóm và keyword hợp lệ, chưa xác minh độ hot."}
    from ..business.domain import classify, active
    business_config = {"business": payload.get("business") or {"profile": "general", "categories": []}}
    if active(business_config):
        # Keep mixed plans intact for interpret() to filter and audit per seed.
        # One unsupported hypothesis must not force another model request when
        # the niche already has usable company products.
        empty_niches = [niche for niche in draft["niches"] if not any(classify(seed, business_config)["status"] == "allowed" for seed in niche["seeds"])]
        if empty_niches:
            invalid = [seed + ": " + classify(seed, business_config)["reason"] for niche in empty_niches for seed in niche["seeds"]]
            raise ValueError("Seed ngoài domain gia công/thiết kế đã chọn; sửa thành loại hàng phù hợp: " + "; ".join(invalid[:8]))
    if "summary_vi" in draft and draft["summary_vi"] is not None and not isinstance(draft["summary_vi"], str):
        raise ValueError("summary_vi cần là văn bản")

    context = payload.get("validation_context") or {}
    if not isinstance(context, dict):
        raise ValueError("Bối cảnh kiểm tra kế hoạch cần là object")
    cutoff = context.get("as_of_date") or payload.get("as_of_date") or today().isoformat()
    year = date.fromisoformat(cutoff).year
    collection = context.get("trends") or payload.get("trends") or {}
    proposed_months = draft.get("selling_months")
    draft["selling_months"] = seasonal_months(proposed_months, explicit.get("selling_months"), collection, payload.get("brief"))
    if draft["selling_months"] != proposed_months and explicit.get("selling_months") is None:
        assumptions = draft.get("assumptions", [])
        if assumptions is None:
            assumptions = []
        if isinstance(assumptions, list):
            draft["assumptions"] = assumptions + ["Kỳ bán suy ra được giới hạn trong các tháng lịch sử đã chọn: " + ", ".join(map(str, draft["selling_months"])) + "; chưa phải lịch bán do người dùng nhập rõ."]
    candidate = {"brief": payload.get("brief") or "Product research plan", "category": draft["category"],
                 "business": business_config["business"],
                 "trends": collection,
                 "niches": draft["niches"], "as_of_date": cutoff,
                 "history_years": context.get("history_years") or payload.get("history_years") or [year-2, year-1],
                 "target_year": context.get("target_year") or payload.get("target_year") or year}
    for field in SCALARS:
        candidate[field] = draft.get(field)
    for field in (*FEATURES, "assumptions"):
        value = draft.get(field, [])
        candidate[field] = [] if value is None else value
    validated = validate_config(candidate)
    for field in (*SCALARS, *FEATURES, "assumptions"):
        draft[field] = validated[field]
    _deduplicate_business_rules(draft, explicit, business_config)
    return draft
