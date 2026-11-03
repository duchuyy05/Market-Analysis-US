"""Regressions from the sparse real run: source phrases, not synthetic catalogs."""
from copy import deepcopy
import json

import pytest

from market_research.config import validate_config
from market_research.llm.client import complete
from market_research.llm.plan import validate_plan
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import broad
from market_research.workflow.trend_queries import DISCOVERY_QUERY_VERSION, measurement_query, search_phrase_issue
from market_research.workflow.web_discovery import literal_model_phrases, poor_page


def config(**changes):
    return validate_config({"brief": "Tìm mẫu lịch và ốp lưng nhỏ gọn cho dịp cuối năm", "category": "Compact gift models",
        "as_of_date": "2026-10-30", "selling_months": [11], "history_years": [2023, 2024, 2025],
        "trends": {"history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        "niches": [{"id": "CAL", "name": "Calendar formats", "seeds": ["spiral desk calendar"]},
                   {"id": "PHONE", "name": "Phone cases", "seeds": ["silicone phone case"]}],
        "sources": {"trends": False, "web": True}, "discovery": {"sites": ["etsy"]},
        "limits": {"candidate_keywords": 4, "llm_requests": 1, "tavily_requests": 2, "retry_attempts": 0}, **changes})


@pytest.mark.parametrize("phrase", ["snowflake keychain", "tassel keychain", "photo keychain", "wallet phone case",
    "folding phone stand", "spiral notebook", "perpetual calendar", "Taylor Swift t shirt", "monogrammed leather keychain"])
def test_natural_model_names_keep_their_identifying_words(phrase):
    assert search_phrase_issue(phrase) is None
    assert measurement_query(phrase) == phrase


@pytest.mark.parametrize("phrase", ["acrylic keychain snowflake shape", "silicone phone case Christmas pattern",
    "gift box small size custom printed logo", "mini desk calendar 2026 monthly layout",
    "a very long made up catalog description of a small product with printed logo"])
def test_generated_catalog_specifications_require_repair_before_measurement(phrase):
    assert search_phrase_issue(phrase)
    assert measurement_query(phrase) == phrase  # No silent shortening or borrowed verification.


def test_literal_fallback_keeps_short_attested_model_phrases_and_source_quote():
    cfg = config()
    page = {"id": "W", "title": "Dodecahedron Calendar", "excerpt": "Discover unique dodecahedron calendars, perfect for organizers."}
    assert literal_model_phrases(page, cfg) == [{"keyword": "Dodecahedron Calendar", "quote": "Dodecahedron Calendar", "source_id": "W"}]
    phone = {"id": "P", "title": "Sublimation Phone Cases for Samsung Galaxy Mobile", "excerpt": "UV Print custom protective covers."}
    result = literal_model_phrases(phone, cfg)
    assert result[0]["keyword"] == "Sublimation Phone Cases"
    assert all(row["keyword"] != "UV Print" for row in result)


def test_literal_fallback_is_not_digital_service_generic_or_unrelated_evidence():
    cfg = config()
    assert literal_model_phrases({"title": "Family Calendar DXF", "excerpt": "Wooden calendar digital download"}, cfg) == []
    assert literal_model_phrases({"title": "Phone Case", "excerpt": "UV Print. 3in x 4in Card"}, cfg) == []
    assert literal_model_phrases({"title": "Dodecahedron Calendar"}, config(business={"profile": "custom_manufacturing", "categories": ["apparel"]})) == []
    singer = literal_model_phrases({"title": "Sabrina Carpenter t shirt"}, config(brief="Which singer print should we compare on shirts?"))
    assert singer[0]["keyword"] == singer[0]["quote"] == "Sabrina Carpenter t shirt"
    assert poor_page({"url": "https://corporate.walmart.com/policies", "title": "Policies for calendar and phone case products"}, {"calendar", "case"})


def test_bad_model_extraction_does_not_waste_attested_models_or_extra_web_requests(tmp_path):
    cfg = config()
    run = Run("literal-fallback", tmp_path)
    run.manifest["input"] = cfg
    calls = []
    def send(provider, params):
        calls.append((provider, params))
        if provider == "tavily":
            return {"results": [
                {"title": "Dodecahedron Calendar", "url": "https://etsy.com/listing/calendar", "content": "Discover unique dodecahedron calendars, perfect for organizers."},
                {"title": "Sublimation Phone Cases for Samsung Galaxy Mobile", "url": "https://etsy.com/listing/phone", "content": "Blank phone cases with dye sublimation inserts."}]}
        payload = json.loads(params["messages"][1]["content"])
        page = payload["pages"][0]
        return {"choices": [{"message": {"content": json.dumps({"candidates": [
            {"keyword": "mini desk calendar 2026 monthly layout", "quote": "Dodecahedron Calendar", "niche_id": "CAL", "source_id": page["id"]}]})}}]}
    result = broad.discover(run, Client(run, cfg, send), cfg)
    observed = {row["text"]: row for row in result["keywords"] if row["origin"] == "public_web"}
    assert set(observed) == {"Dodecahedron Calendar", "Sublimation Phone Cases"}
    assert observed["Dodecahedron Calendar"]["niche_id"] == "CAL"
    assert observed["Sublimation Phone Cases"]["niche_id"] == "PHONE"
    assert all(row["evidence_ids"] and row["evidence_state"] == "source_observed" for row in observed.values())
    assert sum(provider == "tavily" for provider, _ in calls) == 1
    assert sum(provider == "openrouter" for provider, _ in calls) == 1
    assert any("nguyên văn" in item["reason"] for item in result["exclusions"])
    assert result["web_context"][0]["literal_model_phrases"][0]["query_version"] == DISCOVERY_QUERY_VERSION
    assert all("rank" not in row for row in observed.values())  # Mention is not a hot-model measurement.


def valid_plan():
    return {"category": "Small gift models", "niches": [{"name": "Calendar formats", "seeds": ["perpetual calendar"]}]}


def payload(**changes):
    return {"brief": "Small year-end gifts", "business": {"profile": "general", "categories": []},
        "validation_context": {"as_of_date": "2026-10-30", "history_years": [2023, 2024, 2025], "target_year": 2026}, **changes}


def test_embedded_json_property_in_generated_niche_is_invalid_not_a_complete_plan():
    malformed = valid_plan()
    malformed["niches"][0]["tote bag canvas holiday design small size','socks with seasonal pattern']},{"] = "Apparel"
    with pytest.raises(ValueError, match="mảnh JSON"):
        validate_plan(malformed, payload())


def test_generated_catalog_seed_enters_repair_but_explicit_user_metadata_is_preserved():
    malformed = valid_plan()
    malformed["niches"][0]["seeds"] = ["acrylic keychain snowflake shape"]
    with pytest.raises(ValueError, match="catalog"):
        validate_plan(malformed, payload())
    original = {"name": "My exact products", "seeds": ["acrylic keychain snowflake shape"], "team_metadata": {"owner": "design"}}
    result = validate_plan(valid_plan(), payload(chosen_niches=[original]))
    assert result["niches"] == [original]
    echoed = {"category": "Small gifts", "niches": [deepcopy(original)]}
    assert validate_plan(echoed, payload(chosen_niches=[original]))["niches"] == [original]


def test_malformed_generated_niche_uses_the_existing_bounded_llm_repair(tmp_path):
    cfg = config(business={"profile": "general", "categories": []}, limits={"llm_requests": 3, "retry_attempts": 0})
    run = Run("repair-niche-fragment", tmp_path)
    requests = []
    def send(provider, params):
        assert provider == "openrouter"
        requests.append(params)
        result = valid_plan()
        if len(requests) == 1:
            result["niches"][0]["broken']},{\"name\":\"Apparel\""] = "lost seeds"
        return {"choices": [{"message": {"content": json.dumps(result)}}]}
    result = complete(Client(run, cfg, send), "understand", payload())
    assert result["niches"][0]["seeds"] == ["perpetual calendar"]
    assert len(requests) == 2 and len(run.manifest["usage"]) == 2
    assert any(item.get("validation_error") for item in [json.loads(path.read_text(encoding="utf-8")) for path in (run.path / "raw/openrouter").glob("*.json")])
