import csv
import json
from urllib.error import HTTPError

import pytest

from market_research.common import canonical_url
from market_research.config import validate_config
from market_research.storage.run import Run
from market_research.providers.client import Client, BudgetExceeded, SourceError, scrub
from market_research.analysis.products import candidate, resolve, purchase_band, enrich_product


def config(**overrides):
    return validate_config({"brief": "Research products", **overrides})


def test_canonical_urls_preserve_product_query_identity():
    assert canonical_url("https://shop.test/item?sku=one&utm_source=a") != canonical_url("https://shop.test/item?sku=two&utm_source=b")
    assert canonical_url("https://www.amazon.com/dp/B012345678?tag=x") == "https://www.amazon.com/dp/B012345678"


def test_persistent_budget_includes_failed_attempts_and_resume(tmp_path):
    run = Run("budget", tmp_path)
    cfg = config(limits={"serpapi_requests": 1, "retry_attempts": 0})
    def failure(*_):
        raise HTTPError("https://example.test", 429, "limited", {}, None)
    with pytest.raises(SourceError):
        Client(run, cfg, failure).request("serpapi", {"q": "one"})
    resumed = Run("budget", tmp_path)
    with pytest.raises(BudgetExceeded):
        Client(resumed, cfg, lambda *_: {}).request("serpapi", {"q": "two"})
    assert len(resumed.manifest["usage"]) == 1


def test_cache_replay_makes_no_request(tmp_path):
    run = Run("cache", tmp_path)
    calls = []
    client = Client(run, config(), lambda *args: calls.append(args) or {"organic_results": []})
    first = client.request("serpapi", {"q": "one"})
    again = Client(Run("cache", tmp_path), config(), lambda *_: pytest.fail("Network on cache")).request("serpapi", {"q": "one"})
    assert first["retrieved_at"] == again["retrieved_at"]
    assert len(calls) == 1


def test_secrets_are_removed_recursively():
    result = scrub({"nested": [{"api_key": "secret"}, "https://x.test?token=secret", "secret"]}, ["secret"])
    assert "secret" not in json.dumps(result)


def test_purchase_bands_never_parse_ratings_as_sales():
    assert purchase_band("2K+ bought in past month") == 2000
    assert purchase_band("1,000 reviews") is None
    assert purchase_band(None) is None


def test_sponsored_occurrence_does_not_remove_organic_same_asin(tmp_path):
    run = Run("matching", tmp_path)
    envelope = {"retrieved_at": "2026-10-22T00:00:00Z", "raw_file": "raw/test.json"}
    direction = {"id": "D1"}
    ad = candidate({"title": "Advent calendar", "asin": "B012345678", "sponsored": True}, "amazon", direction, envelope, run)
    organic = candidate({"title": "Advent calendar", "asin": "B012345678", "sponsored": False}, "amazon", direction, envelope, run)
    products, offers, matches, excluded = resolve([ad, organic])
    assert len(products) == 1 and len(excluded) == 1
    assert products[0]["sponsored"] is False


def test_shopping_amazon_merchant_links_merge_identity_without_merging_ratings(tmp_path):
    run = Run("cross-source", tmp_path)
    envelope = {"retrieved_at": "2026-10-22T00:00:00Z", "raw_file": "raw/test.json"}
    d = {"id": "D1"}
    amazon = candidate({"title": "Advent calendar", "asin": "B012345678", "rating": 4.1}, "amazon", d, envelope, run)
    shop = candidate({"title": "Advent calendar", "link": "https://www.amazon.com/dp/B012345678?tag=x", "rating": 4.9}, "shopping", d, envelope, run)
    products, *_ = resolve([amazon, shop])
    assert len(products) == 1
    assert products[0]["rating"] == 4.1
    assert len(products[0]["discovery_sources"]) == 2
    assert shop["purchase_lower_bound"] is None


def test_unknown_sponsored_remains_unknown(tmp_path):
    row = candidate({"title": "Desk organizer", "asin": "B012345678"}, "amazon", {"id": "D"}, {"retrieved_at": "2026-10-22", "raw_file": "x"}, Run("unknown", tmp_path))
    assert row["sponsored"] is None
    assert row["price"] is None


def test_details_do_not_silently_inherit_search_price_and_badge(tmp_path):
    run = Run("detail", tmp_path)
    envelope = {"retrieved_at": "2026-10-22", "raw_file": "x"}
    p = candidate({"title": "Advent calendar", "asin": "B012345678", "extracted_price": 10, "bought_last_month": "1K+ bought in past month"}, "amazon", {"id": "D"}, envelope, run)
    detail = {**envelope, "response": {"product_results": {"title": "Advent calendar"}}}
    updated, reviews = enrich_product(p, detail, run, 20, "2026-10-22")
    assert updated["price"] is None and updated["purchase_badge"] is None


def test_csv_complex_fields_roundtrip_and_formula_guard(tmp_path):
    run = Run("csv", tmp_path)
    run.table("test", [{"name": "=HYPERLINK(1)", "ids": ["a", "b"], "missing": None}])
    with (run.output / "tables/test.csv").open(encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["name"].startswith("'")
    assert json.loads(row["ids"]) == ["a", "b"]
    assert row["missing"] == ""


def test_no_results_query_automatically_uses_bounded_simplification(tmp_path):
    from market_research.workflow.products import search_source
    from market_research.providers import amazon
    requests = []
    def transport(provider, params):
        requests.append(params["k"])
        if "family name" in params["k"]:
            return {"error": "Amazon hasn't returned any results for this query."}
        return {"organic_results": [{"title": "Personalized Christmas ornament", "asin": "B012345678"}]}
    run = Run("fallback", tmp_path)
    client = Client(run, config(limits={"retry_attempts": 0}), transport)
    result = search_source(client, amazon, "Personalized family name Christmas ornament")
    assert result["response"]["organic_results"]
    assert requests == ["Personalized family name Christmas ornament", "personalized christmas ornament"]
    # Resume preserves the no-results response and successful fallback, so no repeat charges.
    search_source(Client(Run("fallback", tmp_path), config(), transport), amazon, "Personalized family name Christmas ornament")
    assert len(requests) == 2


def test_credentials_and_nonfinite_prices_rejected():
    with pytest.raises(ValueError, match="secret"):
        config(extra={"api_key": "do-not-save"})
    with pytest.raises(ValueError, match="price_range"):
        config(price_range=[float("nan"), 10])
