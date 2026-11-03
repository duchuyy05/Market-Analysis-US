"""Track every keyword's provenance; related discovery failure is recoverable."""
import re
from ..common import identity, tokens
from ..providers import trends, web
from ..providers.client import SourceError
from ..llm.client import complete
from ..business.domain import classify


def discover(run, client, config):
    keywords, excluded, contexts = {}, [], []
    for niche in config["niches"]:
        for seed in niche["seeds"]:
            fit = classify(seed, config)
            if fit["status"] != "allowed":
                excluded.append({"keyword": seed, "niche_id": niche["id"], "reason": fit["reason"], "kind": "company_domain", "business_fit": fit})
                continue
            key = identity("K", niche["id"], seed.casefold())
            keywords[key] = {"id": key, "niche_id": niche["id"], "text": seed, "seed": seed,
                "origin": "archive_seed" if config["mode"] == "offline" else "user" if any(seed in n.get("seeds", []) for n in run.manifest["input"].get("niches", [])) else "llm_candidate", "evidence_ids": [], "discovery_type": "seed"}
        if config["mode"] == "offline":
            run.warn("Offline: không có phản hồi Related Queries/Shopping đã lưu; không tạo dữ liệu thay thế.")
            continue
        if config["sources"]["trends"] and config.get("trends", {}).get("history_scope") != "seasonal":
            for seed in niche["seeds"][:config["limits"]["related_seeds_per_niche"]]:
                try:
                    envelope = trends.related(client, seed, config["as_of_date"])
                    url = trends.public_url(seed, envelope["parameters"])
                    for kind in ("rising", "top"):
                        rows = (envelope["response"].get("related_queries") or {}).get(kind, [])
                        for item in rows:
                            query = item.get("query")
                            if not isinstance(query, str) or not 2 <= len(query) <= 200:
                                continue
                            if len([k for k in keywords.values() if k["niche_id"] == niche["id"]]) >= config["limits"]["keywords_per_niche"]:
                                break
                            if re.search(r"\b(meaning|definition|news|movie|lyrics|near me|weather)\b", query, re.I) or not tokens(query) & tokens(seed):
                                excluded.append({"keyword": query, "niche_id": niche["id"], "reason": "Ngoài phạm vi seed hoặc ý định thông tin"})
                                continue
                            fit = classify(query, config)
                            if fit["status"] != "allowed":
                                excluded.append({"keyword": query, "niche_id": niche["id"], "reason": fit["reason"], "kind": "company_domain", "business_fit": fit})
                                continue
                            eid = run.add_evidence("related_query", item.get("link") or url, envelope["retrieved_at"], envelope["raw_file"], query, discovery_label=item.get("value"), seed=seed)
                            key = identity("K", niche["id"], query.casefold())
                            if key in keywords:
                                keywords[key]["evidence_ids"] = sorted(set(keywords[key]["evidence_ids"] + [eid]))
                            else:
                                keywords[key] = {"id": key, "niche_id": niche["id"], "text": query, "seed": seed, "origin": "provider_related", "discovery_type": kind, "discovery_label": item.get("value"), "evidence_ids": [eid]}
                except SourceError as error:
                    run.warn(f"Related Queries / {seed}: {error}")
        if config["sources"]["web"]:
            try:
                envelope = web.search(client, niche.get("name_en", niche["name"]) + " USA products customer reviews " + str(config["target_year"]))
                for item in envelope["response"].get("results", []):
                    from ..common import safe_url
                    if not safe_url(item.get("url")):
                        continue
                    eid = run.add_evidence("web_context", item["url"], envelope["retrieved_at"], envelope["raw_file"], item.get("content", "")[:2500], published_at=item.get("published_date"))
                    contexts.append({"niche_id": niche["id"], "title": item.get("title"), "evidence_ids": [eid]})
            except SourceError as error:
                run.warn(f"Web / {niche['name']}: {error}")
    return {"keywords": list(keywords.values()), "exclusions": excluded, "web_context": contexts}


def cluster(run, client, config, discovery):
    output = []
    used = sum(u["provider"] == "openrouter" for u in run.manifest["usage"])
    llm_available = used < config["limits"]["llm_requests"]
    if config["mode"] == "live" and config["llm"]["enabled"] and not llm_available:
        run.log("cluster", "seed_grouping", "Đã hết trần LLM; gom nhóm theo seed bằng Python, không gửi yêu cầu mới", used=used, cap=config["limits"]["llm_requests"])
    for niche in config["niches"]:
        candidates = [k for k in discovery["keywords"] if k["niche_id"] == niche["id"]]
        by_id = {k["id"]: k for k in candidates}
        groups = []
        method = "seed_rules"
        if config["mode"] == "live" and config["llm"]["enabled"] and llm_available:
            try:
                result = complete(client, "cluster", {"niche": niche, "max_directions": config["limits"]["directions_per_niche"], "keywords": candidates})
                for g in result.get("directions", [])[:config["limits"]["directions_per_niche"]]:
                    ids = g.get("keyword_ids")
                    if not isinstance(ids, list) or not ids or any(i not in by_id for i in ids) or g.get("representative_keyword_id") not in ids or not isinstance(g.get("name"), str):
                        raise ValueError("Nhóm keyword dẫn ID không hợp lệ")
                    # Queries stay grounded in a real selected candidate.
                    groups.append({**g, "search_query": by_id[g["representative_keyword_id"]]["text"]})
                if not groups:
                    raise ValueError("Không có hướng sản phẩm")
                method = "llm"
            except (SourceError, ValueError, TypeError, AttributeError) as error:
                run.warn(f"Nhóm keyword / {niche['name']}: {error}; dùng nhóm truy vết theo seed")
                groups = []
            llm_available = sum(u["provider"] == "openrouter" for u in run.manifest["usage"]) < config["limits"]["llm_requests"]
        if not groups:
            for seed in niche["seeds"]:
                rows = [k for k in candidates if k["seed"] == seed]
                main = next((k for k in rows if k["text"] == seed), rows[0] if rows else None)
                if main:
                    groups.append({"name": niche.get("seed_labels", {}).get(seed, seed), "representative_keyword_id": main["id"], "keyword_ids": [k["id"] for k in rows], "customer_hypothesis": niche.get("customer_hypothesis", "Khách hàng dự kiến cần kiểm chứng từ nguồn")})
            groups = groups[:config["limits"]["directions_per_niche"]]
        for group in groups:
            main = by_id[group["representative_keyword_id"]]
            output.append({"id": identity("D", niche["id"], main["id"]), "niche_id": niche["id"], "name": group["name"],
                "grouping_method": method,
                "keyword_id": main["id"], "keyword": main["text"], "keyword_ids": group["keyword_ids"],
                "search_query": main["text"], "customer_hypothesis": group.get("customer_hypothesis") or niche.get("customer_hypothesis", "Chưa xác minh đối tượng khách hàng"),
                "evidence_ids": sorted({e for i in group["keyword_ids"] for e in by_id[i]["evidence_ids"]})})
    return output
