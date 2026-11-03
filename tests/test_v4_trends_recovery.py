"""Recovery/quotas are validated with fixtures; never contact a paid provider."""
from urllib.error import HTTPError

import pytest

from market_research.config import validate_config
from market_research.control import RunCancelled
from market_research.providers import trends
from market_research.providers.client import Client, SourceError, BudgetExceeded
from market_research.storage.run import Run
from market_research.common import read_json


def config(**overrides):
    return validate_config({"brief": "Research gifts in the US", "as_of_date": "2026-10-28", **overrides})


def series(queries):
    return {"interest_over_time": {"timeline_data": [{"timestamp": "1790553600", "values": [
        {"query": q, "extracted_value": 20 + i} for i, q in enumerate(queries)]}]}}


def blocked_free_paid_series(calls):
    def send(provider, params):
        calls.append((provider, params))
        if provider == "google_trends_free":
            raise HTTPError("https://trends.google.com", 429, "limited", {}, None)
        return series(params["q"].split(","))
    return send


def test_new_defaults_enable_auto_recovery_with_explicit_guardrails():
    cfg = config()
    assert cfg["trends"]["provider"] == "auto"
    assert cfg["trends"]["required"] is True
    assert cfg["limits"]["trends_serpapi_requests"] == 8
    assert cfg["limits"]["serpapi_product_reserve"] == 10
    assert cfg["limits"]["trends_related_requests"] == 0
    assert cfg["limits"]["shopping_keywords"] == 2


def test_auto_recovers_429_then_reuses_free_circuit_without_repeating_google(tmp_path):
    calls = []
    cfg = config()
    run = Run("auto", tmp_path)
    client = Client(run, cfg, blocked_free_paid_series(calls))
    result = trends.compare(client, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    history = trends.history(client, "candle warmer", cfg)
    assert result["selected_provider"] == "serpapi"
    assert result["recovered"] is True
    assert "429" in result["recovery_reason"]
    assert history["selected_provider"] == "serpapi"
    assert sum(p == "google_trends_free" for p, _ in calls) == 1
    assert sum(p == "serpapi" for p, _ in calls) == 2
    assert [u["purpose"] for u in run.manifest["usage"] if u["provider"] == "serpapi"] == ["trends_screen", "trends_history"]


def test_explicit_free_mode_never_uses_serpapi(tmp_path):
    calls = []
    cfg = config(trends={"provider": "free"})
    client = Client(Run("free-only", tmp_path), cfg, blocked_free_paid_series(calls))
    with pytest.raises(SourceError, match="429"):
        trends.compare(client, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert [p for p, _ in calls] == ["google_trends_free"]


def test_empty_free_widget_recovers_through_paid_series(tmp_path):
    calls = []
    def send(provider, params):
        calls.append((provider, params))
        if provider == "google_trends_free":
            if params["endpoint"] == "explore":
                return {"widgets": [{"id": "TIMESERIES", "token": "public-widget", "request": params["req"]}]}
            return {"default": {"timelineData": []}}
        return series(params["q"].split(","))
    cfg = config()
    result = trends.compare(Client(Run("empty-free", tmp_path), cfg, send), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert result["selected_provider"] == "serpapi"
    assert len(calls) == 3


def test_paid_empty_or_wrong_query_response_is_not_success(tmp_path):
    cfg = config(trends={"provider": "serpapi"})
    run = Run("wrong-query", tmp_path)
    with pytest.raises(SourceError, match="không đúng chuỗi"):
        trends.compare(Client(run, cfg, lambda *_: series(["unrequested"])), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert len(run.manifest["usage"]) == 1


def test_anchor_only_response_does_not_count_as_complete_comparison(tmp_path):
    cfg = config(trends={"provider": "serpapi"})
    with pytest.raises(SourceError, match="không đúng chuỗi"):
        trends.compare(Client(Run("anchor-only", tmp_path), cfg, lambda *_: series(["gift basket"])), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")


def test_screen_quality_rejects_free_window_then_uses_paid_fallback(tmp_path):
    calls = []
    def send(provider, params):
        calls.append(provider)
        if provider == "google_trends_free":
            if params["endpoint"] == "explore":
                return {"widgets": [{"id": "TIMESERIES", "token": "public-widget", "request": params["req"]}]}
            return {"default": {"timelineData": [{"time": "1790553600", "value": [0, 10]}]}}
        return series(params["q"].split(","))
    cfg = config()
    def quality(envelope):
        values = envelope["response"]["interest_over_time"]["timeline_data"][0]["values"]
        return values[0]["extracted_value"] >= 1
    result = trends.compare(Client(Run("window-quality", tmp_path), cfg, send), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28", quality=quality)
    assert result["selected_provider"] == "serpapi"
    assert calls == ["google_trends_free", "google_trends_free", "serpapi"]


def test_paid_related_default_zero_preserves_screening_budget(tmp_path):
    calls = []
    cfg = config()
    client = Client(Run("related", tmp_path), cfg, blocked_free_paid_series(calls))
    with pytest.raises(BudgetExceeded, match="trần Related trả phí bằng 0"):
        trends.related(client, "candle warmer", cfg["as_of_date"])
    assert not any(p == "serpapi" for p, _ in calls)
    assert client.trends_budget()["remaining"] == 8


def test_retry_is_charged_against_trends_subcap_and_cannot_consume_reserve(tmp_path):
    cfg = config(trends={"provider": "serpapi"}, limits={"serpapi_requests": 4, "serpapi_product_reserve": 3, "trends_serpapi_requests": 8, "retry_attempts": 2})
    run = Run("retry-reserve", tmp_path)
    calls = []
    def send(provider, params):
        calls.append(params["engine"])
        if params["engine"] == "google_trends":
            raise HTTPError("https://serpapi.com/search.json", 500, "temporary", {}, None)
        return {"organic_results": []}
    client = Client(run, cfg, send)
    with pytest.raises(BudgetExceeded, match="Hết phần SerpApi dành cho Trends"):
        trends.compare(client, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert calls == ["google_trends"]
    for i in range(3):
        client.request("serpapi", {"engine": "amazon", "k": f"gift {i}"})
    with pytest.raises(BudgetExceeded):
        client.request("serpapi", {"engine": "amazon", "k": "too many"})
    assert len(run.manifest["usage"]) == 4


def test_resume_retains_trends_attempt_count_and_cache_is_free(tmp_path):
    cfg = config(trends={"provider": "serpapi"}, limits={"serpapi_requests": 4, "serpapi_product_reserve": 3, "trends_serpapi_requests": 1})
    run = Run("resume-cap", tmp_path)
    calls = []
    client = Client(run, cfg, blocked_free_paid_series(calls))
    original = trends.compare(client, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    again = Client(Run(run.id, tmp_path), cfg, lambda *_: pytest.fail("No extra API on cache"))
    assert trends.compare(again, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")["retrieved_at"] == original["retrieved_at"]
    with pytest.raises(BudgetExceeded):
        trends.history(again, "candle warmer", cfg)
    assert len(calls) == 1


def test_reserve_larger_than_total_disables_paid_fallback(tmp_path):
    cfg = config(limits={"serpapi_requests": 3, "serpapi_product_reserve": 10})
    calls = []
    client = Client(Run("low-total", tmp_path), cfg, blocked_free_paid_series(calls))
    with pytest.raises(BudgetExceeded, match="giữ 10 lượt"):
        trends.compare(client, ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert [p for p, _ in calls] == ["google_trends_free"]


def test_cancellation_is_not_caught_and_does_not_trigger_paid_fallback(tmp_path, monkeypatch):
    from market_research.providers import free_trends
    calls = []
    def cancelled(*_, **__):
        raise RunCancelled("stopped")
    monkeypatch.setattr(free_trends, "fetch", cancelled)
    cfg = config()
    with pytest.raises(RunCancelled):
        trends.compare(Client(Run("cancel", tmp_path), cfg, lambda *args: calls.append(args) or {}), ["gift basket"], cfg, "2026-07-31 2026-10-28")
    assert calls == []


def test_provider_logs_redact_secrets_and_widget_codes(tmp_path):
    cfg = config()
    run = Run("logs", tmp_path)
    entries = []
    run.log = lambda stage, event, message, **fields: entries.append((stage, event, message, fields))
    client = Client(run, cfg, lambda *_: {})
    client.env["SERPAPI_API_KEY"] = "sensitive-value"
    client.log("diagnostic", "request", api_key="sensitive-value", nested={"widget_code": "public-token", "text": "sensitive-value", "reasoning": "do not store"})
    body = str(entries)
    assert "sensitive-value" not in body
    assert "public-token" not in body
    assert "do not store" not in body
    assert "[REDACTED]" in body


def test_invalid_paid_response_retains_raw_and_fetches_again_on_resume(tmp_path):
    cfg = config(trends={"provider": "serpapi"})
    run = Run("invalid-cache", tmp_path)
    calls = []
    def send(provider, params):
        calls.append(params)
        return {"interest_over_time": {"timeline_data": []}} if len(calls) == 1 else series(params["q"].split(","))
    with pytest.raises(SourceError):
        trends.compare(Client(run, cfg, send), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    saved = next((run.path / "raw/serpapi").glob("*.json"))
    body = read_json(saved)
    assert body["response"]["interest_over_time"]["timeline_data"] == []
    assert body["validation_error"]
    result = trends.compare(Client(Run(run.id, tmp_path), cfg, send), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert result["selected_provider"] == "serpapi"
    assert len(calls) == 2


def test_invalidation_never_follows_raw_path_outside_provider_boundary(tmp_path):
    from market_research.common import write_json
    run = Run("boundary", tmp_path)
    protected = tmp_path / "protected.json"
    write_json(protected, {"keep": True})
    Client(run, config(), lambda *_: {}).invalidate({"provider": "serpapi", "raw_file": str(protected)}, "invalid")
    assert read_json(protected) == {"keep": True}


def test_invalid_free_comparison_invalidates_explore_and_widget_shared_cache(tmp_path):
    cfg = config(trends={"provider": "free"})
    run = Run("free-invalid", tmp_path)
    def send(provider, params):
        if params["endpoint"] == "explore":
            return {"widgets": [{"id": "TIMESERIES", "token": "public-widget", "request": params["req"]}]}
        return {"default": {"timelineData": []}}
    with pytest.raises(SourceError):
        trends.compare(Client(run, cfg, send), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    local = list((run.path / "raw/google_trends_free").glob("*.json"))
    shared = list((tmp_path / "data/cache/google_trends_free").glob("*.json"))
    assert len(local) == len(shared) == 2
    assert all(read_json(p).get("validation_error") for p in local + shared)


@pytest.mark.parametrize("overrides", [{"trends": {"required": "yes"}}, {"limits": {"trends_serpapi_requests": -1}}, {"limits": {"serpapi_product_reserve": True}}, {"limits": {"trends_related_requests": "1"}}])
def test_bad_recovery_config_is_rejected(overrides):
    with pytest.raises(ValueError):
        config(**overrides)
