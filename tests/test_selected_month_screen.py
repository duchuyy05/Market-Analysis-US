"""Specific design screening uses observed selected months, not forecast cycles."""
from datetime import date, datetime, timedelta, timezone
import pytest

from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import screen, monthly_keywords
from market_research.workflow.planning import analysis_windows, trends_plan


def config(**changes):
    return validate_config({"brief": "Find singer prints for t shirts in November", "as_of_date": "2026-11-02",
        "history_years": [2023, 2024, 2025], "selling_months": [11], "target_year": 2027,
        "business": {"profile": "general", "categories": []}, "llm": {"enabled": False},
        "sources": {"web": False},
        "niches": [{"name": "Singer prints", "seeds": ["singer alpha t shirt", "singer beta t shirt"]}],
        "trends": {"provider": "serpapi", "history_scope": "seasonal", "history_months": [11]},
        "limits": {"candidate_keywords": 2, "monthly_keywords": 2, "serpapi_requests": 20,
                   "trends_serpapi_requests": 10, "serpapi_product_reserve": 4, "retry_attempts": 0}, **changes})


def discovery(cfg):
    niche = cfg["niches"][0]
    niche.setdefault("id", "N-design")
    return {"keywords": [{"id": "K" + str(i), "text": text, "niche_id": niche["id"], "evidence_ids": []}
                         for i, text in enumerate(niche["seeds"])]}


def source(calls):
    def send(provider, params):
        assert provider == "serpapi" and params["engine"] == "google_trends"
        calls.append(params)
        start, end = map(date.fromisoformat, params["date"].split())
        assert start.month == end.month == 11
        points = []
        while start <= end:
            points.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())),
                "values": [{"query": query, "extracted_value": 20 if query == "gift basket" else
                            (60 if "alpha" in query else 10) if start.year == 2026 else
                            (10 if "alpha" in query else 50)}
                           for query in params["q"].split(",")]})
            start += timedelta(days=1)
        return {"interest_over_time": {"timeline_data": points}}
    return send


def test_new_singer_print_is_ranked_from_current_observed_month_without_two_historical_cycles(tmp_path):
    cfg, calls = config(), []
    run = Run("november-designs", tmp_path)
    run.manifest["current_stage"] = "screen"
    client = Client(run, cfg, source(calls))
    result = screen.analyze(run, client, cfg, discovery(cfg))
    assert len(calls) == 1 and calls[0]["date"] == "2026-11-01 2026-11-02"
    assert set(calls[0]["q"].split(",")) == {"gift basket", "singer alpha t shirt", "singer beta t shirt"}
    assert result["status"] == "available" and result["screening_scope"] == "selected_months"
    assert result["selection_basis"] == "selected_month_observations" and result["analysis_year"] == 2026
    first, second = result["rows"]
    assert first["rank"] == 1 and second["rank"] == 2
    assert first["relative_interest"] == 3 and first["partial_period"]
    assert first["qualifying_months"] == [11] and first["peak_month"] == 11
    assert first["monthly_metrics"][0]["required_positive_points"] == 2
    assert all(row["observed_days"] == 2 and row["evidence_ids"] for row in result["rows"])
    assert all(row["year"] == 2026 and row["month"] == 11 for row in first["analysis_observations"])
    assert not run.stage_data("history-" + first["keyword_id"])


def test_explicit_historical_analysis_window_reuses_observations_in_monthly_history(tmp_path):
    cfg = config(trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025})
    calls, run = [], Run("history-share", tmp_path)
    run.manifest["current_stage"] = "screen"
    client = Client(run, cfg, source(calls))
    result = screen.analyze(run, client, cfg, discovery(cfg))
    assert len(calls) == 1 and calls[0]["date"] == "2025-11-01 2025-11-30"
    run.manifest["current_stage"] = "monthly"
    monthly = monthly_keywords.analyze(run, client, cfg, discovery(cfg), result)
    assert len(calls) == 3  # November2025 is reused; only2023/2024 are fetched.
    assert monthly["observed_keywords"] == 2
    assert result["rows"][0]["analysis_year"] == 2025


def test_auto_period_uses_latest_calendar_year_even_when_training_years_are_old():
    cfg = config(as_of_date="2026-10-31", history_years=[2021, 2022])
    assert analysis_windows(cfg) == [{"year": 2025, "months": [11], "start": "2025-11-01", "end": "2025-11-30"}]


def test_explicit_future_month_does_not_fall_back_or_make_a_source_request(tmp_path):
    cfg = config(as_of_date="2026-10-31", trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2026})
    calls, run = [], Run("future-month", tmp_path)
    result = screen.analyze(run, Client(run, cfg, source(calls)), cfg, discovery(cfg))
    assert calls == [] and result["status"] == "unavailable"
    assert result["analysis_year"] == 2026 and result["analysis_windows"] == []
    assert all(row["rank"] is None and row["relative_interest"] is None for row in result["rows"])


def test_current_analysis_budget_is_separate_from_forecast_and_overlap_is_counted_once():
    current = trends_plan(config())
    assert current["screening_estimate"] == 1 and current["history_estimate"] == 3
    assert current["paid_estimate"] == 4 and current["shared_history_estimate"] == 0
    historical = trends_plan(config(trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025}))
    assert historical["screening_estimate"] == 1 and historical["paid_estimate"] == 3
    assert historical["shared_history_estimate"] == 1


def test_current_design_winner_reaches_product_search_even_when_historical_winner_differs(tmp_path):
    cfg = config(limits={"candidate_keywords": 2, "monthly_keywords": 2, "top_keywords": 1, "product_details": 0,
                         "serpapi_requests": 20, "trends_serpapi_requests": 10, "serpapi_product_reserve": 4,
                         "retry_attempts": 0})
    calls, searches = [], []
    timeline = source(calls)
    def send(provider, params):
        if params["engine"] == "google_trends":
            return timeline(provider, params)
        assert params["engine"] == "amazon"
        searches.append(params["k"])
        return {"organic_results": [{"asin": "B000000001", "title": params["k"], "extracted_price": 15}]}
    run = execute(cfg, run_id="current-design-winner", root=tmp_path, transport=send, event=lambda _: None)
    data = run.load_dataset()
    assert searches == ["singer alpha t shirt"]
    assert data["selection"]["selection_basis"] == "selected_month_observations"
    assert data["screening"]["analysis_year"] == 2026
    assert calls[0]["date"] == "2026-11-01 2026-11-02"
    historical = {row["measurement_query"]: row for row in data["keyword_monthly"]["rows"] if row["month"] == 11}
    assert historical["singer beta t shirt"]["demand_metric"] > historical["singer alpha t shirt"]["demand_metric"]


def test_december_model_qualifies_despite_zero_october_november_and_noise_is_not_ranked(tmp_path):
    cfg = config(as_of_date="2026-10-31", selling_months=[10, 11, 12],
        niches=[{"name": "Singer prints", "seeds": ["singer alpha t shirt", "singer beta t shirt", "singer gamma t shirt", "singer delta t shirt"]}],
        trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [10, 11, 12], "analysis_year": 2025},
        limits={"candidate_keywords": 4, "monthly_keywords": 2, "serpapi_requests": 20,
                "trends_serpapi_requests": 10, "serpapi_product_reserve": 4, "retry_attempts": 0})
    calls = []
    def send(provider, params):
        assert provider == "serpapi" and params["date"] == "2025-10-01 2025-12-31"
        calls.append(params)
        start, end = map(date.fromisoformat, params["date"].split())
        points = []
        while start <= end:
            values = []
            for query in params["q"].split(","):
                value = (20 if query == "gift basket" else
                         60 if "alpha" in query and start.month == 12 and start.day <= 3 else
                         20 if "beta" in query and start.month == 10 and start.day <= 3 else
                         100 if "gamma" in query and start.month == 12 and start.day == 1 else
                         100 if "delta" in query and start.month == 11 and start.day <= 2 else 0)
                values.append({"query": query, "extracted_value": value})
            points.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())), "values": values})
            start += timedelta(days=1)
        return {"interest_over_time": {"timeline_data": points}}
    run = Run("q4-month-specific", tmp_path)
    client = Client(run, cfg, send)
    result = screen.analyze(run, client, cfg, discovery(cfg))
    alpha, beta, gamma, delta = result["rows"]
    assert len(calls) == 1 and result["measured_keywords"] == 2
    assert alpha["status"] == "available" and alpha["qualifying_months"] == [12] and alpha["peak_month"] == 12
    assert [item["status"] for item in alpha["monthly_metrics"]] == ["low_signal", "low_signal", "available"]
    assert [item["raw_value"] for item in alpha["analysis_observations"]][:2] == [0, 0]
    assert alpha["monthly_metrics"][2]["rank"] == 1
    assert beta["qualifying_months"] == [10] and beta["monthly_metrics"][0]["rank"] == 1
    assert alpha["rank"] == 1 and beta["rank"] == 2  # aggregate explicitly uses strongest qualifying month
    assert result["aggregation"] == "peak_qualifying_month_v1"
    assert all(row["status"] == "low_signal" and row["rank"] is None and row["qualifying_months"] == [] for row in [gamma, delta])
    again = screen.analyze(run, client, cfg, discovery(cfg))
    assert len(calls) == 1 and again["rows"][0]["monthly_metrics"] == alpha["monthly_metrics"]


@pytest.mark.parametrize(("native", "points", "expected", "required"), [
    (1, 1, "low_signal", 3), (1, 2, "low_signal", 3), (1, 3, "available", 3),
    (7, 1, "low_signal", 2), (7, 2, "available", 2), (31, 1, "available", 1),
])
def test_full_month_uses_native_resolution_and_rejects_isolated_daily_spikes(native, points, expected, required):
    sample = {"value": 100, "observed_days": 31, "status": "complete", "positive_points": points, "native_step_days": native}
    metric = screen._selected_month_metric(sample, 12, 2025, date(2026, 11, 2))
    assert metric["status"] == expected and metric["required_positive_points"] == required


def test_resume_replaces_a_broad_proxy_checkpoint_without_resetting_usage(tmp_path):
    cfg = config(trends={"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
                 limits={"candidate_keywords": 2, "monthly_keywords": 2, "top_keywords": 1, "product_details": 0,
                         "serpapi_requests": 20, "trends_serpapi_requests": 10, "serpapi_product_reserve": 4, "retry_attempts": 0})
    calls = []
    timeline = source(calls)
    def send(provider, params):
        if params["engine"] == "google_trends":
            return timeline(provider, params)
        return {"organic_results": [{"asin": "B000000001", "title": params["k"], "extracted_price": 15}]}
    run = execute(cfg, run_id="legacy-design-proxy", root=tmp_path, transport=send, event=lambda _: None)
    usage = list(run.manifest["usage"])
    input_hash = run.manifest["input_hash"]
    old = run.stage_data("screen")
    for row in old["rows"]:
        row.update(measurement_query="t shirt", measurement_scope="broader_product_type")
    run.checkpoint("screen", old)
    run.manifest["stages"]["screen"]["status"] = "complete"
    run.save()
    resumed = execute(run_id=run.id, root=tmp_path, transport=send, event=lambda _: None)
    assert resumed.manifest["input_hash"] == input_hash
    assert resumed.manifest["usage"][:len(usage)] == usage
    assert all(row["measurement_query"] == row["keyword"] for row in resumed.stage_data("screen")["rows"])
    assert "legacy_proxy_screen_replaced" in (run.path / "events.jsonl").read_text(encoding="utf-8")
