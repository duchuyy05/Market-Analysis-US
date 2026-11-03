"""Conservative request estimates; every reserve remains inside existing caps."""
from math import ceil
import calendar
from datetime import date

HISTORY_BATCH_SIZE = 5
ANCHORED_HISTORY_BATCH_SIZE = 4


def seasonal_windows(config):
    """Exact contiguous month windows for each selected completed history year."""
    months = sorted(set(config.get("trends", {}).get("history_months", [10, 11, 12])))
    if not months or any(type(month) is not int or not 1 <= month <= 12 for month in months):
        raise ValueError("Tháng thu thập lịch sử phải thuộc 1–12")
    groups = []
    for month in months:
        if groups and month == groups[-1][-1] + 1:
            groups[-1].append(month)
        else:
            groups.append([month])
    cutoff = date.fromisoformat(config["as_of_date"])
    windows = []
    for year in sorted(set(config["history_years"])):
        for group in groups:
            start = date(year, group[0], 1)
            end = min(date(year, group[-1], calendar.monthrange(year, group[-1])[1]), cutoff)
            if start <= end:
                windows.append({"year": year, "months": group, "start": start.isoformat(), "end": end.isoformat()})
    return windows


def analysis_windows(config):
    """Observed month windows for design screening, separate from training years.

    Automatic selection uses the most recent calendar year in which all
    selected months have begun. An explicit year is never silently replaced.
    Requests are clipped at the cutoff, so a current month is labelled partial
    and a future month remains absent.
    """
    cutoff = date.fromisoformat(config["as_of_date"])
    months = sorted(set(config.get("trends", {}).get("history_months", [10, 11, 12])))
    year = config.get("trends", {}).get("analysis_year")
    if year is None:
        year = cutoff.year if all(date(cutoff.year, month, 1) <= cutoff for month in months) else cutoff.year - 1
    if year is None:
        return []
    return seasonal_windows({**config, "history_years": [year]})


def trends_plan(config):
    limits = config["limits"]
    broad = config.get("discovery", {}).get("enabled", False)
    seasonal = config.get("trends", {}).get("history_scope", "full") == "seasonal"
    guarded = (broad or seasonal) and "trends_serpapi_requests" in limits
    total = limits["serpapi_requests"]
    product_reserve = limits.get("serpapi_product_reserve", 0) if guarded else 0
    cap = min(limits["trends_serpapi_requests"], max(0, total - product_reserve)) if guarded else total
    monthly = (broad or seasonal) and (config.get("trends", {}).get("monthly_rankings", False) or seasonal)
    batch_size = ANCHORED_HISTORY_BATCH_SIZE if monthly or seasonal else HISTORY_BATCH_SIZE
    history_count = min(limits.get("candidate_keywords", 64), limits.get("monthly_keywords", 64)) if monthly else limits.get("top_keywords", 10)
    window_count = len(seasonal_windows(config)) if seasonal else 1
    history = ceil(history_count / batch_size) * window_count if broad or seasonal else 0
    # Retain at least one screening request when the paid cap is very small.
    paid_history = config.get("mode") == "live" and config.get("sources", {}).get("trends", True) and config.get("trends", {}).get("provider", "serpapi") in {"auto", "serpapi"}
    # A broad monthly study must retain useful screening too when its configured
    # budget is below the estimate. Never silently raise either paid cap.
    history_reserve = min(history, cap) if seasonal and paid_history else min(history, max(1, cap // 2) if monthly else max(0, cap - 1), max(0, cap - 1)) if guarded and paid_history else 0
    observed_windows = analysis_windows(config) if seasonal else []
    screening = ceil(limits.get("candidate_keywords", 32) / ANCHORED_HISTORY_BATCH_SIZE) * len(observed_windows) if seasonal else ceil(limits.get("candidate_keywords", 32) / 4)
    historical_windows = seasonal_windows(config) if seasonal else []
    shared_windows = sum(window in historical_windows for window in observed_windows)
    reused = ceil(history_count / batch_size) * shared_windows if seasonal else 0
    return {"trends_cap": cap, "product_reserve": product_reserve,
            "history_batch_size": batch_size, "history_keywords": history_count, "history_estimate": history,
            "history_scope": "seasonal" if seasonal else "full", "history_windows": window_count,
            "history_reserve": history_reserve, "screening_estimate": screening,
            "screening_reuses_history": seasonal and bool(shared_windows), "recent_screening_estimate": 0 if seasonal else screening,
            "analysis_windows": observed_windows, "shared_history_estimate": reused,
            "paid_estimate": screening + history - reused, "screening_cap": cap if seasonal else cap - history_reserve}
