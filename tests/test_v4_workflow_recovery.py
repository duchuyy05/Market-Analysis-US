"""The required Trends stage cannot silently turn LLM seeds into measured trends."""
import json
from datetime import date, datetime, timezone
from urllib.error import HTTPError

import pytest

from market_research.common import read_json
from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import products, screen, selection
from market_research.llm.client import complete
from test_v3_discovery import free_response, fixture


def cfg(**changes):
    return validate_config({"brief": "Quà cuối năm cho bạn bè tại Mỹ", "as_of_date": "2026-10-28",
        "business": {"profile": "general", "categories": []},
        "limits": {"top_keywords": 1, "candidate_keywords": 32, "related_seeds_per_niche": 0, "retry_attempts": 0}, **changes})


def paid_series(params):
    native = free_response({"endpoint": "widgetdata/multiline", "req": {"comparisonItem": [
        {"keyword": query, "geo": "US", "time": params["date"]} for query in params["q"].split(",")]}})
    return {"interest_over_time": {"timeline_data": [
        {"timestamp": row["time"], "isPartial": row["isPartial"], "values": [
            {"query": query, "extracted_value": row["value"][i]} for i, query in enumerate(params["q"].split(","))]}
        for row in native["default"]["timelineData"]]}}


def test_429_recovers_paid_screening_before_any_amazon_request(tmp_path):
    calls = []
    base = fixture(calls, blocked=True)
    def transport(provider, params):
        if provider == "serpapi" and params.get("engine") == "google_trends":
            calls.append((provider, params))
            return paid_series(params)
        return base(provider, params)
    run = execute(cfg(), root=tmp_path, run_id="recovered", transport=transport, event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert run.manifest["status"] in {"complete", "partial"}
    assert data["selection"]["is_trends_hot_ranking"] is True
    assert data["directions"][0]["keyword"] == "candle warmer"
    assert all(row["provider"] == "serpapi" for row in data["keyword_screening"] if row["status"] == "available")
    first_paid_trend = next(i for i, (_, p) in enumerate(calls) if p.get("engine") == "google_trends")
    first_amazon = next(i for i, (_, p) in enumerate(calls) if p.get("engine") == "amazon")
    assert first_paid_trend < first_amazon
    assert sum(provider == "google_trends_free" for provider, _ in calls) == 1
    events = [json.loads(line) for line in (run.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "trends_recovered" for e in events)
    assert any(e["event"] == "llm_result" and e["details"]["task"] == "understand" for e in events)


def test_exhausted_recovery_waits_before_products_and_resumes_from_checkpoints(tmp_path):
    calls = []
    base = fixture(calls, blocked=True)
    fail = [True]
    def transport(provider, params):
        if provider == "serpapi" and params.get("engine") == "google_trends":
            calls.append((provider, params))
            if fail[0]:
                raise HTTPError("https://serpapi.com", 401, "invalid key", {}, None)
            return paid_series(params)
        return base(provider, params)
    run = execute(cfg(), root=tmp_path, run_id="waiting", transport=transport, event=lambda _: None)
    assert run.manifest["status"] == "awaiting_trends"
    assert run.manifest["stages"]["screen"]["status"] == "waiting"
    assert run.manifest["stages"]["search"]["status"] == "waiting"
    assert not (run.path / "dataset.json").exists()
    assert not (run.output / "report.html").exists()
    assert (run.output / "tables/keyword_screening.csv").exists()
    assert not any(p.get("engine") == "amazon" for _, p in calls)
    llm_calls = sum(provider == "openrouter" for provider, _ in calls)
    fail[0] = False
    resumed = execute(root=tmp_path, run_id=run.id, transport=transport, event=lambda _: None)
    assert resumed.manifest["status"] in {"partial", "complete"}
    assert resumed.manifest["stages"]["understand"]["attempts"] == 1
    assert sum(provider == "openrouter" for provider, _ in calls) == llm_calls + 1  # cluster only
    assert (run.output / "report.html").exists()


def test_zero_trends_budget_does_not_spend_reserved_amazon_quota_without_screening(tmp_path):
    calls = []
    config = cfg(limits={"top_keywords": 1, "related_seeds_per_niche": 0, "free_trends_requests": 0,
                         "trends_serpapi_requests": 0, "serpapi_requests": 20, "retry_attempts": 0})
    run = execute(config, root=tmp_path, run_id="zero-budget", transport=fixture(calls), event=lambda _: None)
    assert run.manifest["status"] == "awaiting_trends"
    assert not any(provider in {"serpapi", "google_trends_free"} for provider, _ in calls)


def test_partial_screening_selects_only_measured_keywords_in_required_mode():
    config = cfg()
    config["niches"] = [{"id": "N", "name": "Gifts"}]
    config["limits"]["top_keywords"] = 10
    discovery = {"keywords": [{"id": f"K{i}", "niche_id": "N", "text": word, "evidence_ids": []} for i, word in enumerate(("candle warmer", "unknown gift"))]}
    screening = {"rows": [{"keyword_id": "K0", "keyword": "candle warmer", "rank": 1, "evidence_ids": [], "status": "available"},
                          {"keyword_id": "K1", "keyword": "unknown gift", "rank": None, "evidence_ids": [], "status": "unavailable"}],
                 "method": "shared_anchor_28d_percentile_v1", "note": "Measured"}
    selected = selection.ranked(config, discovery, screening, [])
    assert selected["selected_keywords"] == 1
    assert selected["trends_verified_keywords"] == 1
    assert selected["rows"][1]["selected"] is False


def test_shopping_comparison_has_its_own_keyword_cap(tmp_path):
    config = cfg(limits={"shopping_keywords": 1}, sources={"shopping": True, "trends": False})
    run = Run("shopping-cap", tmp_path)
    calls = []
    def transport(provider, params):
        calls.append(params)
        return {"shopping_results": []} if params["engine"] == "google_shopping" else {"organic_results": []}
    directions = [{"id": str(i), "keyword": query, "search_query": query} for i, query in enumerate(("candle warmer", "desk organizer", "kitchen organizer"))]
    result = products.collect(run, Client(run, config, transport), config, directions)
    assert sum(p["engine"] == "amazon" for p in calls) == 3
    assert sum(p["engine"] == "google_shopping" for p in calls) == 1
    assert sum(r["status"] == "limited" for r in result["source_status"]) == 2


def test_llm_malformed_json_uses_one_distinct_repair_request(tmp_path):
    config = cfg()
    run = Run("json-repair", tmp_path)
    calls = []
    def transport(provider, params):
        calls.append(params)
        content = '{"directions":' if len(calls) == 1 else json.dumps({"directions": [{"name": "Quà", "keyword_ids": ["K"], "representative_keyword_id": "K"}]})
        return {"choices": [{"message": {"content": content}}]}
    result = complete(Client(run, config, transport), "cluster", {"keywords": [{"id": "K", "text": "candle warmer"}]})
    assert result["directions"][0]["keyword_ids"] == ["K"]
    assert len(calls) == 2 and len(calls[1]["messages"]) == 4
    events = (run.path / "events.jsonl").read_text(encoding="utf-8")
    assert 'llm_repaired' in events


def test_log_drops_secrets_reasoning_and_bounds_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "fake-private-value-for-test")
    run = Run("sanitized", tmp_path)
    run.log("discover", "test", "Inspect", api_key="private", reasoning="do not log", nested={"authorization": "Bearer hidden"}, body="fake-private-value-for-test" + "x" * 50000)
    content = (run.path / "events.jsonl").read_text(encoding="utf-8")
    assert "fake-private-value-for-test" not in content
    assert 'do not log' not in content
    assert 'Bearer hidden' not in content
    assert len(content) < 20000
