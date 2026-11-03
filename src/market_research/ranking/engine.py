"""Different rankings answer different questions; ties remain ties."""
from ..common import identity

RANKINGS = {
    "keyword_growth": ("Tăng trưởng từ khóa", "keyword", "Cùng kỳ trên một chuỗi, nền đủ lớn; không phải search volume"),
    "seasonal_directions": ("Phù hợp kỳ bán", "direction", "Mẫu mùa vụ lịch sử và thời gian chuẩn bị nếu biết"),
    "direction_opportunity": ("Hướng ưu tiên nghiên cứu", "direction", "Chỉ shortlist đủ điều kiện; thứ tự rubric, không phải xác suất thành công"),
    "amazon_purchase_signal": ("Tín hiệu mua Amazon", "product", "Nhãn mua làm tròn; cùng loại trang và cùng ngày quan sát"),
    "comparable_price": ("Giá các offer cùng quy cách", "offer", "Chỉ so cùng sản phẩm, biến thể và tiền tệ; không phải best value"),
    "differentiation_candidates": ("Ý tưởng khác biệt", "idea", "Cải thiện có đoạn nguồn hỗ trợ; vẫn là giả thuyết cần thử"),
    "evidence_strength": ("Độ phủ bằng chứng", "direction", "Số loại bằng chứng độc lập về mặt thông tin; không phải lợi nhuận"),
    "niche_priority": ("Niche ưu tiên", "niche", "Hướng shortlist tốt nhất trong mỗi niche; không ưu ái số lượng listing"),
    "product_research_shortlist": ("Mẫu nên đối chiếu", "product", "Mẫu đạt điều kiện thuộc hướng shortlist; không phải top bán chạy"),
    "idea_priority": ("Idea ưu tiên", "idea", "Trạng thái hướng và căn cứ của idea; chưa khẳng định hiệu quả kinh doanh"),
}


def rubric_key(assessment):
    # Unknown is a separate category. Only comparable known positives are ordered.
    return tuple(assessment[k] == "positive" for k in ("season", "demand", "purchase", "differentiation", "business_fit"))


def known_group(assessment):
    return "known-" + "".join("0" if assessment[k] == "unknown" else "1" for k in ("season", "demand", "purchase", "differentiation", "business_fit"))


def build(config, directions, collected, assessment, histories, ideas):
    items, definitions = [], []
    by_assessment = {r["direction_id"]: r for r in assessment["directions"]}
    products = {p["product_id"]: p for p in collected["products"]}
    for rid, (label, entity_type, scope) in RANKINGS.items():
        groups = {}
        def add(group, entity, metric, evidence, **extra):
            groups.setdefault(group, []).append({"entity_id": entity, "metric": metric, "evidence_ids": evidence, **extra})
        for d in directions:
            a = by_assessment[d["id"]]
            if rid == "keyword_growth" and a["growth_pct"] is not None:
                add(d["niche_id"] + ":" + a["growth_scope"], d["keyword_id"], a["growth_pct"], a["evidence_ids"])
            if rid == "seasonal_directions" and a["season_fit_pct"] is not None:
                add(d["niche_id"], d["id"], a["season_fit_pct"], a["evidence_ids"])
            if rid == "direction_opportunity" and a["status"] == "shortlist":
                add(d["niche_id"] + ":" + known_group(a), d["id"], rubric_key(a), a["evidence_ids"])
            if rid == "evidence_strength" and a["evidence_ids"]:
                coverage = (bool(a["product_ids"]), bool(a["review_ids"]), any(h["direction_id"] == d["id"] and h["status"] == "available" for h in histories))
                add(d["niche_id"], d["id"], coverage, a["evidence_ids"])
        if rid == "niche_priority":
            for niche in config["niches"]:
                candidates = [a for a in assessment["directions"] if a["niche_id"] == niche["id"] and a["status"] == "shortlist"]
                for group in {known_group(a) for a in candidates}:
                    best = max([a for a in candidates if known_group(a) == group], key=rubric_key)
                    add("category:" + group, niche["id"], rubric_key(best), best["evidence_ids"])
        if rid == "amazon_purchase_signal":
            for p in products.values():
                if p["purchase_lower_bound"] is not None:
                    add(str(p["purchase_scope"]) + ":" + p["observed_at"][:10], p["product_id"], p["purchase_lower_bound"], p["evidence_ids"])
        if rid == "comparable_price":
            price_groups = {}
            for o in collected["offers"]:
                if o["price"] is not None and o["currency"] and o.get("variant") is not None:
                    key = identity("comparable", o["product_id"], o["variant"], o["currency"], o["observed_at"][:10])
                    price_groups.setdefault(key, []).append(o)
            for group, rows in price_groups.items():
                if len(rows) >= 2:
                    for o in rows:
                        add(group, o["offer_id"], -o["price"], o["evidence_ids"], price=o["price"])
        if rid == "product_research_shortlist":
            for p in products.values():
                eligible = [by_assessment[d] for d in p["direction_ids"] if d in by_assessment and by_assessment[d]["status"] == "shortlist" and p["product_id"] in by_assessment[d]["product_ids"]]
                if eligible:
                    best = max(eligible, key=rubric_key)
                    add(best["niche_id"] + ":" + known_group(best), p["product_id"], rubric_key(best), p["evidence_ids"])
        if rid in {"idea_priority", "differentiation_candidates"}:
            for idea in ideas:
                if rid == "differentiation_candidates" and not idea["improvement_evidence_ids"]:
                    continue
                a = by_assessment[idea["direction_id"]]
                if a["status"] == "shortlist":
                    add(("category" if rid == "idea_priority" else idea["niche_id"]) + ":" + known_group(a), idea["id"], rubric_key(a), idea["evidence_ids"])
        count = 0
        for group, rows in groups.items():
            ordered_metrics = sorted({tuple(r["metric"]) if isinstance(r["metric"], (list, tuple)) else r["metric"] for r in rows}, reverse=True)
            for row in rows:
                metric = tuple(row["metric"]) if isinstance(row["metric"], (list, tuple)) else row["metric"]
                items.append({"ranking_id": rid, "group": group, "rank": ordered_metrics.index(metric)+1, **row})
                count += 1
        definitions.append({"id": rid, "label": label, "entity_type": entity_type, "scope": scope, "version": "2.0",
            "tie_policy": "dense_rank; ID chỉ ổn định hiển thị", "sort": "descending metric within comparable group", "status": "available" if count else "unavailable",
            "unknown_policy": "Nhóm known-abcde theo độ đủ thông tin mùa/cầu/mua/khác biệt/phù hợp; không so thứ hạng giữa các nhóm, unknown không thành negative",
            "reason": None if count else "Chưa có đủ mẫu/quan sát tương thích để xếp hạng", "count": count})
    return {"definitions": definitions, "items": sorted(items, key=lambda r: (r["ranking_id"], r["group"], r["rank"], r["entity_id"]))}
