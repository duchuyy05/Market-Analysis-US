"""Content discovery must answer what is shown/written, before product search.

All source responses and demand in this file are fixtures, not live hot topics.
"""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from market_research.analysis.products import relevant
from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers.client import Client
from market_research.reporting.document import Document
from market_research.reporting.design_content import overview
from market_research.storage.run import Run
from market_research.workflow import broad, web_discovery
from market_research.workflow.products import content_filter, search_source
from market_research.workflow.design_content import content_mode, subject_terms, verified_source_design
from market_research.workflow.trend_queries import product_context


def config(**changes):
    return validate_config({"brief": "Tìm mẫu móc khóa hình gì, áo in gì và giấy gói họa tiết nào vào tháng 11",
        "as_of_date": "2026-11-02", "selling_months": [11], "history_years": [2023, 2024, 2025],
        "discovery": {"focus": "designs", "sites": ["etsy"]},
        "business": {"profile": "custom_manufacturing", "categories": ["keychains", "apparel", "printed_paper"]},
        "niches": [{"id": "K", "name": "Móc khóa", "seeds": ["clear acrylic keychain"]},
                   {"id": "S", "name": "Áo", "seeds": ["long sleeve graphic tee"]},
                   {"id": "W", "name": "Giấy gói", "seeds": ["kraft wrapping paper"]}],
        "trends": {"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        "limits": {"candidate_keywords": 3, "top_keywords": 3, "monthly_keywords": 3, "product_details": 0,
                   "related_seeds_per_niche": 0, "serpapi_requests": 20, "trends_serpapi_requests": 8,
                   "serpapi_product_reserve": 8, "tavily_requests": 4, "llm_requests": 3, "retry_attempts": 0},
        "sources": {"web": True, "trends": True, "shopping": False}, "llm": {"enabled": True}, **changes})


@pytest.mark.parametrize("query", ["clear acrylic keychain", "long sleeve graphic tee", "lined journal blank",
    "magnetic phone case", "spiral notebook", "canvas zipper pouch", "stainless steel keychain with matte coating"])
def test_substrate_details_do_not_answer_what_to_print(query):
    assert subject_terms(query) == ""
    assert product_context(query, config())
    assert not product_context(query, config(discovery={"focus": "models"}))


@pytest.mark.parametrize("query", ["Hello Kitty keychain", "Sabrina Carpenter t shirt", "not a morning person shirt",
    "woodland fox wrapping paper", "galaxy pattern wrapping paper", "snowflake keychain"])
def test_content_subject_is_retained_without_a_fixed_entity_catalog(query):
    assert subject_terms(query)
    assert not product_context(query, config())


def test_actual_report_brief_infers_content_but_incidental_example_preserves_models():
    brief = "Các mẫu sản phẩm đồ tặng như móc khóa, ốp lưng, hay ví (các sản phẩm nhỏ gọn), hay mẫu in hình áo thun vào dịp cuối năm"
    assert content_mode({"brief": brief}) == "designs"
    assert content_mode({"brief": "Tìm kiểu dáng, chất liệu, phôi cho nhiều nhóm hàng. Ví dụ áo in hình ca sĩ chỉ là ví dụ."}) == "models"
    assert content_mode({"brief": brief, "discovery": {"focus": "models"}}) == "models"


def test_source_spans_can_form_a_natural_query_without_claiming_verbatim():
    page = {"id": "P", "title": "A keychain featuring Hello Kitty", "evidence_ids": ["E"]}
    item = {"keyword": "Hello Kitty keychain", "quote": page["title"],
            "design": {"subject": "Hello Kitty", "product": "keychain", "kind": "character"}}
    design = verified_source_design(item, page)
    assert design["subject"] == "Hello Kitty" and design["query_origin"] == "composed_from_source_spans"
    assert design["evidence_ids"] == ["E"]
    assert verified_source_design({**item, "keyword": "Hello Kitty acrylic keychain"}, page) is None
    assert verified_source_design({**item, "design": {**item["design"], "subject": "Miffy"}}, page) is None
    assert verified_source_design({**item, "source_id": "other", "quote": "Hello Kitty shirt"}, page) is None
    assert verified_source_design({**item, "keyword": None}, page) is None


def test_full_slogan_and_character_must_match_the_product_not_just_a_word_bag():
    assert relevant("Not a Morning Person Graphic Tee", "not a morning person shirt", subject="Not a morning person", kind="slogan")
    assert not relevant("A Morning Person Not Today Shirt", "not a morning person shirt", subject="Not a morning person", kind="slogan")
    assert not relevant("Hello Kitty poster", "Hello Kitty keychain", subject="Hello Kitty", kind="character")
    assert not relevant("Plain cotton tee", "Sabrina Carpenter shirt", subject="Sabrina Carpenter", kind="person")


def test_empty_search_does_not_drop_words_from_a_measured_slogan():
    class Adapter:
        def search(self, client, query):
            assert query == "all in the family shirt"
            return {"response": {"organic_results": []}}
    assert search_source(None, Adapter(), "all in the family shirt", preserve_query=True)["response"]["organic_results"] == []


def test_enrichment_cannot_turn_a_matched_print_into_an_unrelated_variant(tmp_path):
    run = Run("variant-recheck", tmp_path)
    directions = [{"id": "D", "keyword": "Hello Kitty keychain", "content_focus": "designs",
                   "source_design": {"subject": "Hello Kitty", "kind": "character"}}]
    collected = {"products": [{"product_id": "P", "title": "Plain acrylic keychain", "direction_ids": ["D"]}],
                 "offers": [{"product_id": "P"}], "reviews": [], "product_matches": [], "exclusions": []}
    result = content_filter(collected, directions, run)
    assert not result["products"] and not result["offers"]
    assert result["exclusions"][0]["kind"] == "design_content_mismatch"


def test_saved_run_pages_explain_weak_sources_without_inventing_prints():
    pages = json.loads((Path(__file__).parent/"fixtures/shallow-run-source-pages.json").read_text(encoding="utf-8"))
    reasons = [web_discovery.poor_page({**page, "content": page["excerpt"]}, {"shirt", "keychain"}) for page in pages]
    assert reasons[0] and reasons[1] and reasons[3] and reasons[5]
    # A valid source mention does not turn material-only candidates into art.
    assert all(not web_discovery.literal_model_phrases({"title": query}, config()) for query in
               ["Clear acrylic keychain", "Long sleeve graphic tee", "Spiral notebook"])


def test_one_source_subject_does_not_stop_searching_other_families(tmp_path):
    cfg = config(llm={"enabled": False}, sources={"trends": False, "web": True})
    run = Run("content-source-coverage", tmp_path)
    run.manifest["input"] = cfg
    calls = []
    def send(provider, params):
        calls.append(params["query"])
        return {"results": [{"title": "Hello Kitty keychain", "url": "https://etsy.com/listing/keychain", "content": "Hello Kitty keychain"}]} if len(calls) == 1 else {"results": []}
    result = broad.discover(run, Client(run, cfg, send), cfg)
    assert len(calls) == 3
    assert "shirt" in calls[1] or "tee" in calls[1]
    assert "wrapping" in calls[2]
    assert [keyword["text"] for keyword in result["keywords"]] == ["Hello Kitty keychain"]
    assert result["summary"]["source_content_candidates"] == 1
    assert [row["source_candidates"] for row in result["summary"]["content_coverage"]] == [1, 0, 0]


def test_source_content_flows_through_exact_month_trends_matching_products_images_and_report(tmp_path):
    pages = [{"title": "Acrylic keychain featuring Hello Kitty", "content": "A keychain featuring Hello Kitty", "url": "https://etsy.com/listing/k"},
             {"title": "T-shirt with words Not a morning person", "content": "A shirt printed with the words Not a morning person", "url": "https://etsy.com/listing/s"},
             {"title": "woodland fox wrapping paper", "content": "woodland fox wrapping paper", "url": "https://etsy.com/listing/w"}]
    queries = {"Hello Kitty keychain", "Not a morning person shirt", "woodland fox wrapping paper"}
    calls, searched = [], []
    def send(provider, params):
        calls.append((provider, params))
        if provider == "tavily":
            return {"results": pages}
        if provider == "openrouter":
            payload = json.loads(params["messages"][1]["content"])
            if "pages" in payload:
                ids = {p["url"]: p["id"] for p in payload["pages"]}
                niche_ids = [n["id"] for n in payload["niches"]]
                return {"choices": [{"message": {"content": json.dumps({"candidates": [
                    {"keyword": "Hello Kitty keychain", "niche_id": niche_ids[0], "source_id": ids[pages[0]["url"]], "quote": pages[0]["content"],
                     "design": {"subject": "Hello Kitty", "product": "keychain", "kind": "character"}},
                    {"keyword": "Not a morning person shirt", "niche_id": niche_ids[1], "source_id": ids[pages[1]["url"]], "quote": pages[1]["content"],
                     "design": {"subject": "Not a morning person", "product": "shirt", "kind": "slogan"}}]})}}]}
            return {"choices": [{"message": {"content": json.dumps({"directions": [{"name": k["text"], "niche_id": k["niche_id"], "keyword_ids": [k["id"]], "representative_keyword_id": k["id"]} for k in payload["keywords"]]})}}]}
        assert provider == "serpapi"
        if params["engine"] == "google_trends":
            start, end = map(date.fromisoformat, params["date"].split())
            assert start.month == end.month == 11
            assert set(params["q"].split(",")) <= queries | {"gift basket"}
            points = []
            while start <= end:
                points.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())),
                    "values": [{"query": query, "extracted_value": 20 if query == "gift basket" else 60} for query in params["q"].split(",")]})
                start += timedelta(days=1)
            return {"interest_over_time": {"timeline_data": points}}
        assert params["engine"] == "amazon"
        searched.append(params["k"])
        asin = "B0" + hashlib.sha256(params["k"].encode()).hexdigest()[:8].upper()
        return {"organic_results": [{"asin": asin, "title": params["k"], "extracted_price": 15,
            "thumbnail": "https://m.media-amazon.com/images/fixture.jpg"},
            {"asin": "B012345678", "title": "Plain keychain and plain cotton shirt", "extracted_price": 5}]}

    run = execute(config(), run_id="content-workflow", root=tmp_path, transport=send, event=lambda _: None)
    data = run.load_dataset()
    assert run.manifest["status"] in {"complete", "partial"}
    assert set(searched) == queries
    assert len(data["products"]) == len(data["ideas"]) == 3
    assert {k["text"] for k in data["keywords"]} == queries
    assert all(d["measurement_query"] == d["search_query"] and d["qualifying_months"] == [11] for d in data["directions"])
    slogan = next(d for d in data["directions"] if d["keyword"].startswith("Not a"))
    assert slogan["source_design"]["subject"] == "Not a morning person"
    assert all(idea["sample_image_url"].endswith("fixture.jpg") for idea in data["ideas"])
    assert any("Nội dung mẫu: Not a morning person" in idea["sell_what"] for idea in data["ideas"])
    doc = Document()
    overview(doc, data, run.evidence)
    md, html = doc.render("Test", "Fixture")
    assert "Not a morning person" in md and "Hello Kitty" in md and "11 / 2025" in md
    assert "amazon.com/dp/" in html and "etsy.com/listing/s" in html
    assert any(row.get("design_match", {}).get("kind") == "slogan" for row in data["products"])


@pytest.mark.parametrize("value", ["unknown", [], {}])
def test_focus_is_validated(value):
    with pytest.raises(ValueError, match="discovery.focus"):
        config(discovery={"focus": value})
