"""Calendar-month evidence without confusing seasonal fit with search volume.

The helper is pure: it never fetches data or fills absent months. Demand ranks
are restricted to a declared shared normalization context; seasonal-fit ranks
use each keyword's own historical peak and can span those contexts.
"""
from math import isfinite
from statistics import median, mean, pstdev

from ..common import identity


def _key(value):
    return " ".join(str(value or "").casefold().split())


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def _observations(history):
    return {(row.get("year"), row.get("month")): row for row in history.get("monthly", [])
            if isinstance(row, dict)}


def _complete(row):
    return row.get("status") == "complete" and _number(row.get("value"))


def _scope_months(history, config=None):
    context = history.get("normalization_context") or {}
    trends = (config or {}).get("trends", {})
    seasonal = history.get("history_scope") == "seasonal" or context.get("history_scope") == "seasonal" or trends.get("history_scope") == "seasonal"
    if not seasonal:
        return list(range(1, 13))
    return sorted(set(history.get("history_months") or history.get("collected_months") or context.get("history_months") or context.get("collected_months") or trends.get("history_months") or [10, 11, 12]))


def _usable_years(history, years, config=None):
    periods = _observations(history)
    declared = history.get("usable_years")
    scope_months = _scope_months(history, config)
    seasonal = len(scope_months) < 12
    result = []
    for year in years:
        rows = [periods.get((year, month), {}) for month in scope_months]
        if not all(_complete(row) for row in rows):
            continue
        if declared is not None:
            signal = year in declared
        else:
            # Match the history branch's conservative native-resolution rule.
            native_month = any((row.get("native_step_days") or 0) >= 27 for row in rows)
            signal = any(row["value"] > 0 for row in rows) and (native_month or sum(row.get("positive_points", 0) for row in rows) >= 3) if seasonal else sum(row["value"] > 0 for row in rows) >= 2 and max(row["value"] for row in rows) >= 5 and (native_month or sum(row.get("positive_points", 0) for row in rows) >= 8)
        if signal:
            result.append(year)
    return result


def _demand(history, years, month, config):
    """Return a metric plus its comparable group, never a global raw-index rank."""
    context = history.get("normalization_context") or {}
    periods = _observations(history)
    date_range = context.get("date_range")
    market = context.get("market", config.get("market", "US"))
    query = history.get("measurement_query")
    anchor = context.get("anchor")
    anchor_rows = history.get("anchor_monthly") or context.get("anchor_monthly") or []
    if context.get("scale") == "anchor_ratio_100" and anchor and date_range:
        # Separate yearly windows were calibrated during collection. Dividing
        # this by the original anchor again would silently corrupt the scale.
        observed = [(year, periods.get((year, month), {})) for year in years]
        ratios = [(year, row["value"] / 100) for year, row in observed if _complete(row)]
        if len(ratios) >= 2:
            return {"demand_metric": round(median(value for _, value in ratios), 6), "demand_metric_kind": "query_to_anchor_ratio",
                    "comparison_group": identity("MK", "seasonal_anchor", _key(anchor), market, context.get("periods") or date_range, _scope_months(history, config), config["history_years"]),
                    "comparison_label": "Cùng anchor " + str(anchor) + " trong các tháng đã chọn", "demand_years": [year for year, _ in ratios]}
    if anchor and date_range and anchor_rows:
        anchors = {(r.get("year"), r.get("month")): r for r in anchor_rows if isinstance(r, dict)}
        ratios = [periods[year, month]["value"] / anchors[year, month]["value"] for year in years
                  if _complete(anchors.get((year, month), {})) and anchors[year, month]["value"] >= 1]
        if len(ratios) >= 2:
            return {"demand_metric": round(median(ratios), 6), "demand_metric_kind": "query_to_anchor_ratio",
                    "comparison_group": identity("MK", "anchor", _key(anchor), market, date_range, config["history_years"]),
                    "comparison_label": "Cùng anchor " + str(anchor), "demand_years": [y for y in years if _complete(anchors.get((y, month), {})) and anchors[y, month]["value"] >= 1]}
    queries = context.get("queries") or []
    if context.get("scale") == "shared_0_100" and len(queries) >= 2 and _key(query) in {_key(q) for q in queries}:
        # Older saved histories do not have a request id. Their exact query set
        # and frozen window identify only that batch, never other query sets.
        window = date_range or f"{min(config['history_years'])}-01-01 {config['as_of_date']}"
        return {"demand_metric": round(median(periods[year, month]["value"] for year in years), 6),
                "demand_metric_kind": "same_batch_index",
                "comparison_group": identity("MK", "batch", sorted(_key(q) for q in queries), market, window),
                "comparison_label": "Cùng batch " + ", ".join(map(str, queries)), "demand_years": list(years)}
    return {"demand_metric": None, "demand_metric_kind": None, "comparison_group": None,
            "comparison_label": "Không có thang so sánh chung giữa keyword", "demand_years": []}


def build(config, keywords, histories):
    """Build all 12 months; ``keywords`` may be the entire discovery pool.

    Each keyword uses one intact historical series. ``keyword_id`` can bind a
    history directly; otherwise ``measurement_query`` binds it. Distinct niche
    contexts sharing a query stay attached without multiplying its rank.
    For cross-batch demand comparisons provide normalization_context.anchor,
    .date_range, .market and anchor_monthly (calendar monthly row schema).
    """
    years = sorted(set(y for y in config["history_years"] if y < config["target_year"]))
    by_id = {h.get("keyword_id"): h for h in histories if h.get("keyword_id")}
    by_query = {}
    for history in histories:
        key = _key(history.get("measurement_query"))
        if key:
            previous = by_query.get(key)
            if previous is None or len(_usable_years(history, years, config)) > len(_usable_years(previous, years, config)):
                by_query[key] = history
    candidates = {}
    for keyword in keywords:
        linked = by_id.get(keyword.get("id"), {})
        query = keyword.get("measurement_query") or linked.get("measurement_query") or keyword.get("text") or keyword.get("keyword")
        key = _key(query)
        if not key:
            continue
        item = candidates.setdefault(key, {"keyword_id": keyword.get("id"), "keyword_ids": [], "keyword": keyword.get("text") or keyword.get("keyword") or query,
            "measurement_query": query, "measurement_scope": keyword.get("measurement_scope") or linked.get("measurement_scope", "exact_keyword"), "niche_ids": [], "keywords": []})
        for field, value in (("keyword_ids", keyword.get("id")), ("niche_ids", keyword.get("niche_id")), ("keywords", keyword.get("text") or keyword.get("keyword") or query)):
            if value and value not in item[field]:
                item[field].append(value)
    rows, covered = [], 0
    for key, candidate in candidates.items():
        history = by_query.get(key) or by_id.get(candidate["keyword_id"]) or {}
        periods = _observations(history)
        scope_months = _scope_months(history, config)
        seasonal_scope = len(scope_months) < 12
        usable = _usable_years(history, years, config)
        eligible = len(usable) >= 2
        covered += eligible
        peaks = {y: max(periods[y, m]["value"] for m in scope_months) for y in usable}
        for month in range(1, 13):
            in_scope = month in scope_months
            seasonal = [periods[y, month]["value"] / peaks[y] * 100 for y in usable if peaks[y] > 0] if in_scope else []
            score = round(median(seasonal), 3) if eligible and in_scope else None
            values = [periods[y, month]["value"] for y in usable] if in_scope else []
            cv = round(pstdev(values) / mean(values), 4) if eligible and values and mean(values) > 0 else None
            latest = max(usable) if usable and in_scope else None
            previous = periods.get((latest - 1, month), {}) if latest else {}
            yoy = round((periods[latest, month]["value"] / previous["value"] - 1) * 100, 3) if latest and latest - 1 in usable and _complete(previous) and previous["value"] > 0 else None
            prediction = next((f.get("prediction") for f in history.get("forecast", []) if f.get("year") == config["target_year"] and f.get("month") == month), None) if in_scope else None
            demand = _demand(history, usable, month, config) if eligible and in_scope else {"demand_metric": None, "demand_metric_kind": None, "comparison_group": None, "comparison_label": "Ngoài phạm vi thu thập" if not in_scope else "Chưa đủ lịch sử", "demand_years": []}
            reason = "Tháng ngoài phạm vi thu thập; không có phép đo hoặc xếp hạng." if not in_scope else f"Cùng tháng của {len(usable)} năm đủ tín hiệu; trung vị mức so đỉnh riêng trong {'các tháng đã chọn' if seasonal_scope else 'năm'} {score:.1f}%." if eligible else f"Chỉ {len(usable)}/{len(years)} năm có đủ {len(scope_months)} tháng trong phạm vi và tín hiệu; cần ít nhất hai chu kỳ."
            rows.append({**candidate, "month": month, "target_year": config["target_year"], "selling_month": month in config["selling_months"],
                "status": "not_collected" if not in_scope else "available" if eligible and score > 0 else "low_signal" if eligible else "insufficient_history",
                "seasonal_score": score, "seasonality_rank": None, "demand_rank": None, **demand,
                "usable_years": usable, "historical_years_requested": years, "year_observations": [
                    {"year": y, "value": periods.get((y, month), {}).get("value") if in_scope and _complete(periods.get((y, month), {})) else None,
                     "status": "not_collected" if not in_scope else periods.get((y, month), {}).get("status", "unavailable")} for y in years],
                "history_scope": "seasonal" if seasonal_scope else "full", "history_months": scope_months,
                "metric_unit": "anchor_100" if history.get("normalization_context", {}).get("scale") == "anchor_ratio_100" else "trends_index_0_100",
                "month_cv": cv, "latest_yoy_pct": yoy, "prediction": prediction,
                "evidence_ids": list(history.get("evidence_ids") or []), "reason": reason,
                "history_confidence": history.get("validation", {}).get("confidence", {}).get("level", "unassessed")})
    months = []
    requested_months = _scope_months({}, config)
    for month in range(1, 13):
        eligible = [r for r in rows if r["month"] == month and r["status"] == "available"]
        scores = sorted({r["seasonal_score"] for r in eligible}, reverse=True)
        groups = {}
        for row in eligible:
            row["seasonality_rank"] = scores.index(row["seasonal_score"]) + 1
            if row["comparison_group"] and row["demand_metric"] is not None:
                groups.setdefault(row["comparison_group"], []).append(row)
        for group in groups.values():
            if len(group) < 2:
                continue
            values = sorted({r["demand_metric"] for r in group}, reverse=True)
            for row in group:
                row["demand_rank"] = values.index(row["demand_metric"]) + 1
        ranked = sorted(eligible, key=lambda r: (r["seasonality_rank"], _key(r["measurement_query"])))
        months.append({"month": month, "selling_month": month in config["selling_months"],
            "status": "not_collected" if month not in requested_months else "available" if len(eligible) == len(candidates) and eligible else "partial" if eligible else "unavailable",
            "ranked_keywords": len(eligible), "candidate_keywords": len(candidates), "rankings": ranked,
            "comparison_groups": [{"id": gid, "label": group[0]["comparison_label"], "keyword_count": len(group),
                "demand_rank_available": len(group) >= 2} for gid, group in groups.items()]})
    return {"status": "available" if covered == len(candidates) and covered else "partial" if covered else "unavailable",
        "method": "calendar_month_seasonal_fit_v1", "months": months, "rows": rows,
        "coverage": {"candidate_keywords": len(candidates), "original_keyword_contexts": len(keywords), "keywords_with_two_complete_cycles": covered,
            "keywords_missing_two_complete_cycles": len(candidates) - covered, "history_years": years, "history_months": requested_months,
            "history_scope": "seasonal" if len(requested_months) < 12 else "full"},
        "note": ("Chỉ phân tích các tháng " + ", ".join(map(str, requested_months)) + "; tháng ngoài phạm vi không thu và không xếp hạng. Đỉnh tham chiếu nằm trong các tháng đã chọn, không phải đỉnh của cả năm. Thang anchor=100 có thể vượt 100. " if len(requested_months) < 12 else "Hạng phù hợp tháng so mức quan tâm của từng keyword với đỉnh riêng trong năm, ") + "không phải hạng lượng tìm kiếm hay doanh số. Hạng nhu cầu chỉ so trong cùng nhóm thang đo (anchor chung hoặc cùng batch); không so hạng giữa các nhóm. Chỉ dùng năm trước năm đích; tháng/năm thiếu giữ trống, không nội suy để đủ số lượng. Độ phủ và số keyword không phải xác suất chính xác."}
