"""Company research compares physical models, not only artwork or family volume."""
import json

import pytest

from market_research.config import validate_config
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import broad, web_discovery
from market_research.workflow.keyword_expansion import product_key, rejection
from market_research.workflow.trend_queries import candidate_level, measurement_query, product_context, research_focus


BRIEF = ("Tìm mẫu sản phẩm hot cho công ty theo tháng đã chọn: móc khóa, lịch, đồ trang trí, giấy gói, quần áo. "
         "Ví dụ áo in hình ca sĩ chỉ là ví dụ. Công ty có thể in ấn, khắc, thuê gia công và nhập phôi decor.")
FAMILIES = ["keychain", "calendar", "decor", "t shirt", "wrapping paper"]
MODELS = ["star shaped acrylic keychain", "spiral bound desk calendar", "sublimation photo slate", "boxy cropped t shirt", "woodland fox wrapping paper"]


def cfg(**changes):
    return validate_config({"brief": BRIEF, "category": "Manufacturable product models", "selling_months": [7],
        "as_of_date": "2026-10-30", "history_years": [2023, 2024, 2025],
        "trends": {"history_scope": "seasonal", "history_months": [7], "analysis_year": 2025},
        "niches": [{"id": "N"+str(index), "name": family, "seeds": [family]} for index, family in enumerate(FAMILIES)],
        "llm": {"enabled": True}, "sources": {"trends": False, "web": False},
        "limits": {"candidate_keywords": 5, "llm_requests": 1, "retry_attempts": 0}, **changes})


def test_incidental_artist_example_does_not_close_other_company_families():
    config = cfg()
    focus = research_focus(config)
    assert focus["level"] == "product_models" and focus["multiple_product_families"]
    assert focus["incidental_examples"] and len(focus["selected_categories"]) > 1
    assert product_context("keychain", config) and product_context("calendar", config)
    assert all(not product_context(model, config) for model in MODELS)


def test_vietnamese_mixed_families_with_one_pattern_word_stay_model_scope():
    focus = research_focus({"brief": "Tìm mẫu móc khóa, lịch, giấy gói họa tiết, quần áo trong tháng 7"})
    assert focus["level"] == "product_models" and focus["multiple_product_families"]


def test_company_constraints_after_multiple_examples_are_still_main_scope():
    config = cfg(brief="Ví dụ áo ca sĩ, ví dụ họa tiết giấy gói chỉ để minh họa. Công ty in ấn, khắc, thuê gia công, nhập phôi decor và cần tìm các nhóm mẫu phù hợp.")
    focus = research_focus(config)
    assert focus["level"] == "product_models" and focus["multiple_product_families"]
    assert not product_context("blank acrylic ornament", config)


def test_explicit_motif_limit_wins_over_company_capability_background():
    config = cfg(brief="Công ty có thể in ấn, khắc, gia công và nhập phôi decor. Lần này chỉ tìm hình ca sĩ nào trên áo trong tháng 7.")
    assert research_focus(config)["level"] == "exact_motif"
    assert research_focus(config)["explicit_limit"]
    assert product_context("graphic t shirt", config)
    assert not product_context("Sabrina Carpenter t shirt", config)


@pytest.mark.parametrize("model", [
    "heart shaped keychain", "rotating acrylic keychain", "double sided keychain", "engraved metal keychain",
    "monogrammed leather keychain", "spiral bound desk calendar", "flip desk calendar", "tent desk calendar",
    "minimalist grid wall calendar", "blank acrylic ornament", "matte ceramic ornament", "sublimation photo slate",
    "acrylic stand", "wooden toy", "oversized boxy t shirt", "cropped t shirt", "satin finish gift box",
    "floral wrapping paper", "kraft wrapping paper", "plain blank pillow cover",
    "photo slate", "shadow box", "embroidered patch", "heat press coaster blanks",
])
def test_physical_model_dimensions_do_not_require_a_named_character(model):
    config = cfg()
    assert not product_context(model, config)
    assert candidate_level(model, config) in {"product_model", "unclassified_product"}
    assert measurement_query(model) == model


@pytest.mark.parametrize("parent", ["keychain", "calendar", "shirt", "decor", "t shirt", "wrapping paper"])
def test_bare_parent_series_stays_context_in_broad_model_research(parent):
    assert product_context(parent, cfg())


def test_a_real_family_question_can_compare_family_terms():
    config = {"brief": "Which product categories should a printing company research across selected categories?"}
    assert research_focus(config)["level"] == "product_families"
    assert not product_context("calendar", config) and not product_context("keychain", config)


def test_small_pool_expands_balanced_physical_models_without_artist_only_scope(tmp_path):
    config = cfg()
    run = Run("company-models", tmp_path)
    run.manifest["input"] = config
    calls = []
    def send(provider, params):
        assert provider == "openrouter"
        payload = json.loads(params["messages"][1]["content"])
        calls.append(payload)
        assert payload["research_focus"]["level"] == "product_models"
        assert payload["research_period"]["months"] == [7] and payload["research_period"]["analysis_year"] == 2025
        assert payload["existing_keywords"] == []
        return {"choices": [{"message": {"content": json.dumps({"candidates": [
            {"keyword": model, "niche_id": "N"+str(index), "reason": "Giả thuyết mẫu vật lý có thể gia công hoặc nhập phôi, cần đo đúng tháng"}
            for index, model in enumerate(MODELS)]})}}]}
    result = broad.discover(run, Client(run, config, send), config)
    assert len(calls) == len(run.manifest["usage"]) == 1
    assert {keyword["text"] for keyword in result["keywords"]} == set(MODELS)
    assert len({keyword["niche_id"] for keyword in result["keywords"]}) == 5
    assert result["summary"]["unique_product_models"] == 5
    assert {row["text"] for row in result["product_context_keywords"]} == set(FAMILIES)
    assert all(keyword["evidence_state"] == "hypothesis" and not keyword["evidence_ids"] for keyword in result["keywords"])
    assert config["limits"]["llm_requests"] == 1 and config["limits"]["serpapi_requests"] == 20


def test_existing_web_budget_rotates_family_queries_and_does_not_force_artist_terms(tmp_path):
    config = cfg(llm={"enabled": False}, sources={"web": True, "trends": False},
        discovery={"sites": ["tiktok", "etsy", "pinterest"]}, limits={"tavily_requests": 3})
    run = Run("company-model-web", tmp_path)
    queries = []
    def send(provider, params):
        assert provider == "tavily"
        queries.append(params["query"])
        return {"results": []}
    web_discovery.harvest(run, Client(run, config, send), config, {n["id"]: n for n in config["niches"]}, lambda *_: False)
    assert len(queries) == 3
    assert all("July" in query and "2025" in query for query in queries)
    assert all("artist" not in query and "singer" not in query and "personalized" not in query for query in queries)
    assert all(any(family in query for query in queries) for family in FAMILIES)


def test_finish_process_binding_and_shape_are_distinct_models_not_dedupe_padding():
    assert product_key("engraved metal keychain") != product_key("metal keychain")
    assert product_key("monogrammed metal keychain") != product_key("metal keychain")
    assert product_key("spiral bound calendar") != product_key("flip calendar")
    assert product_key("round acrylic keychain") != product_key("star acrylic keychain")
    assert product_key("personalized round acrylic keychain") == product_key("round acrylic keychain")


@pytest.mark.parametrize("keyword, reason", [
    ("viral star keychain", "Giả thuyết cần kiểm chứng"),
    ("star shaped keychain", "This is currently viral and popular in July"),
    ("star shaped keychain", "Mẫu đang bán chạy trong tháng 7"),
    ("star shaped keychain", "Sold 5000 orders last month"),
])
def test_llm_model_proposal_cannot_supply_its_own_popularity_evidence(keyword, reason):
    assert rejection({"keyword": keyword, "reason": reason, "niche_id": "N0"}, {"N0": {}}, cfg()) is not None
