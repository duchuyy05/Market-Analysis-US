"""Budget allocation and truthful completion, using local provider fixtures only."""
from datetime import date, datetime, timedelta, timezone
import json
from urllib.request import urlopen

import pytest

from market_research.config import validate_config
from market_research.providers import trends
from market_research.providers.client import Client, BudgetExceeded
from market_research.storage.run import Run
from market_research.workflow import history, discover
from market_research.workflow.planning import trends_plan
from market_research.workflow.quality import outcome
from test_v2_http import app


def config(**changes):
    return validate_config({"brief": "Christmas gifts for parents and a partner, bought by students",
        "as_of_date": "2026-10-30", "selling_months": [11, 12], "trends": {"provider": "serpapi"},
        "limits": {"candidate_keywords": 32, "serpapi_requests": 30, "retry_attempts": 0}, **changes})


def timeline(params, zero=False):
    start, end = [date.fromisoformat(s) for s in params["date"].split()]
    queries = params["q"].split(",")
    rows = []
    while start <= end:
        rows.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())),
            "values": [{"query": q, "extracted_value": 0 if zero else 10 + i * 10 + start.month}
                       for i, q in enumerate(queries)]})
        start += timedelta(days=7)
    return {"interest_over_time": {"timeline_data": rows}}


def directions(count=10):
    return [{"id": f"D{i}", "keyword_id": f"K{i}", "keyword": f"gift type {i}",
             "measurement_query": f"gift type {i}"} for i in range(count)]


def test_screening_cannot_spend_two_reserved_history_calls(tmp_path):
    cfg = config()
    run = Run("budget-split", tmp_path)
    calls = []
    def send(provider, params):
        calls.append(params)
        return timeline(params) if params.get("engine") == "google_trends" else {}
    client = Client(run, cfg, send)
    assert trends_plan(cfg)["paid_estimate"] == 10
    assert client.trends_budget()["remaining"] == 8
    assert client.trends_budget("trends_screen")["remaining"] == 6
    for i in range(6):
        trends.compare(client, [f"screen {i}"], cfg, "2026-08-01 2026-10-30")
    with pytest.raises(BudgetExceeded, match="2 lượt cho lịch sử"):
        trends.compare(client, ["seventh screening"], cfg, "2026-08-01 2026-10-30")
    assert len(calls) == 6
    result = history.analyze(run, client, cfg, directions())
    assert len(calls) == 8
    assert all(h["status"] == "available" for h in result), [h.get("reason") for h in result]
    assert all(any(r["prediction"] is not None for r in h["forecast"]) for h in result)
    assert client.trends_budget()["remaining"] == 0
    # Paid history still respects both caps and leaves room for product sources.
    client.request("serpapi", {"engine": "amazon", "k": "gift"}, purpose="product_search")
    assert len(calls) == 9


def test_history_batches_deduplicate_and_reuse_individual_checkpoints(tmp_path):
    cfg = config()
    run = Run("batch-history", tmp_path)
    calls = []
    def send(provider, params):
        calls.append(params)
        return timeline(params)
    client = Client(run, cfg, send)
    items = directions() + [{**directions()[0], "id": "D-shared"}]
    result = history.analyze(run, client, cfg, items)
    assert len(result) == 11 and len(calls) == 2
    assert all(len(c["q"].split(",")) == 5 for c in calls)
    assert all(h["status"] == "available" for h in result), [h.get("reason") for h in result]
    assert result[0]["monthly"][0]["value"] != result[1]["monthly"][0]["value"]
    assert result[0]["monthly"] == result[-1]["monthly"]
    assert result[0]["normalization_context"]["scale"] == "shared_0_100"
    assert result[5]["normalization_context"]["queries"] != result[0]["normalization_context"]["queries"]
    history.analyze(run, client, cfg, items)
    assert len(calls) == 2  # no HTTP, even across a second history invocation


def test_product_requests_cannot_spend_the_history_reserve_in_total_cap(tmp_path):
    cfg = config(limits={"serpapi_requests": 6, "serpapi_product_reserve": 3, "trends_serpapi_requests": 3, "retry_attempts": 0})
    run = Run("total-reserve", tmp_path)
    calls = []
    def send(provider, params):
        calls.append(params)
        return timeline(params) if params.get("engine") == "google_trends" else {}
    client = Client(run, cfg, send)
    trends.compare(client, ["screen"], cfg, "2026-08-01 2026-10-30")
    for i in range(3):
        client.request("serpapi", {"engine": "amazon", "k": f"gift {i}"}, purpose="amazon_search")
    with pytest.raises(BudgetExceeded, match="Giữ 2 lượt SerpApi"):
        client.request("serpapi", {"engine": "amazon_product", "asin": "B000000001"}, purpose="amazon_detail")
    assert len(calls) == 4
    result = history.analyze(run, client, cfg, directions())
    assert len(calls) == 6 and all(h["status"] == "available" for h in result)


@pytest.mark.parametrize(("provider", "enabled"), [("free", True), ("auto", False)])
def test_no_paid_history_reserve_when_paid_trends_is_disabled(provider, enabled):
    cfg = config(trends={"provider": provider}, sources={"trends": enabled})
    assert trends_plan(cfg)["history_reserve"] == 0


def test_zero_series_is_observed_but_does_not_become_a_forecast(tmp_path):
    cfg = config()
    run = Run("zero-history", tmp_path)
    result = history.analyze(run, Client(run, cfg, lambda _, p: timeline(p, zero=True)), cfg, directions(2))
    assert all(h["status"] == "available" for h in result)
    assert all(h["usable_years"] == [] for h in result)
    state = outcome("history", result, cfg)
    assert state["status"] == "partial" and "dự báo 0/2" in state["note"]


def test_two_years_may_support_a_forecast_but_not_a_rolling_backtest(tmp_path):
    cfg = config(history_years=[2024, 2025])
    run = Run("short-history", tmp_path)
    result = history.analyze(run, Client(run, cfg, lambda _, p: timeline(p)), cfg, directions(1))
    assert any(r["prediction"] is not None for r in result[0]["forecast"])
    assert result[0]["validation"]["folds"] == []
    state = outcome("history", result, cfg)
    assert state["status"] == "partial" and "kiểm chứng hồi cứu 0/1" in state["note"]


def test_low_signal_is_a_completed_measurement_and_excluded_rows_do_not_taint_selection():
    cfg = config()
    rows = [{"status": "available"}] * 10 + [{"status": "low_signal"}] * 20
    assert outcome("screen", {"status": "available", "rows": rows}, cfg)["status"] == "complete"
    assert outcome("select", {"requested": 10, "selected_keywords": 10, "rows": rows}, cfg)["status"] == "complete"
    assert outcome("select", {"requested": 10, "selected_keywords": 8, "rows": rows}, cfg)["status"] == "partial"
    rows.append({"status": "unavailable"})
    assert outcome("screen", {"status": "available", "rows": rows}, cfg)["status"] == "partial"
    assert outcome("commentary", {}, cfg)["status"] == "skipped"


def test_exhausted_llm_uses_traceable_seed_groups_without_requests(tmp_path):
    cfg = config(limits={"llm_requests": 0})
    cfg["niches"] = [{"id": "N", "name": "Quà hữu ích", "seeds": ["coffee mug"]}]
    run = Run("seed-groups", tmp_path)
    def unexpected(*_):
        pytest.fail("No model request should be sent after the configured cap")
    result = discover.cluster(run, Client(run, cfg, unexpected), cfg, {"keywords": [
        {"id": "K", "text": "coffee mug", "seed": "coffee mug", "niche_id": "N", "evidence_ids": []}]})
    assert result[0]["grouping_method"] == "seed_rules"
    assert not run.manifest["usage"]
    assert "theo seed" in outcome("cluster", result, cfg)["note"]


def test_old_run_quality_is_projected_without_mutating_stored_status_or_usage(app):
    base, manager = app
    run = Run("old-status", manager.root)
    run.manifest.update(input=config(), status="partial", usage=[])
    run.manifest["stages"] = {name: {"status": "partial"} for name in ("screen", "select", "history", "commentary")}
    run.save()
    run.checkpoint("screen", {"rows": [{"status": "available"}, {"status": "low_signal"}]})
    run.checkpoint("select", {"selected_keywords": 10, "requested": 10})
    run.checkpoint("history", [{"status": "unavailable", "direction_id": "D", "reason": "quota"}])
    run.checkpoint("commentary", {})
    with urlopen(base + "/api/runs/old-status", timeout=5) as response:
        state = json.load(response)
    assert state["stages"]["screen"]["status"] == "complete"
    assert state["stages"]["select"]["status"] == "complete"
    assert state["stages"]["history"]["status"] == "partial"
    assert state["stages"]["commentary"]["status"] == "skipped"
    with urlopen(base + "/api/runs/old-status/stages/screen", timeout=5) as response:
        detail = json.load(response)
    assert detail["status"] == "complete" and "ít tín hiệu" in detail["note"]
    original = run.db.get_manifest(run.id)
    assert original["stages"]["screen"]["status"] == "partial"
    assert original["usage"] == []
