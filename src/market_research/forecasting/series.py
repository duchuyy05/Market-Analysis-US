"""Calendar overlap aggregation; zero, missing and incomplete stay distinct."""
import calendar
from datetime import date, datetime, timedelta, timezone

from ..common import number
from statistics import median


def parse_timeline(envelope, query):
    timeline = (envelope["response"].get("interest_over_time") or {}).get("timeline_data", [])
    rows = []
    for index, point in enumerate(timeline):
        start = datetime.fromtimestamp(int(point["timestamp"]), timezone.utc).date()
        if index + 1 < len(timeline):
            end = datetime.fromtimestamp(int(timeline[index + 1]["timestamp"]), timezone.utc).date()
        else:
            differences = [(int(timeline[i]["timestamp"])-int(timeline[i-1]["timestamp"]))/86400 for i in range(1, len(timeline))]
            step = median(differences) if differences else 7
            end = date(start.year + (start.month == 12), start.month % 12 + 1, 1) if 27 <= step <= 32 and start.day == 1 else start + timedelta(days=max(1, round(step)))
        if end <= start:
            continue
        item = next((v for v in point.get("values", []) if v.get("query") == query), None)
        if item is None:
            continue
        rows.append({"start": start.isoformat(), "end": end.isoformat(), "value": number(item.get("extracted_value")),
            "partial": bool(point.get("isPartial") or point.get("is_partial") or item.get("isPartial")), "raw_label": point.get("date")})
    return rows


def monthly(series, years, cutoff):
    cutoff = date.fromisoformat(cutoff)
    steps = [(date.fromisoformat(p["end"])-date.fromisoformat(p["start"])).days for p in series if not p.get("partial")]
    native_step = median(steps) if steps else None
    result = []
    for year in years:
        for month in range(1, 13):
            start = date(year, month, 1)
            days = calendar.monthrange(year, month)[1]
            end = start + timedelta(days=days)
            observed_end = min(end, cutoff + timedelta(days=1))
            total, covered, positives = 0.0, set(), 0
            for point in series:
                if point["value"] is None or point.get("partial"):
                    continue
                lower, upper = max(start, date.fromisoformat(point["start"])), min(observed_end, date.fromisoformat(point["end"]))
                fresh = {lower + timedelta(days=i) for i in range(max(0, (upper-lower).days))} - covered
                if fresh:
                    covered.update(fresh)
                    total += point["value"] * len(fresh)
                    positives += point["value"] > 0
            value = round(total/len(covered), 4) if covered else None
            status = "future" if start > cutoff else "unavailable" if not covered else "complete" if len(covered) == days else "partial"
            result.append({"year": year, "month": month, "value": value, "observed_days": len(covered), "calendar_days": days, "positive_points": positives, "native_step_days": native_step, "status": status})
    return result
