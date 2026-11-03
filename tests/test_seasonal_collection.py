"""Exact requested windows, anchored cross-year scale and bounded API usage."""
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from market_research.config import validate_config
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import history
from market_research.workflow.planning import seasonal_windows, trends_plan


def config(**changes):
    return validate_config({"brief": "Christmas printed gifts", "as_of_date": "2026-10-30",
        "history_years": [2023, 2024, 2025], "selling_months": [11, 12],
        "trends": {"provider": "serpapi", "history_scope": "seasonal", "history_months": [10, 11, 12]},
        "limits": {"candidate_keywords": 64, "monthly_keywords": 64, "serpapi_requests": 80,
                   "trends_serpapi_requests": 60, "serpapi_product_reserve": 12, "retry_attempts": 0}, **changes})


def directions(count=4):
    return [{"id": f"D{i}", "keyword_id": f"K{i}", "keyword": f"printed gift {i}"} for i in range(count)]


def timeline(params, *, zero_anchor=False):
    start, end = [date.fromisoformat(item) for item in params["date"].split()]
    queries = params["q"].split(",")
    factor = (start.year - 2022)  # each independent source window has a new scale
    points = []
    while start <= end:
        values = [{"query": query, "extracted_value": (0 if zero_anchor else 20 * factor) if query == "gift basket" else (5 + i * 2) * factor}
                  for i, query in enumerate(queries)]
        points.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())), "values": values})
        start += timedelta(days=1)
    return {"interest_over_time": {"timeline_data": points}}


def test_only_q4_of_history_years_is_requested_and_analysis_uses_anchor_ratio(tmp_path):
    cfg, calls = config(), []
    run = Run("q4-only", tmp_path)
    def send(provider, params):
        assert provider == "serpapi"
        calls.append(params)
        return timeline(params)
    result = history.analyze(run, Client(run, cfg, send), cfg, directions(8))
    assert len(calls) == 6  # two batches × three Q4 windows, not one call/month
    assert {item["date"] for item in calls} == {f"{year}-10-01 {year}-12-31" for year in [2023, 2024, 2025]}
    assert all(len(item["q"].split(",")) == 5 for item in calls)
    assert all(item["q"].split(",")[0] == "gift basket" for item in calls)
    assert all({row["month"] for row in item["monthly"]} == {10, 11, 12} for item in result)
    assert all(len(item["monthly"]) == 9 and len(item["forecast"]) == 3 for item in result)
    q = result[0]
    assert q["monthly"][0]["raw_value"] != q["monthly"][3]["raw_value"]
    assert q["monthly"][0]["value"] == q["monthly"][3]["value"]
    assert q["monthly"][0]["value"] == 35  # query7 / anchor20 ×100
    assert q["normalization_context"]["scale"] == "anchor_ratio_100"
    assert q["usable_years"] == [2023, 2024, 2025]
    assert q["validation"]["metrics"]["mae"] == 0


def test_matching_scope_reuses_global_and_per_query_window_checkpoints(tmp_path):
    cfg, calls = config(), []
    run = Run("season-cache", tmp_path)
    def send(_, params):
        calls.append(params)
        return timeline(params)
    client = Client(run, cfg, send)
    first = history.analyze(run, client, cfg, directions())
    assert len(calls) == 3
    again = history.analyze(run, client, cfg, directions())
    assert len(calls) == 3 and again[0]["monthly"] == first[0]["monthly"]
    shared = [{**directions()[0], "id": "D-shared", "keyword_id": "K-shared"}]
    reused = history.analyze(run, client, cfg, shared)
    assert len(calls) == 3 and reused[0]["monthly"] == first[0]["monthly"]


def test_full_scope_checkpoint_cannot_replace_season_only_collection(tmp_path):
    cfg, calls = config(), []
    run = Run("scope-guard", tmp_path)
    run.checkpoint("history-D0", {"status": "available", "monthly": [], "normalization_context": {"scale": "shared_0_100"}})
    def send(_, params):
        calls.append(params)
        return timeline(params)
    client = Client(run, cfg, send)
    result = history.analyze(run, client, cfg, directions(1))
    assert len(calls) == 3 and result[0]["history_scope"] == "seasonal"
    full = {**cfg, "trends": {**cfg["trends"], "history_scope": "full", "monthly_rankings": False}}
    history.analyze(run, Client(run, full, send), full, directions(1))
    assert calls[-1]["date"] == "2023-01-01 2026-10-30"


def test_failed_year_remains_missing_and_resume_fetches_only_failed_window(tmp_path):
    cfg, calls, fail = config(), [], [True]
    run = Run("partial-year", tmp_path)
    run.manifest["current_stage"] = "monthly"
    def send(_, params):
        calls.append(params)
        if params["date"].startswith("2024") and fail[0]:
            raise HTTPError("https://serpapi.com", 500, "temporary", {}, None)
        return timeline(params)
    client = Client(run, cfg, send)
    result = history.analyze(run, client, cfg, directions(1))
    assert result[0]["collection_complete"] is False
    assert all(row["value"] is None for row in result[0]["monthly"] if row["year"] == 2024)
    assert result[0]["growth_pct"] is None  # missing2024 cannot masquerade as a YoY base
    fail[0] = False
    resumed = history.analyze(run, client, cfg, directions(1))
    assert len(calls) == 4 and resumed[0]["collection_complete"] is True
    assert resumed[0]["usable_years"] == [2023, 2024, 2025]


def test_zero_anchor_does_not_create_zero_demand_or_a_forecast(tmp_path):
    cfg = config()
    run = Run("zero-anchor", tmp_path)
    result = history.analyze(run, Client(run, cfg, lambda _, params: timeline(params, zero_anchor=True)), cfg, directions(1))
    assert all(row["value"] is None for row in result[0]["monthly"])
    assert result[0]["usable_years"] == []
    assert all(row["prediction"] is None for row in result[0]["forecast"])


def test_noncontiguous_selected_months_generate_separate_exact_windows():
    cfg = config(selling_months=[1, 3], trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [1, 3, 10]})
    windows = seasonal_windows(cfg)
    assert len(windows) == 9
    assert windows[0] == {"year": 2023, "months": [1], "start": "2023-01-01", "end": "2023-01-31"}
    assert windows[1]["start"] == "2023-03-01" and windows[1]["end"] == "2023-03-31"
    assert trends_plan(cfg)["history_estimate"] == 16 * 9


def test_q4_request_plan_is_honest_and_preserves_paid_caps():
    cfg = config(limits={"candidate_keywords": 64, "monthly_keywords": 64, "serpapi_requests": 80,
                         "trends_serpapi_requests": 32, "serpapi_product_reserve": 12})
    plan = trends_plan(cfg)
    assert plan["history_estimate"] == 48
    assert plan["history_windows"] == 3 and plan["screening_estimate"] == 16
    assert plan["screening_reuses_history"] and plan["shared_history_estimate"] == 16
    assert plan["paid_estimate"] == 48 and plan["history_reserve"] == 32
    assert plan["trends_cap"] == 32
    full = {**cfg, "trends": {**cfg["trends"], "history_scope": "full"}}
    assert trends_plan(full)["paid_estimate"] == 32
