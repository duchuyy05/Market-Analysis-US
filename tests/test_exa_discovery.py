"""Exa complements source gaps within caps; fixtures spend no real credits."""
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone
from urllib.error import HTTPError

import pytest

from market_research.common import read_json
from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers import exa
from market_research.providers.client import Client, environment, scrub
from market_research.storage.run import Run
from market_research.workflow import broad
from market_research.workflow.products import public_listing_rows


def config(**changes):
    return validate_config({"brief": "Tìm móc khóa hình nhân vật gì trong tháng 11", "as_of_date": "2026-11-03",
        "selling_months": [11], "history_years": [2023, 2024, 2025], "target_year": 2026,
        "business": {"profile": "custom_manufacturing", "categories": ["keychains", "apparel"]},
        "niches": [{"id": "K", "name": "Móc khóa", "seeds": ["acrylic keychain"]}],
        "discovery": {"sites": ["etsy"], "focus": "designs", "web_provider": "combined"},
        "sources": {"trends": False, "web": True}, "llm": {"enabled": False},
        "limits": {"candidate_keywords": 2, "tavily_requests": 1, "exa_requests": 2, "retry_attempts": 0}, **changes})


def exa_result(title="Hello Kitty keychain", url="https://etsy.com/listing/keychain", **fields):
    return {"results": [{"title": title, "url": url, "text": title, **fields}], "costDollars": {"total": .007}}


def test_env_loads_exa_and_secret_headers_never_enter_configs_or_raw(tmp_path):
    (tmp_path/".env").write_text("EXA_API_KEY=fixture-only-key\n", encoding="utf-8")
    assert environment(tmp_path)["EXA_API_KEY"] == "fixture-only-key"
    assert scrub({"headers": {"x-api-key": "private"}, "exa_api_key": "private"}) == {"headers": {"x-api-key": "[REDACTED]"}, "exa_api_key": "[REDACTED]"}
    with pytest.raises(ValueError, match=".env"):
        config(exa_api_key="private")


def test_search_normalizes_text_dates_and_images_without_mutating_raw_and_tracks_cost(tmp_path):
    cfg, calls = config(), []
    run = Run("exa-adapter", tmp_path)
    def send(provider, params):
        calls.append((provider, params))
        assert provider == "exa" and params["numResults"] <= 10 and params["type"] == "auto"
        assert params["includeDomains"] == ["etsy.com"] and params["userLocation"] == "US"
        assert params["endPublishedDate"] == "2026-11-03T23:59:59Z"
        assert "summary" not in params["contents"]
        return exa_result(publishedDate="2025-11-10T00:00:00Z", image="https://example.com/keychain.jpg",
                          extras={"imageLinks": ["https://example.com/detail.jpg", "javascript:bad"]})
    result = exa.search(Client(run, cfg, send), "keychain designs", ["etsy"], cfg["as_of_date"])
    row = result["response"]["results"][0]
    assert row["published_date"].startswith("2025-11") and row["content"] == "Hello Kitty keychain"
    assert row["image_links"] == ["https://example.com/detail.jpg"]
    raw = read_json(run.path/result["raw_file"])
    assert "text" in raw["response"]["results"][0] and "content" not in raw["response"]["results"][0]
    assert run.manifest["usage"][0]["cost_usd"] == .007 and len(calls) == 1


def test_exa_wire_request_uses_header_auth_and_never_places_key_in_url(tmp_path, monkeypatch):
    cfg = config()
    client = Client(Run("exa-wire", tmp_path), cfg)
    client.env["EXA_API_KEY"] = "fixture-only-key"
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def read(self): return b'{"results": []}'
    def open_request(request, timeout):
        assert request.full_url == "https://api.exa.ai/search"
        assert request.get_header("X-api-key") == "fixture-only-key"
        assert "fixture-only-key" not in request.data.decode()
        return Response()
    monkeypatch.setattr("market_research.providers.client.urlopen", open_request)
    assert client._send("exa", {"query": "test"}) == {"results": []}


def test_exa_shared_cache_replays_with_zero_budget_and_no_http(tmp_path):
    cfg = config()
    first_run = Run("exa-cache-first", tmp_path)
    first = exa.search(Client(first_run, cfg, lambda *_: exa_result()), "character keychain", ["etsy"])
    cfg["limits"]["exa_requests"] = 0
    next_run = Run("exa-cache-next", tmp_path)
    second = exa.search(Client(next_run, cfg, lambda *_: pytest.fail("Cache must prevent HTTP")), "character keychain", ["etsy"])
    assert second["shared_cache"] and second["retrieved_at"] == first["retrieved_at"]
    assert not next_run.manifest["usage"]


@pytest.mark.parametrize("status", [401, 402, 429])
def test_provider_stops_on_key_credit_or_rate_limit_without_retry_spending(tmp_path, status):
    cfg = config(discovery={"sites": ["etsy"], "web_provider": "exa", "focus": "designs"}, limits={"exa_requests": 4, "retry_attempts": 2})
    run, calls = Run("exa-stop-"+str(status), tmp_path), []
    run.manifest["input"] = cfg
    def send(provider, params):
        calls.append(provider)
        raise HTTPError("https://api.exa.ai/search", status, "limit", {}, io.BytesIO(b'{"error":{"message":"limited"}}'))
    result = broad.discover(run, Client(run, cfg, send), cfg)
    assert calls == ["exa"] and len(run.manifest["usage"]) == 1
    assert not result["keywords"]
    assert next(row for row in result["discovery_sources"] if row.get("provider") == "exa")["status"] == "unavailable"


def test_combined_uses_exa_for_content_gaps_instead_of_measuring_only_blanks(tmp_path):
    cfg, calls = config(), []
    run = Run("exa-gaps", tmp_path)
    run.manifest["input"] = cfg
    def send(provider, params):
        calls.append(provider)
        return {"results": [{"title": "Clear acrylic keychain", "content": "Clear acrylic keychain", "url": "https://etsy.com/listing/blank"}]} if provider == "tavily" else exa_result()
    result = broad.discover(run, Client(run, cfg, send), cfg)
    assert calls == ["tavily", "exa"]
    assert [row["text"] for row in result["keywords"]] == ["Hello Kitty keychain"]
    source = next(page for page in result["web_context"] if "Hello Kitty" in page["title"])
    assert source["retrieval_providers"] == ["exa"]
    assert run.evidence[source["evidence_ids"][0]]["raw_file"].startswith("raw/exa/")


def test_no_exa_call_when_tavily_already_covers_requested_content(tmp_path):
    cfg, calls = config(discovery={"sites": ["etsy"], "focus": "designs", "web_provider": "auto"}), []
    run = Run("exa-not-needed", tmp_path)
    run.manifest["input"] = cfg
    def send(provider, params):
        calls.append(provider)
        assert provider == "tavily"
        return {"results": [{"title": "Hello Kitty keychain", "content": "Hello Kitty keychain", "url": "https://etsy.com/listing/k"}]}
    client = Client(run, cfg, send)
    client.env.update(TAVILY_API_KEY="fixture-tavily", EXA_API_KEY="fixture-exa")
    result = broad.discover(run, client, cfg)
    assert calls == ["tavily"] and result["summary"]["source_content_candidates"] == 1


def test_explicit_combined_mode_samples_both_indexes_even_after_first_source_covers_family(tmp_path):
    cfg, calls = config(), []
    run = Run("both-indexes", tmp_path)
    run.manifest["input"] = cfg
    def send(provider, params):
        calls.append(provider)
        return {"results": [{"title": "Hello Kitty keychain", "content": "Hello Kitty keychain", "url": "https://etsy.com/listing/k"}]} if provider == "tavily" else exa_result("Woodland fox keychain", "https://etsy.com/listing/fox")
    result = broad.discover(run, Client(run, cfg, send), cfg)
    assert calls == ["tavily", "exa"]
    assert {row["text"] for row in result["keywords"]} == {"Hello Kitty keychain", "Woodland fox keychain"}


def test_exa_works_with_tavily_at_zero_and_auto_selects_a_configured_key(tmp_path):
    cfg = config(discovery={"sites": ["etsy"], "web_provider": "auto", "focus": "designs"}, limits={"tavily_requests": 0, "exa_requests": 1})
    run = Run("exa-only-budget", tmp_path)
    run.manifest["input"] = cfg
    calls = []
    def send(provider, params):
        calls.append(provider)
        return exa_result()
    client = Client(run, cfg, send)
    client.env["EXA_API_KEY"] = "fixture-only-key"
    result = broad.discover(run, client, cfg)
    assert calls == ["exa"] and result["keywords"][0]["text"] == "Hello Kitty keychain"


def test_same_page_is_deduplicated_but_exa_richer_source_and_images_are_retained(tmp_path):
    cfg = config(niches=[{"id": "K", "name": "Móc khóa", "seeds": ["keychain"]}, {"id": "S", "name": "Áo", "seeds": ["shirt"]}])
    run = Run("exa-rich-duplicate", tmp_path)
    run.manifest["input"] = cfg
    def send(provider, params):
        if provider == "tavily":
            return {"results": [{"title": "Hello Kitty keychain", "content": "Hello Kitty keychain", "url": "https://etsy.com/listing/k"}]}
        result = exa_result(url="https://etsy.com/listing/k", image="https://example.com/kitty.jpg")
        result["results"][0]["text"] = "Hello Kitty keychain. Additional literal description of the illustrated character."
        result["results"].append({"title": "Woodland fox shirt", "text": "Woodland fox shirt", "url": "https://etsy.com/listing/shirt"})
        return result
    result = broad.discover(run, Client(run, cfg, send), cfg)
    kitty = next(page for page in result["web_context"] if page["url"].endswith("/k"))
    assert len(result["web_context"]) == 2 and len(kitty["evidence_ids"]) == 2
    assert kitty["retrieval_providers"] == ["exa", "tavily"] and kitty["image"].endswith("kitty.jpg")
    assert "Additional literal" in kitty["excerpt"]


@pytest.mark.parametrize("product_budget", [0, 2])
def test_combined_sources_free_trends_and_bounded_product_quota_complete_the_workflow(tmp_path, product_budget):
    cfg = config(niches=[{"name": "Móc khóa", "seeds": ["keychain"]}, {"name": "Áo", "seeds": ["shirt"]}],
        sources={"web": True, "trends": True, "amazon": product_budget > 0, "shopping": False},
        trends={"provider": "free", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        limits={"candidate_keywords": 2, "top_keywords": 2, "monthly_keywords": 2, "tavily_requests": 1,
                "exa_requests": 1, "free_trends_requests": 20, "serpapi_requests": product_budget, "trends_serpapi_requests": 0,
                "serpapi_product_reserve": 0, "product_details": 0, "related_seeds_per_niche": 0, "retry_attempts": 0})
    calls, searched = [], []
    def send(provider, params):
        calls.append(provider)
        if provider == "tavily":
            return {"results": [{"title": "Hello Kitty keychain", "content": "Hello Kitty keychain", "url": "https://etsy.com/listing/k"}]}
        if provider == "exa":
            return exa_result("Woodland fox shirt", "https://etsy.com/listing/shirt", image="https://example.com/shirt.jpg")
        if provider == "google_trends_free":
            if params["endpoint"] == "explore":
                return {"widgets": [{"id": "TIMESERIES", "token": "public-widget", "request": params["req"]}]}
            entries = params["req"]["comparisonItem"]
            start, end = map(date.fromisoformat, entries[0]["time"].split())
            assert start.month == end.month == 11
            points = []
            while start <= end:
                points.append({"time": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())),
                    "value": [20 if entry["keyword"] == "gift basket" else 60 for entry in entries]})
                start += timedelta(days=1)
            return {"default": {"timelineData": points}}
        assert provider == "serpapi" and params["engine"] == "amazon"
        searched.append(params["k"])
        asin = "B0"+hashlib.sha256(params["k"].encode()).hexdigest()[:8].upper()
        return {"organic_results": [{"asin": asin, "title": params["k"], "extracted_price": 12}]}
    run = execute(cfg, run_id="combined-free-workflow", root=tmp_path, transport=send, event=lambda _: None)
    data = run.load_dataset()
    assert run.manifest["status"] in {"complete", "partial"}
    assert set(searched) == ({"Hello Kitty keychain", "Woodland fox shirt"} if product_budget else set())
    assert len(data["products"]) == len(data["ideas"]) == 2
    assert calls.count("tavily") == calls.count("exa") == 1 and calls.count("serpapi") == product_budget
    assert 0 < calls.count("google_trends_free") <= 20 and "openrouter" not in calls
    assert all(d["qualifying_months"] == [11] and d["measurement_query"] == d["search_query"] for d in data["directions"])
    assert (run.output/"report.html").is_file()
    if not product_budget:
        assert all(p["source"] == "public_web" and p["detail_status"] == "public_listing_excerpt" for p in data["products"])
        assert all(p["price"] is p["rating"] is p["review_count"] is p["purchase_lower_bound"] is None for p in data["products"])
        assert not data["reviews"]
        assert data["source_status"][-1]["extra_requests"] == 0


def test_reused_listing_rejects_pins_category_pages_wrong_subjects_and_unquoted_pages(tmp_path):
    run = Run("listing-guards", tmp_path)
    eid = run.add_evidence("public_web_discovery", "https://etsy.com/listing/123/kitty", "2026-11-03T00:00:00Z", "raw/exa/fixture.json", "Hello Kitty keychain")
    direction = {"id": "D", "keyword": "Hello Kitty keychain", "search_query": "Hello Kitty keychain"}
    item = {"title": "Hello Kitty keychain", "url": "https://etsy.com/listing/123/kitty", "evidence_ids": [eid]}
    assert public_listing_rows(run, [item], direction)[0]["source"] == "public_web"
    for change in [{"url": "https://pinterest.com/pin/123"}, {"url": "https://etsy.com/market/hello-kitty-keychain"},
                   {"title": "Plain acrylic keychain"}, {"evidence_ids": []}, {"title": "Hello Kitty keychain SVG digital download"}]:
        assert public_listing_rows(run, [{**item, **change}], direction) == []
