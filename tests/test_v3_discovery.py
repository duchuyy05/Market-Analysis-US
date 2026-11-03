"""No network or paid keys: verify discovery, calibration and quota boundaries."""
import hashlib
import json
import threading
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from market_research.common import read_json, write_json
from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers.client import Client, SourceError, BudgetExceeded
from market_research.providers.free_trends import decode
from market_research.storage.run import Run
from market_research.workflow import broad, screen
from market_research.control import RunCancelled


def free_response(params):
    if params["endpoint"] == "explore":
        related = params["req"].get("related_fixture", False)
        return {"widgets": [{"id": "RELATED_QUERIES", "request": params["req"], "token": "public-code"},
                            {"id": "TIMESERIES", "request": params["req"], "token": "public-code"}]}
    if params["endpoint"].endswith("relatedsearches"):
        return {"default": {"rankedList": []}}
    items = params["req"]["comparisonItem"]
    start, end = (date.fromisoformat(x) for x in items[0]["time"].split())
    timeline = []
    point = start
    while point <= end:
        values = [20 if item["keyword"] == "gift basket" else 60 if item["keyword"] == "candle warmer" else 10 for item in items]
        timeline.append({"time": str(int(datetime.combine(point, datetime.min.time(), timezone.utc).timestamp())), "value": values, "isPartial": False})
        point += timedelta(days=1 if (end-start).days < 366 else 7)
    return {"default": {"timelineData": timeline}}


def fixture(calls, *, blocked=False, fabricated=False):
    def send(provider, params):
        calls.append((provider, params))
        if provider == "google_trends_free":
            if blocked:
                raise HTTPError("https://trends.google.com/", 429, "limited", {}, None)
            return free_response(params)
        if provider == "tavily":
            if "tiktok.com" not in params.get("include_domains", []):
                return {"results": []}
            return {"results": [{"title": "Holiday candle warmer", "url": "https://www.tiktok.com/@shop/video/1", "content": "A candle warmer is shown as a holiday gift.", "published_date": "2026-10-20"},
                                {"title": "Future product", "url": "https://tiktok.com/future", "content": "Future evidence", "published_date": "2026-12-01"},
                                {"title": "Wrong domain", "url": "https://tiktok.com.evil.test/a", "content": "Not selected domain"}]}
        if provider == "openrouter":
            payload = json.loads(params["messages"][1]["content"])
            if "brief" in payload:
                result = {"category": "Holiday gifts for friends", "selling_months": [11, 12], "assumptions": [], "niches": [{"name": "Quà hữu ích", "seeds": ["desk organizer", "kitchen organizer"]}]}
            elif "pages" in payload:
                result = {"candidates": [{"keyword": "invented bestseller" if fabricated else "candle warmer", "quote": "A candle warmer is shown as a holiday gift.", "niche_id": payload["niches"][0]["id"], "source_id": payload["pages"][0]["id"]}]}
            else:
                keyword = payload["keywords"][0]
                result = {"directions": [{"name": "Nhóm quà", "keyword_ids": [k["id"] for k in payload["keywords"]], "representative_keyword_id": keyword["id"]}]}
            return {"choices": [{"message": {"content": json.dumps(result)}}]}
        assert provider == "serpapi" and params["engine"] in {"amazon", "amazon_product"}
        if params["engine"] == "amazon":
            return {"organic_results": [{"asin": "B0" + hashlib.sha256(params["k"].encode()).hexdigest()[:8].upper(), "title": params["k"], "extracted_price": 20, "sponsored": False}]}
        return {"product_results": {"title": "Gift", "extracted_price": 20}}
    return send


def config(**kwargs):
    # These regression tests exercise the original explicitly optional free mode.
    # Automatic fallback and the required screening gate have separate v4 tests.
    return validate_config({"brief": "Tìm quà cho bạn bè cuối năm tại Mỹ", "business": {"profile": "general", "categories": []}, "as_of_date": "2026-10-28", "trends": {"provider": "free", "required": False}, "limits": {"top_keywords": 1, "candidate_keywords": 32, "related_seeds_per_niche": 0}, **kwargs})


def test_web_newcomer_can_win_top_n_before_amazon_with_no_paid_trends(tmp_path):
    calls = []
    run = execute(config(), root=tmp_path, run_id="broad", transport=fixture(calls), event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert data["directions"][0]["keyword"] == "candle warmer"
    assert data["selection"]["is_trends_hot_ranking"] is True
    assert len(data["web_context"]) == 1
    assert data["web_context"][0]["audience_country"] == "unverified"
    assert data["histories"][0]["status"] == "available"
    assert all(m["value"] is None for m in data["histories"][0]["monthly"] if m["year"] == 2026 and m["month"] > 10)
    assert {p["engine"] for provider, p in calls if provider == "serpapi"} <= {"amazon", "amazon_product"}
    assert sum(provider == "serpapi" for provider, _ in calls) == 2
    first_amazon = next(i for i, (provider, _) in enumerate(calls) if provider == "serpapi")
    assert any(provider == "google_trends_free" for provider, _ in calls[:first_amazon])
    assert all(u["cost_usd"] == 0 for u in run.manifest["usage"] if u["provider"] == "google_trends_free")
    assert read_json(run.output / "validation.json")["errors"] == []
    assert (run.output / "tables/keyword_screening.csv").exists()
    assert "Khám phá từ trang công khai" in (run.output / "report.md").read_text(encoding="utf-8")


def test_google_429_stops_free_branch_but_keeps_amazon_and_honest_fallback(tmp_path):
    calls = []
    run = execute(config(), root=tmp_path, run_id="blocked", transport=fixture(calls, blocked=True), event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert sum(provider == "google_trends_free" for provider, _ in calls) == 1
    assert data["selection"]["is_trends_hot_ranking"] is False
    assert data["selection"]["trends_verified_keywords"] == 0
    assert data["products"]
    assert not any(p.get("engine") == "google_trends" for _, p in calls)
    assert "chưa xác minh" in data["selection"]["note"]


def test_fabricated_web_keyword_is_rejected_not_sent_to_trends(tmp_path):
    calls = []
    run = execute(config(), root=tmp_path, run_id="grounded", transport=fixture(calls, fabricated=True), event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert all(k["text"] != "invented bestseller" for k in data["keywords"])
    assert any("nguyên văn" in k["reason"] for k in data["keyword_exclusions"])


def test_shared_cache_reuses_free_http_and_keeps_original_observation_date(tmp_path):
    calls = []
    params = {"endpoint": "explore", "req": {"comparisonItem": []}}
    cfg = config()
    one = Client(Run("one", tmp_path), cfg, lambda *args: calls.append(args) or {"widgets": []}).request("google_trends_free", params)
    two_run = Run("two", tmp_path)
    two = Client(two_run, cfg, lambda *_: pytest.fail("Cache must prevent network")).request("google_trends_free", params)
    assert len(calls) == 1
    assert two["retrieved_at"] == one["retrieved_at"]
    assert two["shared_cache"] is True
    assert two_run.manifest["usage"] == []
    assert (two_run.path / two["raw_file"]).exists()


def test_stopped_free_request_saves_received_data_before_cancelling(tmp_path):
    cancel = threading.Event()
    cfg = config()
    run = Run("stop-free", tmp_path)
    def send(*_):
        cancel.set()
        return {"widgets": []}
    params = {"endpoint": "explore", "req": {}}
    with pytest.raises(RunCancelled):
        Client(run, cfg, send, cancel).request("google_trends_free", params)
    again = Client(run, cfg, lambda *_: pytest.fail("Must reuse in-flight response")).request("google_trends_free", params)
    assert again["response"] == {"widgets": []}
    assert len(run.manifest["usage"]) == 1


def test_comparison_calibrates_batches_with_anchor_instead_of_raw_100_scale(tmp_path):
    cfg = config(sources={"web": False}, llm={"enabled": False}, niches=[{"name": "A", "seeds": ["product a"]}])
    keywords = [{"id": f"K{i}", "text": f"product {i}", "niche_id": "N"} for i in range(5)]
    calls = []
    def send(provider, params):
        response = free_response(params)
        if params["endpoint"].endswith("multiline"):
            items = params["req"]["comparisonItem"]
            # Batch 1 raw value 80/anchor40 = 2; batch 2 raw30/anchor10 = 3.
            second = any(i["keyword"] == "product 4" for i in items)
            for row in response["default"]["timelineData"]:
                row["value"] = [10 if second else 40] + [30 if second else 80] * (len(items)-1)
        calls.append(params)
        return response
    run = Run("scale", tmp_path)
    result = screen.analyze(run, Client(run, cfg, send), cfg, {"keywords": keywords})
    by_word = {r["keyword"]: r for r in result["rows"]}
    assert by_word["product 4"]["relative_interest"] == 3
    assert by_word["product 0"]["relative_interest"] == 2
    assert by_word["product 4"]["rank"] == 1
    assert len(calls) == 4


@pytest.mark.parametrize("overrides", [{"discovery": {"sites": ["invalid"]}}, {"trends": {"provider": "apify"}}, {"trends": {"screen_days": 1}}, {"limits": {"candidate_keywords": 0}}])
def test_invalid_new_options_are_rejected(overrides):
    with pytest.raises(ValueError):
        config(**overrides)


def test_xssi_parser_accepts_widget_payload_and_rejects_html():
    assert decode(b')]}\',\n{"widgets": []}') == {"widgets": []}
    with pytest.raises(ValueError):
        decode(b'<html>blocked</html>')


def test_free_http_cap_counts_explore_and_widget_separately(tmp_path):
    cfg = config(limits={"free_trends_requests": 1})
    run = Run("one-http", tmp_path)
    from market_research.providers.trends import compare
    with pytest.raises(BudgetExceeded):
        compare(Client(run, cfg, lambda _, p: free_response(p)), ["gift basket", "candle warmer"], cfg, "2026-07-31 2026-10-28")
    assert len(run.manifest["usage"]) == 1
    assert run.manifest["usage"][0]["provider"] == "google_trends_free"


def test_real_transport_cooldown_persists_between_runs_without_paid_fallback(tmp_path, monkeypatch):
    from market_research.providers import free_trends
    calls = []
    def limited(*_):
        calls.append(True)
        raise HTTPError("https://trends.google.com", 429, "limited", {}, None)
    monkeypatch.setattr(free_trends, "send", limited)
    params = {"endpoint": "explore", "req": {}}
    with pytest.raises(SourceError, match="429"):
        Client(Run("limited-one", tmp_path), config()).request("google_trends_free", params)
    second = Run("limited-two", tmp_path)
    with pytest.raises(SourceError, match="15 phút"):
        Client(second, config()).request("google_trends_free", params)
    assert calls == [True]
    assert second.manifest["usage"] == []


def test_expired_shared_cache_makes_a_new_request(tmp_path):
    cfg = config()
    params = {"endpoint": "explore", "req": {}}
    Client(Run("old", tmp_path), cfg, lambda *_: {"widgets": []}).request("google_trends_free", params)
    for path in (tmp_path / "data/cache/google_trends_free").glob("*.json"):
        cached = read_json(path)
        cached["retrieved_at"] = "2020-01-01T00:00:00+00:00"
        write_json(path, cached)
    calls = []
    Client(Run("fresh", tmp_path), cfg, lambda *args: calls.append(args) or {"widgets": []}).request("google_trends_free", params)
    assert len(calls) == 1


def test_zero_anchor_never_produces_a_rank_or_infinite_growth(tmp_path):
    cfg = config()
    def zero(_, params):
        body = free_response(params)
        for row in body.get("default", {}).get("timelineData", []):
            row["value"][0] = 0
        return body
    run = Run("zero-anchor", tmp_path)
    result = screen.analyze(run, Client(run, cfg, zero), cfg, {"keywords": [{"id": "K1", "text": "candle warmer", "niche_id": "N1"}]})
    assert result["status"] == "unavailable"
    assert result["rows"][0]["rank"] is None
    assert result["rows"][0]["relative_interest"] is None
