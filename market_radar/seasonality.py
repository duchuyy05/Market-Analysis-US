"""Calendar-month comparisons from fixed-window Google Trends series."""
import calendar
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode


def overlap_days(start, end, lower, upper):
    """All intervals are [start, end); assign crossing weeks by their overlapping days."""
    return max(0, (min(end, upper) - max(start, lower)).days)


def parse_series(envelope, batch, keywords, anchor):
    by_term = {item["keyword"]: item for item in keywords}
    timeline = (envelope["response"].get("interest_over_time") or {}).get("timeline_data", [])
    series = []
    for index, point in enumerate(timeline):
        start = datetime.fromtimestamp(int(point["timestamp"]), timezone.utc).date()
        end = datetime.fromtimestamp(int(timeline[index + 1]["timestamp"]), timezone.utc).date() if index + 1 < len(timeline) else start + timedelta(days=7)
        values = {v.get("query"): v for v in point.get("values", [])}
        anchor_value = values.get(anchor, {}).get("extracted_value")
        for term, keyword in by_term.items():
            item = values.get(term)
            if not item:
                continue
            value = item.get("extracted_value")
            series.append({"keyword_id": keyword["keyword_id"], "keyword": term,
                "component_id": keyword["id"], "batch_id": batch["batch_id"],
                "period_start": start.isoformat(), "period_end_exclusive": end.isoformat(),
                "interest_index": value if isinstance(value, (int, float)) else None,
                "value_raw": item.get("value"), "anchor_index": anchor_value,
                "source_period": point.get("date"), "source_raw_file": envelope["raw_file"],
                "source_url": "https://trends.google.com/trends/explore?"+urlencode({"date":batch["date"],"geo":"US","q":",".join(batch["terms"])}),
                "normalization_scope": "single_term" if batch.get("single_term") else "comparison_batch",
                "collected_at_utc": envelope["fetched_at_utc"], "market": "US",
                "scale_note": "0-100 within this fixed-window series/batch, not absolute searches"})
    return series


def weighted_mean(series, lower, upper, field="interest_index"):
    weighted, days, positive_points = 0, 0, 0
    for point in series:
        value = point.get(field)
        if not isinstance(value, (int, float)):
            continue
        start, end = date.fromisoformat(point["period_start"]), date.fromisoformat(point["period_end_exclusive"])
        overlap = overlap_days(start, end, lower, upper)
        if overlap:
            weighted += value * overlap
            days += overlap
            positive_points += int(value > 0)
    return (round(weighted / days, 4) if days else None), days, positive_points


def monthly_period(series, keywords, years, cutoff, months):
    output = []
    for keyword in keywords:
        points = [p for p in series if p["keyword_id"] == keyword["keyword_id"]]
        for year in years:
            for month in sorted(set(months)):
                lower = date(year, month, 1)
                month_days = calendar.monthrange(year, month)[1]
                upper = lower + timedelta(days=month_days)
                observed_end = min(upper, cutoff + timedelta(days=1))
                value, days, positives = weighted_mean(points, lower, observed_end) if lower <= cutoff else (None, 0, 0)
                anchor, _, _ = weighted_mean(points, lower, observed_end, "anchor_index") if lower <= cutoff else (None, 0, 0)
                if lower > cutoff:
                    status = "not_yet_observed"
                elif not days:
                    status = "source_unavailable"
                elif not positives:
                    status = "below_search_reporting_threshold"
                else:
                    status = "complete_month" if days == month_days else "partial_month"
                output.append({"keyword_id": keyword["keyword_id"], "keyword": keyword["keyword"],
                    "component_id": keyword["id"], "demand_scope": keyword["demand_scope"], "year": year, "month": month,
                    "mean_interest_index": value, "anchor_mean_index": anchor,
                    "ratio_to_anchor": round(value / anchor, 4) if value is not None and anchor and value > 0 else None,
                    "observed_days": days, "calendar_days": month_days, "positive_source_points": positives,
                    "observation_status": status, "as_of_date": cutoff.isoformat(), "market": "US",
                    "batch_id": points[0]["batch_id"] if points else None,
                    "aggregation_method": "Weekly Google index weighted by days overlapping the month; approximate monthly average",
                    "source_raw_file": points[0]["source_raw_file"] if points else None})
                output[-1].update(source_url=points[0].get("source_url") if points else None,
                    normalization_scope=points[0].get("normalization_scope") if points else None)
    return output


def period_keyword_summary(keywords, monthly, cutoff, months, series):
    """Summarize arbitrary calendar months; compare identical observed windows YoY."""
    output = []
    for keyword in keywords:
        rows = [r for r in monthly if r["keyword_id"] == keyword["keyword_id"]]
        points = [p for p in series if p["keyword_id"] == keyword["keyword_id"]]
        row = {k: keyword[k] for k in ("keyword_id", "keyword", "demand_scope", "keyword_origin", "tavily_source_count")}
        row.update(component_id=keyword["id"], component_name=keyword["name"])
        for year in sorted({r["year"] for r in rows}):
            group = [r for r in rows if r["year"] == year]
            days = sum(r["observed_days"] for r in group)
            mean_value = sum((r["mean_interest_index"] or 0) * r["observed_days"] for r in group) / days if days else None
            complete = all(r["observed_days"] == r["calendar_days"] for r in group)
            row[f"period_{year}_mean_index"] = round(mean_value, 4) if mean_value is not None else None
            row[f"period_{year}_status"] = "complete_period" if complete else "partial_period" if days else "not_observed"
        comparison = []
        for year in (cutoff.year, cutoff.year - 1):
            value_sum, days_sum, positive = 0, 0, set()
            compare_months=months if {cutoff.year,cutoff.year-1}.issubset({r["year"] for r in rows}) else []
            for month in compare_months:
                if month > cutoff.month:
                    continue
                end_day = min(cutoff.day, calendar.monthrange(year, month)[1]) if month == cutoff.month else calendar.monthrange(year, month)[1]
                lower, upper = date(year, month, 1), date(year, month, end_day) + timedelta(days=1)
                value, days, _ = weighted_mean(points, lower, upper)
                if value is not None:
                    value_sum += value * days
                    days_sum += days
                positive.update(p["period_start"] for p in points if (p.get("interest_index") or 0) > 0
                                and p["period_start"] < upper.isoformat() and p["period_end_exclusive"] > lower.isoformat())
            comparison.append((value_sum / days_sum if days_sum else None, days_sum, len(positive)))
        current, previous = comparison
        reliable = current[1] == previous[1] and current[2] >= 2 and previous[2] >= 2 and previous[0]
        row.update(same_period_current_mean_index=round(current[0], 4) if current[0] is not None else None,
                   same_period_previous_mean_index=round(previous[0], 4) if previous[0] is not None else None,
                   same_period_yoy_change_pct=round((current[0] / previous[0] - 1) * 100, 2) if reliable and current[0] is not None else None,
                   change_status="comparable_same_period" if reliable else "insufficient_signal_for_change",
                   as_of_date=cutoff.isoformat(), market="US",
                   comparison_note="Selected calendar months, equal observed days YoY; own keyword history only, not absolute volume")
        output.append(row)
    return output
