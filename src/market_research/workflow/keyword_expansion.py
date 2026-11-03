"""Bounded product/design expansion; proposals remain unverified hypotheses."""
import re

from ..llm.client import complete
from ..common import identity
from ..providers.client import SourceError
from .trend_queries import measurement_query, research_period, research_focus, product_context, search_phrase_issue, DISCOVERY_QUERY_VERSION
from ..business.domain import prompt_context


def product_key(text):
    """Collapse empty service/plural padding, preserving model/finish/process."""
    query = measurement_query(text).casefold()
    query = re.sub(r"\b(custom|customized|customised|personalized|personalised)\b", " ", query)
    words = re.findall(r"[a-z0-9]+", query)
    def singular(word):
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"
        if word.endswith(("ches", "shes", "sses", "xes")):
            return word[:-2]
        return word[:-1] if word.endswith("s") and len(word) > 3 and not word.endswith(("ss", "us")) else word
    return " ".join(singular(w) for w in words)


def rejection(item, niches, config=None):
    if not isinstance(item, dict):
        return "Ứng viên không phải object"
    text = item.get("keyword")
    if not isinstance(item.get("niche_id"), str) or item["niche_id"] not in niches:
        return "Niche ngoài phạm vi người dùng"
    if not isinstance(text, str) or not text.isascii() or not 2 <= len(text.strip()) <= 100:
        return "Keyword phải là cụm sản phẩm hoặc mẫu thiết kế tiếng Anh ASCII"
    words = re.findall(r"[a-zA-Z0-9]+", text)
    if not 1 <= len(words) <= 12 or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9 '&+.,()\-/]*", text.strip()):
        return "Keyword quá dài hoặc có ký tự không phù hợp tìm loại hàng"
    if re.search(r"\b(lyrics|weather|meaning|definition|news|tutorial|article|statistics|bestseller|viral|trending)\b|https?://|\b(?:best|top)\s+\d+", text, re.I):
        return "Cụm thông tin/khẳng định độ hot, không phải giả thuyết loại sản phẩm"
    if not product_key(text):
        return "Thiếu loại sản phẩm để kiểm chứng"
    issue = search_phrase_issue(text)
    if issue:
        return issue
    if config is not None and product_context(text, config):
        return "Keyword chỉ mô tả nhóm hàng chung; thiếu chi tiết mẫu, hình dạng, định dạng, chất liệu, hoàn thiện hoặc chủ đề cụ thể theo yêu cầu"
    reason = item.get("reason")
    if not isinstance(reason, str) or not 8 <= len(reason.strip()) <= 500:
        return "Thiếu lý do phù hợp với niche/người nhận"
    if re.search(r"\b(?:is|are|was|were|proven|verified|currently)\b.{0,35}\b(?:trending|viral|popular|bestsell\w*|hot)\b|(?:đang|đã|rất|chắc chắn)\s+(?:hot|thịnh hành|bán chạy|phổ biến)|\b\d+[,+]*\s*(?:sales|sold|orders|đơn hàng|lượt tìm)", reason, re.I):
        return "Đề xuất LLM khẳng định độ hot/doanh số chưa có bằng chứng nguồn; chỉ nhận giả thuyết để đo đúng tháng"
    return None


def expand(run, client, config, niches, keywords, add, source_pages=()):
    """At most two logical rounds; Client still owns all HTTP/model retry caps."""
    target = config["limits"]["candidate_keywords"]
    summary = {"branch": "llm_expansion", "target": target, "rounds": 0,
               "accepted": 0, "rejected": 0, "cache_reused": 0, "status": "skipped"}
    if len(keywords) >= target:
        summary["reason"] = "Đã đủ ứng viên trong phạm vi người dùng chọn"
        return summary, []
    if not config["llm"]["enabled"]:
        summary["reason"] = "LLM đã tắt; chỉ dùng seed và nguồn thật đã cấu hình"
        return summary, []
    seen = {product_key(k["text"]) for k in keywords.values()}
    excluded = []
    for round_number in range(1, 3):
        if len(keywords) >= target:
            break
        maximum = min(32, target - len(keywords))
        payload = {"brief": config["brief"], "category": config["category"], "market": config["market"],
            "business_context": prompt_context(config),
            "research_period": research_period(config),
            "research_focus": research_focus(config),
            "source_pages": [{key: page.get(key) for key in ("id", "title", "excerpt", "url")} for page in source_pages][:16],
            "query_version": DISCOVERY_QUERY_VERSION,
            "niches": [{k: n.get(k) for k in ("id", "name", "name_en", "customer_hypothesis")} for n in niches.values()],
            "constraints": {k: config.get(k) for k in ("price_range", "required_features", "excluded_features", "preferences", "selling_months")},
            "existing_keywords": [k["text"] for k in keywords.values()], "maximum": maximum, "round": round_number}
        checkpoint_name = "discover-expansion-" + str(round_number)
        payload_hash = identity("expand", payload)
        saved = run.stage_data(checkpoint_name)
        reusable = isinstance(saved, dict) and saved.get("input_hash") == payload_hash and isinstance(saved.get("result"), dict) and isinstance(saved["result"].get("candidates"), list)
        used = sum(u["provider"] == "openrouter" for u in run.manifest["usage"])
        if not reusable and used >= config["limits"]["llm_requests"]:
            summary.update(status="limited", reason="Hết trần OpenRouter; không tự tăng ngân sách")
            break
        summary["rounds"] += 1
        try:
            if reusable:
                result = saved["result"]
                summary["cache_reused"] += 1
                run.log("discover", "keyword_expansion_checkpoint_reused", "Dùng lại mở rộng keyword đã lưu; không gọi LLM mới", round=round_number)
            else:
                result = complete(client, "expand", payload)
                run.checkpoint(checkpoint_name, {"input_hash": payload_hash, "result": result})
            accepted = 0
            for item in result.get("candidates", [])[:maximum * 2]:
                reason = rejection(item, niches, config)
                text = item.get("keyword") if isinstance(item, dict) else None
                key = product_key(text) if isinstance(text, str) else None
                if reason is None and key in seen:
                    reason = "Trùng sản phẩm và chủ đề thiết kế đã có; không tăng số lượng bằng biến thể cách viết"
                if reason:
                    excluded.append({"keyword": text, "reason": reason, "kind": "llm_expansion"})
                    summary["rejected"] += 1
                    continue
                if len(keywords) >= target:
                    break
                text = " ".join(text.split())
                if add(text, niches[item["niche_id"]], "llm_expansion", proposal_reason=item["reason"].strip(), expansion_round=round_number):
                    seen.add(key)
                    accepted += 1
            summary["accepted"] += accepted
            summary["status"] = "available" if summary["accepted"] else "empty"
            run.log("discover", "keyword_expansion_result", "Mở rộng mẫu sản phẩm theo hình dạng, định dạng, hoàn thiện, phôi hoặc chủ đề để đo trong tháng đã chọn; đề xuất chưa phải xu hướng đã xác minh", round=round_number, requested=maximum, accepted=accepted, total_candidates=len(keywords), target=target)
            if accepted == 0:
                break
        except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
            summary.update(status="limited", reason=str(error))
            run.log("discover", "keyword_expansion_unavailable", "Không mở rộng thêm được trong nguồn/ngân sách hiện tại", round=round_number, reason=str(error))
            break
    return summary, excluded
