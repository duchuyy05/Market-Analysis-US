"""Regression checks for the user's sparse 13/30 run; no provider network."""
import json
from datetime import date, timedelta

from market_research.config import validate_config
from market_research.storage.run import Run
from market_research.providers.client import Client
from market_research.workflow import products, understand, web_discovery, selection
from market_research.workflow.trend_queries import measurement_query, signal
from market_research.llm.client import complete


def config(**updates):
    return validate_config({"brief": "Christmas gifts for parents", "business": {"profile": "general", "categories": []}, "niches": [{"name": "Warm", "seeds": ["heated throw"]}], **updates})


def test_design_and_subject_modifiers_are_never_verified_by_a_generic_product_query():
    for query in ["personalized knitted family blanket", "heated throw for grandparents",
                  "personalized Christmas ornament", "Taylor Swift t shirt", "t shirt for Sabrina Carpenter fans",
                  "wrapping paper with woodland fox pattern"]:
        assert measurement_query(query) == query
    assert measurement_query("  Taylor  Swift t shirt  ") == "Taylor Swift t shirt"


def test_one_spike_is_low_signal_not_a_robust_keyword():
    start = date(2026, 10, 1)
    series = [{"start": (start+timedelta(days=i)).isoformat(), "end": (start+timedelta(days=i+1)).isoformat(), "value": 5 if i == 4 else 0} for i in range(28)]
    result = signal(series, start, start+timedelta(days=28))
    assert result["positive_points"] == 1
    assert result["has_signal"] is False
    for row in series[:4]:
        row["value"] = 5
    assert signal(series, start, start+timedelta(days=28))["has_signal"] is True


def test_enrich_uses_three_details_when_only_one_of_three_niches_has_products(tmp_path):
    cfg = config(niches=[{"name": "A", "id": "A", "seeds": ["ornament"]}, {"name": "B", "id": "B", "seeds": ["blanket"]}, {"name": "C", "id": "C", "seeds": ["robe"]}], sources={"shopping": False})
    run = Run("active-niches", tmp_path)
    calls = []
    def transport(provider, params):
        calls.append(params)
        if params["engine"] == "amazon":
            return {"organic_results": [{"title": "Ornament", "asin": f"B01234567{i}", "extracted_price": 20, "sponsored": False} for i in range(3)]}
        return {"product_results": {"title": "Ornament", "extracted_price": 20}}
    client = Client(run, cfg, transport)
    directions = [{"id": "D", "niche_id": "A", "keyword": "ornament", "search_query": "ornament"}]
    data = products.collect(run, client, cfg, directions)
    products.enrich(run, client, cfg, data, directions)
    assert sum(p["engine"] == "amazon_product" for p in calls) == 3


def test_model_that_returns_empty_length_is_skipped_for_later_tasks(tmp_path):
    cfg = config(llm={"model": "fixture/truncated:free"})
    run = Run("model-circuit", tmp_path)
    calls = []
    def transport(provider, params):
        calls.append(params["model"])
        if params["model"] == "fixture/truncated:free":
            return {"choices": [{"finish_reason": "length", "message": {"content": None}}]}
        return {"choices": [{"message": {"content": json.dumps({"directions": [{"name": "Gift", "keyword_ids": ["K"], "representative_keyword_id": "K"}]})}}]}
    client = Client(run, cfg, transport)
    complete(client, "cluster", {"keywords": [{"id": "K", "text": "robe"}]})
    complete(client, "cluster", {"keywords": [{"id": "K", "text": "blanket"}]})
    assert calls.count("fixture/truncated:free") == 1
    assert calls.count("openrouter/free") == 2


def test_noel_is_not_silently_treated_as_all_year(tmp_path):
    cfg = config(brief="Quà Noel cho bố mẹ", llm={"enabled": False})
    run = Run("season", tmp_path)
    result = understand.interpret(run, Client(run, cfg), cfg)
    assert result["selling_months"] == [11, 12]
    explicit = {**cfg, "selling_months": [10]}
    assert understand.interpret(run, Client(run, explicit), explicit)["selling_months"] == [10]


def test_recall_and_homepage_are_not_product_discovery_evidence():
    assert web_discovery.poor_page({"url": "https://corporate.walmart.com/recalls", "title": "Product Recalls"}, {"blanket"})
    assert web_discovery.poor_page({"url": "https://etsy.com/", "title": "Shop Etsy"}, {"blanket"})
    assert web_discovery.poor_page({"url": "https://etsy.com/listing/123", "title": "Knitted blanket", "content": "gift"}, {"blanket"}) is None


def test_focused_web_retry_uses_remaining_budget_to_find_grounded_keyword(tmp_path):
    cfg = config(limits={"tavily_requests": 4}, discovery={"sites": ["etsy"]})
    cfg["niches"][0]["id"] = "N"
    run = Run("web-retry", tmp_path)
    requests = []
    def transport(provider, params):
        if provider == "tavily":
            requests.append(params)
            return {"results": [{"url": "https://etsy.com/", "title": "Etsy"}]} if len(requests) == 1 else {"results": [{"url": "https://etsy.com/listing/123", "title": "heated throw", "content": "heated throw"}]}
        payload = json.loads(params["messages"][1]["content"])
        page = payload["pages"][0]
        return {"choices": [{"message": {"content": json.dumps({"candidates": [{"keyword": "heated throw", "quote": "heated throw", "niche_id": "N", "source_id": page["id"]}]})}}]}
    keywords = []
    contexts, states, excluded = web_discovery.harvest(run, Client(run, cfg, transport), cfg, {"N": cfg["niches"][0]}, lambda *args: keywords.append(args) or True)
    assert len(requests) == 2
    assert keywords[0][0] == "heated throw"
    assert contexts[0]["url"].endswith("123")
    assert states[0]["filtered_count"] == 1


def test_legacy_broad_proxy_does_not_verify_specific_design_candidates():
    cfg = config(limits={"top_keywords": 1})
    cfg["niches"][0]["id"] = "N"
    words = ["personalized knitted family blanket", "custom knitted blanket"]
    discovery = {"keywords": [{"id": str(i), "text": word, "niche_id": "N", "evidence_ids": []} for i, word in enumerate(words)]}
    measured = {"rows": [{"keyword_id": str(i), "keyword": word, "measurement_query": "knitted blanket", "measurement_scope": "broader_product_type", "rank": 1, "evidence_ids": []} for i, word in enumerate(words)], "method": "test", "note": "test"}
    selected = selection.ranked(cfg, discovery, measured, [])
    assert selected["selected_keywords"] == 0
    assert selected["trends_verified_keywords"] == 0
    assert selected["original_candidates"] == 2
    assert selected["directions"] == []
    assert all(r["rank"] is None and r["proxy_rank"] == 1 for r in selected["rows"])
    assert all(not r["exact_design_measured"] for r in selected["rows"])


def test_unused_detail_slots_are_reallocated_without_exceeding_global_cap(tmp_path):
    cfg = config(niches=[{"name": n, "id": n, "seeds": ["gift"]} for n in ("A", "B", "C")], limits={"product_details": 5}, sources={"shopping": False})
    run = Run("topup", tmp_path)
    calls = []
    def transport(provider, params):
        calls.append(params)
        if params["engine"] == "amazon":
            n = params["k"]
            return {"organic_results": [{"title": "Gift " + n, "asin": "B0" + str(ord(n)) + str(i).zfill(6), "extracted_price": 20, "sponsored": False} for i in range({"A": 1, "B": 1, "C": 8}[n])]}
        return {"product_results": {"title": "Gift", "extracted_price": 20}}
    client = Client(run, cfg, transport)
    directions = [{"id": n, "niche_id": n, "keyword": n, "search_query": n} for n in ("A", "B", "C")]
    data = products.collect(run, client, cfg, directions)
    products.enrich(run, client, cfg, data, directions)
    assert sum(p["engine"] == "amazon_product" for p in calls) == 5
