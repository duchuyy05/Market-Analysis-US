"""User-selected monthly comparison windows on one consistent historical scale."""
import calendar
import re


MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def month_index(value):
    if not isinstance(value, str) or not MONTH.fullmatch(value):
        raise ValueError("Khoảng so sánh cần tháng dạng YYYY-MM")
    year, month = map(int, value.split("-"))
    if not 2004 <= year <= 2100:
        raise ValueError("Tháng so sánh phải từ năm 2004")
    return year * 12 + month - 1


def validate_periods(values, cutoff):
    if not isinstance(values, list) or len(values) > 12:
        raise ValueError("comparison_periods cần danh sách tối đa 12 khoảng tháng")
    last = cutoff[:7]
    output, seen = [], set()
    for item in values:
        if not isinstance(item, dict) or set(item) != {"start", "end"}:
            raise ValueError("Mỗi khoảng so sánh cần đúng start và end")
        start, end = item["start"], item["end"]
        lower, upper = month_index(start), month_index(end)
        if lower > upper:
            raise ValueError("Tháng bắt đầu phải trước hoặc bằng tháng kết thúc")
        if end > last:
            raise ValueError("Khoảng so sánh không được sau tháng của ngày chốt")
        if upper - lower >= 120:
            raise ValueError("Mỗi khoảng so sánh tối đa 120 tháng")
        if (start, end) in seen:
            raise ValueError("Không nhập trùng khoảng thời gian so sánh")
        seen.add((start, end))
        output.append({"start": start, "end": end})
    return sorted(output, key=lambda item: (item["start"], item["end"]))


def years_for(periods):
    return sorted({year for item in periods for year in range(int(item["start"][:4]), int(item["end"][:4]) + 1)})


def summarize(monthly, periods, evidence_ids=()):
    by_month = {(row["year"], row["month"]): row for row in monthly}
    output = []
    for period in periods:
        lower, upper = month_index(period["start"]), month_index(period["end"])
        requested_days = covered_days = observed_months = complete_months = 0
        total = 0.0
        for index in range(lower, upper + 1):
            year, offset = divmod(index, 12)
            month = offset + 1
            requested_days += calendar.monthrange(year, month)[1]
            row = by_month.get((year, month), {})
            value = row.get("value")
            days = row.get("observed_days", 0)
            if value is None or days <= 0:
                continue
            observed_months += 1
            complete_months += row.get("status") == "complete"
            covered_days += days
            total += value * days
        status = "complete" if covered_days == requested_days else "partial" if covered_days else "unavailable"
        row = {**period, "label": period["start"] + " → " + period["end"],
               "requested_months": upper - lower + 1, "observed_months": observed_months, "complete_months": complete_months,
               "requested_days": requested_days, "observed_days": covered_days,
               "coverage_pct": round(covered_days / requested_days * 100, 2), "status": status,
               "mean_index": round(total / covered_days, 4) if covered_days else None,
               "evidence_ids": list(evidence_ids), "change_vs_previous_pct": None,
               "note": "Chỉ số quan tâm tương đối trên cùng chuỗi lịch sử; không phải giá, lượt bán hoặc doanh thu trong quá khứ."}
        previous = output[-1] if output else None
        if previous and previous["status"] == status == "complete" and previous["mean_index"] > 0:
            row["change_vs_previous_pct"] = round((row["mean_index"] / previous["mean_index"] - 1) * 100, 2)
        output.append(row)
    return output
