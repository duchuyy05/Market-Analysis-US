"""Choose product queries for the requested selling months using observed history."""
from math import isfinite
from statistics import median


def _key(value):
    return " ".join(str(value or "").casefold().split())


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _percentile(values, value):
    if len(values) < 2:
        return .5
    return (sum(v < value for v in values) + (sum(v == value for v in values) - 1) / 2) / (len(values) - 1)


def priority(config, discovery, screening, rankings):
    """Return screening-compatible rows; recent observations are never rewritten.

    The resulting rank is historical selling-window suitability in the current
    candidate set, not a forecast of absolute demand or a marketplace bestseller
    rank. Missing monthly evidence cannot inherit a verified historical rank.
    """
    months = sorted(set(config["selling_months"]))
    metadata = {k["id"]: k for k in discovery.get("keywords", [])}
    allowed_queries = {_key(r.get("measurement_query") or metadata.get(r["keyword_id"], {}).get("text") or r.get("keyword"))
                       for r in screening.get("rows", [])}
    by_query = {}
    for row in rankings.get("rows", []):
        if row.get("month") in months and _key(row.get("measurement_query")) in allowed_queries:
            by_query.setdefault(_key(row.get("measurement_query")), {})[row["month"]] = row
    candidates, groups = {}, {}
    for query, monthly in by_query.items():
        rows = [monthly.get(month, {}) for month in months]
        if not months or not all(r.get("status") == "available" and r.get("demand_metric_kind") == "query_to_anchor_ratio"
            and _number(r.get("demand_metric")) and _number(r.get("seasonal_score"))
            and len(r.get("usable_years", [])) >= 2 and len(r.get("demand_years", [])) >= 2 and r.get("comparison_group") for r in rows):
            continue
        common = {r["comparison_group"] for r in rows}
        if len(common) != 1:
            continue
        common_years = sorted(set.intersection(*(set(r["usable_years"]) & set(r["demand_years"]) for r in rows)))
        if len(common_years) < 2:
            continue
        group = common.pop()
        candidates[query] = {"comparison_group": group, "monthly_demand_ratio": round(median(r["demand_metric"] for r in rows), 6),
            "seasonal_score": round(median(r["seasonal_score"] for r in rows), 3),
            "evidence_ids": sorted({e for r in rows for e in r.get("evidence_ids", [])}),
            "usable_years": common_years,
            "comparison_label": rows[0].get("comparison_label")}
        groups.setdefault(group, []).append(query)
    primary = min(groups, key=lambda group: (-len(groups[group]), group)) if groups else None
    chosen = {query: data for query, data in candidates.items() if data["comparison_group"] == primary}
    if not chosen:
        return {**screening, "rows": [{**row, "selection_basis": "recent_interest_fallback", "selection_months": months,
            "recent_rank": row.get("rank"), "recent_score": row.get("score"), "recent_status": row.get("status"),
            "recent_relative_interest": row.get("relative_interest"), "recent_growth_pct": row.get("growth_pct"),
            "monthly_demand_ratio": None, "seasonal_score": None} for row in screening.get("rows", [])],
            "method": "recent_screening_fallback_v1", "selection_basis": "recent_interest_fallback", "selection_months": months,
            "monthly_measured_keywords": 0, "monthly_selection_status": "unavailable",
            "note": screening.get("note", "") + " Chưa có keyword đủ lịch sử cho toàn bộ tháng bán trên một anchor chung. Tạm chọn theo phép đo gần đây nếu có; đây không phải xác minh nhu cầu trong kỳ bán hoặc dự báo năm đích."}
    interests = [data["monthly_demand_ratio"] for data in chosen.values()]
    fits = [data["seasonal_score"] for data in chosen.values()]
    for data in chosen.values():
        data["score"] = round(100 * (.7 * _percentile(interests, data["monthly_demand_ratio"]) + .3 * _percentile(fits, data["seasonal_score"])), 3)
    scores = sorted({data["score"] for data in chosen.values()}, reverse=True)
    rows = []
    for original in screening.get("rows", []):
        query = _key(original.get("measurement_query") or metadata.get(original["keyword_id"], {}).get("text") or original.get("keyword"))
        monthly = chosen.get(query)
        row = {**original, "recent_rank": original.get("rank"), "recent_score": original.get("score"), "recent_status": original.get("status"),
            "recent_reason": original.get("reason"), "recent_relative_interest": original.get("relative_interest"), "recent_growth_pct": original.get("growth_pct"),
            "selection_basis": "historical_selling_months", "selection_months": months,
            "rank": None, "score": None, "monthly_demand_ratio": None, "seasonal_score": None, "monthly_comparison_group": None}
        if monthly:
            row.update(status="available", rank=scores.index(monthly["score"]) + 1, score=monthly["score"],
                monthly_demand_ratio=monthly["monthly_demand_ratio"], seasonal_score=monthly["seasonal_score"],
                monthly_comparison_group=monthly["comparison_group"], monthly_usable_years=monthly["usable_years"],
                monthly_evidence_ids=monthly["evidence_ids"], evidence_ids=sorted(set(original.get("evidence_ids", []) + monthly["evidence_ids"])),
                reason="Ưu tiên tháng " + ", ".join(map(str, months)) + f": trung vị tỷ lệ so anchor {monthly['monthly_demand_ratio']:.3f}; phù hợp mùa {monthly['seasonal_score']:.1f}%. Chỉ dựa trên các năm đã quan sát, chưa phải dự báo nhu cầu tuyệt đối.")
        else:
            row.update(status="unavailable", reason="Chưa đủ chuỗi cho toàn bộ tháng bán trên cùng anchor; không đưa vào hạng lịch sử đã xác minh.")
        rows.append(row)
    return {**screening, "rows": rows, "method": "shared_anchor_selling_months_percentile_v1",
        "selection_basis": "historical_selling_months", "selection_months": months,
        "monthly_comparison_group": primary, "monthly_measured_keywords": len(chosen), "measured_keywords": len(chosen),
        "monthly_selection_status": "available", "excluded_comparison_groups": len(groups) - 1,
        "note": "Ưu tiên tìm mẫu cho tháng " + ", ".join(map(str, months)) + ": 70% phân vị tỷ lệ nhu cầu lịch sử so anchor + 30% phân vị phù hợp mùa (mức so đỉnh riêng của keyword). "
            f"Có {len(chosen)} truy vấn đủ bằng chứng trong cùng nhóm anchor; {len(groups)-1} nhóm thang đo khác không trộn vào thứ hạng. "
            "Đây là lựa chọn kỳ bán từ lịch sử trong tập ứng viên, không phải lượng tìm kiếm, doanh số hay dự báo tuyệt đối năm đích. Phép đo gần đây, nếu có, được trình bày riêng và không trộn vào thứ hạng lịch sử."}


# Pipeline name and direct analysis callers share exactly one implementation.
prioritize = priority
