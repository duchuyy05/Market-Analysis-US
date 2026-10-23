"""Validated, reusable study configuration. No API secrets belong in a study."""
import calendar
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import re


def local_today():
    return datetime.now(timezone(timedelta(hours=7))).date()


def study_months(data):
    return sorted(set(data.get("history_months") or data.get("months") or [10, 11, 12]))


def month_end(year, month):
    return date(year, month, calendar.monthrange(year, month)[1])


def period_label(months):
    months = sorted(set(months))
    for quarter in range(1, 5):
        if months == list(range(quarter * 3 - 2, quarter * 3 + 1)):
            return f"Q{quarter} (tháng {months[0]}–{months[-1]})"
    return "tháng " + ", ".join(map(str, months))


def profile_value(row):
    return row.get("historical_profile_pct_of_own_period_peak", row.get("historical_profile_pct_of_own_q4_peak"))


def validate_config(value):
    c = deepcopy(value)
    if not isinstance(c, dict):
        raise ValueError("Cấu hình phải là một JSON object")
    c["category"] = str(c.get("category", "")).strip()[:180]
    if not c["category"]:
        raise ValueError("Cần nhập danh mục/chủ đề nghiên cứu")
    months = c.get("months", [10, 11, 12])
    years = c.get("years", list(range(local_today().year - 3, local_today().year + 1)))
    if not isinstance(months, list) or not months or any(type(m) is not int or not 1 <= m <= 12 for m in months):
        raise ValueError("Tháng phải là danh sách số nguyên từ 1 đến 12")
    if not isinstance(years, list) or not years or len(years) > 8 or any(type(y) is not int or not 2004 <= y <= local_today().year for y in years):
        raise ValueError("Chọn tối đa 8 năm, từ 2004 đến năm hiện tại")
    c["months"], c["years"] = sorted(set(months)), sorted(set(years))
    cutoff = date.fromisoformat(c.get("as_of_date") or local_today().isoformat())
    if cutoff > local_today() or cutoff < date(min(years), 1, 1):
        raise ValueError("Mốc quan sát phải nằm từ năm bắt đầu đến ngày hiện tại")
    c["as_of_date"] = cutoff.isoformat()
    # This application deliberately retains the existing US, English source contract.
    if c.get("market", "US") != "US" or c.get("marketplace", "amazon.com") != "amazon.com":
        raise ValueError("Bản này hỗ trợ thị trường US / amazon.com")
    c.update(market="US", marketplace="amazon.com", language="en_US")
    limits = {"products_per_family": (2, 1, 5), "max_mobile_review_requests": (4, 0, 8),
              "min_completed_years_for_timing": (2, 2, 8), "ramp_up_profile_threshold_pct": (40, 1, 100),
              "max_serpapi_requests": (56, 1, 100), "max_tavily_requests": (4, 1, 4),
              "top_n": (5, 1, 20)}
    for key, (default, low, high) in limits.items():
        v = c.get(key, default)
        if type(v) is not int or not low <= v <= high:
            raise ValueError(f"{key}: nhập số nguyên {low}–{high}")
        c[key] = v
    c["min_positive_week_points_per_period"] = c.get("min_positive_week_points_per_period", c.get("min_positive_week_points_per_q4", 3))
    if type(c["min_positive_week_points_per_period"]) is not int or not 2 <= c["min_positive_week_points_per_period"] <= 52:
        raise ValueError("Số điểm nguồn dương tối thiểu phải từ 2 đến 52")
    for name, maximum in (("niches", 4), ("families", 12)):
        rows = c.get(name)
        if not isinstance(rows, list) or not 1 <= len(rows) <= maximum or any(not isinstance(r, dict) for r in rows):
            raise ValueError(f"Cần 1–{maximum} {name}")
        ids = []
        for row in rows:
            identifier = row.get("id", "")
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", identifier):
                raise ValueError(f"ID {name} chỉ dùng chữ thường, số, gạch dưới")
            ids.append(identifier)
            for key in ("name", "name_vi"):
                row[key] = str(row.get(key) or row.get("name") or identifier).strip()[:180]
        if len(set(ids)) != len(ids):
            raise ValueError(f"ID {name} không được trùng")
    niche_ids = {r["id"] for r in c["niches"]}
    for niche in c["niches"]:
        query = niche.get("discovery_query")
        if not isinstance(query, str) or not 3 <= len(query.strip()) <= 500:
            raise ValueError("Cần truy vấn Tavily tiếng Anh cho mỗi niche")
    for family in c["families"]:
        if family.get("niche_id") not in niche_ids:
            raise ValueError("niche_id của nhóm phải tồn tại trong niches")
        for key in ("keyword", "amazon_query"):
            text = family.get(key)
            if not isinstance(text, str) or not 2 <= len(text.strip()) <= 250:
                raise ValueError(f"Cần {key} tiếng Anh, dài 2–250 ký tự")
            if re.search(r"[đĐăĂơƠưƯấầẩẫậắằẳẵặếềểễệốồổỗộớờởỡợứừửữự]", text):
                raise ValueError("Keyword và truy vấn Amazon phải dùng tiếng Anh")
        patterns = family.get("required_patterns", [])
        # Literal alternatives only: model/user regex must not cause catastrophic backtracking.
        if not patterns or len(patterns) > 8 or any(not isinstance(p, str) or len(p) > 250 for p in patterns):
            raise ValueError("Cần 1–8 bộ lọc hợp lệ cho mỗi nhóm")
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError("Biểu thức lọc không hợp lệ") from error
            safe_pattern = pattern.replace("(?:es)?", "es?")
            if re.search(r"[+*{}\\]|\([^)]*[?+*][^)]*\)[?+*]", safe_pattern):
                raise ValueError("Bộ lọc chỉ nên dùng từ/cụm từ, dấu | và số nhiều ?")
        family["idea_vi"] = str(family.get("idea_vi") or "Đối chiếu quy cách, giá, đóng gói và review trước khi thử sản phẩm.")[:800]
    # Reject accidental credential fields rather than serializing them into public outputs.
    for key in list(c):
        if "key" in key.lower() or "token" in key.lower() or "secret" in key.lower():
            raise ValueError("Không đặt API key/token trong cấu hình nghiên cứu")
    c["schema_version"] = 4
    return c
