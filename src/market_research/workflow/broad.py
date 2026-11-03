"""Bounded discovery across independent public-page and related-query branches."""
import re

from ..common import identity, safe_url
from ..providers import web, trends
from ..providers.client import SourceError
from ..llm.client import complete
from ..business.domain import classify, active


def normalized(text):
    return " ".join(str(text).casefold().split())


def discover(run, client, config):
    from .discover import discover as legacy
    if config["mode"] == "offline" or not config.get("discovery", {}).get("enabled"):
        return legacy(run, client, config)
    keywords, contexts, excluded, statuses = {}, [], list(config.get("business_exclusions", [])), []
    niches = {n["id"]: n for n in config["niches"]}

    def add(text, niche, origin, evidence=(), seed=None, **metadata):
        if not isinstance(text, str) or not text.isascii() or not 2 <= len(text.strip()) <= 200:
            return False
        text = " ".join(text.split())
        from .trend_queries import candidate_level
        from .design_content import design_metadata
        metadata["candidate_level"] = candidate_level(text, config)
        metadata.update(design_metadata(text, config))
        fit = classify(text, config)
        if fit["status"] != "allowed":
            excluded.append({"keyword": text, "niche_id": niche["id"], "reason": fit["reason"], "kind": "company_domain", "origin": origin, "evidence_ids": list(evidence), "business_fit": fit})
            run.log("discover", "company_keyword_filtered", fit["reason"], keyword=text, origin=origin, business_fit=fit)
            return False
        if active(config):
            metadata["business_fit"] = fit
        key = identity("K", niche["id"], text.casefold())
        is_new = key not in keywords
        row = keywords.setdefault(key, {"id": key, "text": text, "niche_id": niche["id"], "seed": seed or text,
                                       "origin": origin, "discovery_type": origin, "evidence_ids": [],
                                       "evidence_state": "source_observed" if evidence else "hypothesis", **metadata})
        before = len(row["evidence_ids"])
        row["evidence_ids"] = sorted(set(row["evidence_ids"]) | set(evidence))
        if row["evidence_ids"]:
            row["evidence_state"] = "source_observed"
        if metadata.get("source_design"):
            row["source_design"] = metadata["source_design"]
            if metadata["source_design"].get("query_origin") == "composed_from_source_spans":
                row["evidence_state"] = "source_grounded_query"
        return is_new or len(row["evidence_ids"]) > before

    for depth in range(max(len(n["seeds"]) for n in niches.values())):
        for niche in niches.values():
            if depth < len(niche["seeds"]):
                add(niche["seeds"][depth], niche, "user" if any(niche["seeds"][depth] in n.get("seeds", []) for n in run.manifest["input"].get("niches", [])) else "llm_candidate")
    from .web_discovery import harvest
    contexts, statuses, web_excluded = harvest(run, client, config, niches, add)
    excluded.extend(web_excluded)
    if config["sources"]["trends"]:
        windows = None
        if config.get("trends", {}).get("history_scope") == "seasonal":
            from .planning import analysis_windows
            windows = analysis_windows(config)
        related_rows = list(keywords.values())[:min(2, config["limits"]["related_seeds_per_niche"])] if windows != [] else []
        for index, row in enumerate(related_rows):
            try:
                date_range = None
                if windows:
                    window = windows[index % len(windows)]
                    date_range = window["start"] + " " + window["end"]
                envelope = trends.related(client, row["text"], config["as_of_date"], date_range=date_range) if date_range else trends.related(client, row["text"], config["as_of_date"])
                for kind in ("rising", "top"):
                    for item in envelope["response"].get("related_queries", {}).get(kind, [])[:12]:
                        text = item.get("query")
                        if not isinstance(text, str) or re.search(r"\b(lyrics|weather|meaning|definition|news)\b", text, re.I):
                            continue
                        eid = run.add_evidence("related_query", trends.public_url(row["text"], envelope["parameters"]), envelope["retrieved_at"], envelope["raw_file"], text, discovery_label=item.get("value"))
                        add(text, niches[row["niche_id"]], "provider_related", [eid], row["seed"], discovery_window=envelope["parameters"]["date"])
            except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
                run.warn(f"Related / {row['text']}: {error}")
        if windows == []:
            run.log("discover", "related_future_window", "Tháng/năm phân tích chưa có quan sát đến ngày chốt; không đổi sang mùa hoặc năm khác")
    # Source-backed discoveries precede model-only proposals, including when
    # the candidate cap is small. Both remain subject to the same source caps.
    from .trend_queries import product_context, research_focus
    product_context_keywords = []
    for key, keyword in list(keywords.items()):
        if product_context(keyword["text"], config):
            reason = ("Keyword dùng làm ngữ cảnh khám phá; thiếu nội dung hình/nhân vật/họa tiết/câu chữ cần tìm trên sản phẩm. Phôi, chất liệu hoặc kiểu áo chưa trả lời in gì."
                      if research_focus(config)["content_focus"] == "designs" else
                      "Keyword nhóm hàng dùng để khám phá; chưa chỉ rõ mẫu, hình dạng, định dạng, chất liệu, hoàn thiện hoặc chủ đề cụ thể để xếp hạng mẫu sản phẩm.")
            product_context_keywords.append({**keyword, "reason": reason})
            excluded.append({"keyword": keyword["text"], "niche_id": keyword["niche_id"], "origin": keyword["origin"],
                "kind": "product_context", "reason": reason, "evidence_ids": keyword["evidence_ids"]})
            run.log("discover", "product_context_only", reason, keyword=keyword["text"])
            del keywords[key]
    from .keyword_expansion import expand, product_key
    expansion, expansion_excluded = expand(run, client, config, niches, keywords, add, source_pages=contexts)
    excluded.extend(expansion_excluded)
    statuses.append(expansion)
    backed = [r for r in keywords.values() if r["evidence_ids"]]
    proposed = [r for r in keywords.values() if not r["evidence_ids"]]
    pool = [queue[i] for i in range(max(len(backed), len(proposed))) for queue in (backed, proposed) if i < len(queue)]
    cap = config["limits"]["candidate_keywords"]
    for row in pool[cap:]:
        excluded.append({"keyword": row["text"], "niche_id": row["niche_id"], "reason": "Ngoài trần ứng viên Trends; chưa được đo"})
    selected = pool[:cap]
    summary = {"requested_candidates": cap, "actual_candidates": len(selected),
               "unique_product_types": len({product_key(k["text"]) for k in selected}),
               "unique_product_models": len({product_key(k["text"]) for k in selected if k.get("candidate_level") in {"product_model", "exact_motif"}}),
               "research_focus": research_focus(config),
               "source_backed_candidates": sum(bool(k["evidence_ids"]) for k in selected),
               "content_candidates": sum(k.get("design_content_status") == "query_subject" for k in selected),
               "source_content_candidates": sum(k.get("design_content_status") == "query_subject" and bool(k["evidence_ids"]) for k in selected),
               "hypothesis_candidates": sum(not k["evidence_ids"] for k in selected),
               "expanded_candidates": sum(k["origin"] == "llm_expansion" for k in selected),
               "product_context_keywords": len(product_context_keywords),
               "note": "Số ứng viên là độ rộng khám phá, không phải thước đo độ chính xác. Chỉ Trends/listing/phản hồi thật mới kiểm chứng được từng hướng."}
    if research_focus(config)["content_focus"] == "designs":
        summary["content_coverage"] = [{"niche_id": nid, "name": niche["name"],
            "candidates": sum(k["niche_id"] == nid for k in selected),
            "source_candidates": sum(k["niche_id"] == nid and bool(k["evidence_ids"]) for k in selected)} for nid, niche in niches.items()]
        summary["note"] += " Đang tìm nội dung hình/nhân vật/họa tiết/câu chữ trên sản phẩm; keyword chỉ tả phôi, chất liệu hoặc kiểu áo được giữ làm ngữ cảnh khám phá."
    if len(selected) < cap:
        run.warn(f"Khám phá keyword: có {len(selected)}/{cap} ứng viên; không tự điền keyword trùng hoặc không phù hợp để đủ số lượng")
    run.log("discover", "discovery_coverage", "Độ phủ keyword trước đo Trends", **summary)
    return {"keywords": selected, "research_focus": research_focus(config), "product_context_keywords": product_context_keywords, "exclusions": excluded, "web_context": contexts, "discovery_sources": statuses, "summary": summary}
