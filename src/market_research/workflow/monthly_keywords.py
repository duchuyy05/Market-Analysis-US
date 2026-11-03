"""Candidate-wide historical month evidence before product-query selection."""
from ..common import identity
from ..analysis.keyword_monthly import build
from . import history
from .trend_queries import measurement_query


def _key(value):
    return " ".join(str(value or "").casefold().split())


def analyze(run, client, config, discovery, screening):
    enabled = config.get("trends", {}).get("monthly_rankings", False)
    if not enabled or config["mode"] == "offline" or not config["sources"]["trends"]:
        reason = "Tắt phân tích keyword theo tháng" if not enabled else "Bộ offline không gọi thêm lịch sử ứng viên" if config["mode"] == "offline" else "Nguồn Trends đã tắt"
        return {"status": "skipped", "histories": [], "rankings": {"status": "skipped", "months": [], "rows": [], "coverage": {}, "note": reason},
                "requested_keywords": 0, "observed_keywords": 0, "target_keywords": 0, "candidate_keywords": 0, "note": reason}
    metrics = {r["keyword_id"]: r for r in screening.get("rows", [])}
    keywords = []
    for original in discovery.get("keywords", []):
        metric = metrics.get(original["id"], {})
        query = metric.get("measurement_query") or measurement_query(original["text"])
        keywords.append({**original, "measurement_query": query,
            "measurement_scope": metric.get("measurement_scope") or ("exact_keyword" if _key(query) == _key(original["text"]) else "broader_product_type")})
    by_id = {k["id"]: k for k in keywords}
    # Prefer the proven screening leaders, then alternate the remaining niches.
    # The cap counts queries, not the number of repeated niche contexts.
    ranked_ids = [r["keyword_id"] for r in sorted(screening.get("rows", []), key=lambda r: r.get("rank") or float("inf"))
                  if r.get("rank") is not None and r["keyword_id"] in by_id]
    ranked_set = set(ranked_ids)
    queues = [[k["id"] for k in keywords if k["niche_id"] == niche and k["id"] not in ranked_set]
              for niche in dict.fromkeys(k["niche_id"] for k in keywords)]
    remaining_ids = [q[i] for i in range(max(map(len, queues), default=0)) for q in queues if i < len(q)]
    maximum = min(config["limits"].get("monthly_keywords", 64), config["limits"].get("candidate_keywords", 32))
    chosen = set()
    for kid in ranked_ids + remaining_ids:
        query = _key(by_id[kid]["measurement_query"])
        if query and (query in chosen or len(chosen) < maximum):
            chosen.add(query)
    directions = []
    for kid in ranked_ids + remaining_ids:
        keyword = by_id[kid]
        if _key(keyword["measurement_query"]) in chosen:
            directions.append({"id": identity("D", keyword["niche_id"], keyword["id"]),
                "keyword_id": keyword["id"], "niche_id": keyword["niche_id"], "keyword": keyword["text"],
                "measurement_query": keyword["measurement_query"], "measurement_scope": keyword["measurement_scope"]})
    run.log("monthly", "monthly_history_plan", "Lấy chuỗi ứng viên để so các tháng trước khi chọn keyword tìm sản phẩm",
            requested_keywords=len(chosen), target_keywords=maximum, candidate_keywords=len({_key(k["measurement_query"]) for k in keywords}),
            anchor=config["trends"]["anchor"])
    histories = history.analyze(run, client, config, directions, anchor=config["trends"]["anchor"])
    by_direction = {d["id"]: d for d in directions}
    histories = [{**h, "keyword_id": by_direction[h["direction_id"]]["keyword_id"],
                  "keyword": by_direction[h["direction_id"]]["keyword"], "niche_id": by_direction[h["direction_id"]]["niche_id"],
                  "measurement_query": by_direction[h["direction_id"]]["measurement_query"],
                  "measurement_scope": by_direction[h["direction_id"]]["measurement_scope"]} for h in histories]
    observed = len({_key(h["measurement_query"]) for h in histories if h.get("status") == "available" and any(
        r.get("value") is not None and r.get("status") in {"complete", "partial"} for r in h.get("monthly", []))})
    rankings = build(config, keywords, histories)
    status = "unavailable" if not observed else "available" if rankings["status"] == "available" else "partial"
    note = (f"Lịch sử có quan sát cho {observed}/{len(chosen)} truy vấn yêu cầu, trong {len({_key(k['measurement_query']) for k in keywords})} loại truy vấn ứng viên. "
            "Hạng phù hợp tháng khác hạng nhu cầu theo anchor; không coi keyword chưa có chuỗi là đã xác minh. "
            "Giới hạn thu thập vẫn nằm trong các trần API đã chọn; đủ số ứng viên không bảo đảm đủ chuỗi hoặc ý tưởng.")
    run.log("monthly", "monthly_history_completed", note, requested_keywords=len(chosen), observed_keywords=observed,
            ranking_coverage=rankings["coverage"], status=status)
    return {"status": status, "histories": histories, "rankings": rankings, "requested_keywords": len(chosen),
            "observed_keywords": observed, "target_keywords": maximum, "candidate_keywords": len({_key(k["measurement_query"]) for k in keywords}), "note": note}
