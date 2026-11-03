"""Observed sample evidence stays distinct from recipient and design hypotheses."""
import pytest

from market_research.analysis.products import candidate, enrich_product
from market_research.workflow.ideas import generate


class EvidenceRun:
    def __init__(self):
        self.evidence = {}

    def add_evidence(self, kind, url, retrieved_at, raw_file=None, excerpt=None, **fields):
        key = "E" + str(len(self.evidence) + 1)
        self.evidence[key] = {"kind": kind, "url": url, "excerpt": excerpt, **fields}
        return key


def enrich(response):
    run = EvidenceRun()
    envelope = {"retrieved_at": "2026-10-30T00:00:00Z", "raw_file": "raw/fixture.json"}
    sample = candidate({"title": "Coffee mug", "asin": "B012345678"}, "amazon", {"id": "D"}, envelope, run)
    updated, reviews = enrich_product(sample, {**envelope, "response": {"product_results": {"title": "Coffee mug"}, **response}}, run, 20, "2026-10-30")
    return updated, reviews, run


@pytest.mark.parametrize("specifications", [
    {"Material": "Ceramic", "Special Feature": "Handle"},
    [{"name": "Material", "value": "Ceramic"}, {"label": "Special Feature", "value": "Handle"}],
    "Material: Ceramic\nSpecial Feature: Handle",
])
def test_item_specifications_supports_labelled_provider_variations(specifications):
    sample, reviews, run = enrich({"item_specifications": specifications})
    material = sample["attributes"]["material"]
    assert material["value"] == "Ceramic" and material["status"] == "observed"
    assert material["source_values"] == [{"source_field": "item_specifications.material", "value": "Ceramic"}]
    assert material["evidence_ids"] and all(e in run.evidence for e in material["evidence_ids"])
    assert sample["attributes"]["special_feature"]["value"] == "Handle"
    assert reviews == []  # No review is inferred from specification text.


def test_unlabelled_spec_prose_does_not_become_an_observed_attribute():
    sample, _, _ = enrich({"item_specifications": "A lovely ceramic coffee mug with a blue handle"})
    assert sample["attributes"]["material"]["status"] == "missing"
    assert sample["attributes"]["material"]["value"] is None
    assert sample["suitability_status"] == "preliminary_keyword_match"


def test_labelled_manufacturing_model_features_keep_source_values_and_evidence():
    sample, _, run = enrich({"item_specifications": {"Shape": "Heart", "Binding Type": "Spiral", "Finish Type": "Glossy",
        "Calendar Format": "Desk", "Page Layout": "Month to view", "Printing Method": "Sublimation"}})
    for field, expected in {"shape": "Heart", "binding": "Spiral", "finish": "Glossy", "format": "Desk", "layout": "Month to view", "print_method": "Sublimation"}.items():
        attribute = sample["attributes"][field]
        assert attribute["value"] == expected and attribute["status"] == "observed"
        assert attribute["source_values"][0]["source_field"].startswith("item_specifications.")
        assert all(e in run.evidence for e in attribute["evidence_ids"])


def test_model_features_are_presented_as_observed_attributes_without_inventing_unlabelled_ones():
    shape = {"value": "Heart", "status": "observed", "evidence_ids": ["E-shape"], "source_values": [{"source_field": "item_specifications.shape", "value": "Heart"}]}
    binding = {"value": "Spiral", "status": "observed", "evidence_ids": ["E-binding"], "source_values": [{"source_field": "item_specifications.binding", "value": "Spiral"}]}
    result = idea([product("P1", attributes={"shape": shape, "binding": binding, "finish": {"value": None, "status": "missing"}})])
    assert result["market_evidence"]["observed_model_features"] == {"shape": shape, "binding": binding}
    assert "shape: Heart" in result["observed_specification"] and "binding: Spiral" in result["observed_specification"]
    assert "finish" not in result["observed_specification"]


def test_conflicting_attribute_values_are_preserved_instead_of_silently_overwritten():
    sample, _, _ = enrich({"product_details": {"material_type": "Metal"}, "item_specifications": {"material": "Plastic"}})
    material = sample["attributes"]["material"]
    assert material["status"] == "conflicting" and material["value"] is None
    assert [v["value"] for v in material["source_values"]] == ["Metal", "Plastic"]
    assert sample["attributes"]["color"]["status"] == "missing"


def product(pid, **changes):
    return {"product_id": pid, "title": "Coffee mug for women", "direction_ids": ["D"], "description": "",
        "url": "https://www.amazon.com/dp/" + pid, "purchase_lower_bound": 1000, "purchase_badge": "1K+ bought in past month",
        "price": 12, "currency": "USD", "rating": 4.5, "review_count": 200, "observed_at": "2026-10-30T00:00:00Z",
        "detail_status": "available", "evidence_ids": ["E-" + pid], "attributes": {}, **changes}


def idea(products, reviews=None, histories=None, checks=None):
    directions = [{"id": "D", "keyword_id": "K", "niche_id": "N", "name": "Coffee mug", "customer_hypothesis": "Sinh viên mua quà cho người yêu hoặc bố mẹ"}]
    assessed = {"directions": [{"direction_id": "D", "status": "watchlist"}], "product_checks": checks or [
        {"product_id": p["product_id"], "status": "eligible", "pending": []} for p in products]}
    return generate({"selling_months": [11, 12]}, directions, {"products": products, "reviews": reviews or []}, assessed, histories or [])[0]


def test_recipient_hypothesis_is_preserved_and_listing_audience_is_separate():
    result = idea([product("P1")])
    assert result["customer"] == "Sinh viên mua quà cho người yêu hoặc bố mẹ"
    assert result["customer_status"] == "hypothesis_from_brief_not_demographic_research"
    assert result["listing_audience"] == "phụ nữ"
    assert result["listing_audience_status"] == "seller_stated_not_verified_buyers"


def test_alternative_samples_and_prices_have_exact_same_direction_evidence():
    products = [product("P1"), product("P2", price=8, purchase_lower_bound=100),
                product("P3", price=20, direction_ids=["OTHER"]), product("P4", price=100)]
    checks = [{"product_id": p["product_id"], "status": "excluded" if p["product_id"] == "P4" else "eligible", "pending": []} for p in products]
    result = idea(products, checks=checks)
    assert result["sample_product_id"] == "P1"
    assert [p["product_id"] for p in result["alternatives"]] == ["P2"]
    assert result["alternatives"][0]["price"] == 8
    assert result["market_evidence"]["observed_usd_price_range"] == [8, 12]
    assert result["market_evidence"]["direction_sample_count"] == 2
    assert "E-P2" in result["evidence_ids"] and "E-P3" not in result["evidence_ids"]
    assert result["differentiation_evidence"]["status"] == "not_established"


def test_other_product_review_counts_do_not_become_the_selected_sample_review():
    review = {"id": "R2", "product_id": "P2", "text": "The package arrived damaged", "evidence_ids": ["E-review2"]}
    result = idea([product("P1"), product("P2", purchase_lower_bound=100)], [review])
    evidence = result["market_evidence"]
    assert evidence["listing_review_count"] == 200
    assert evidence["sample_reviews_collected"] == 0
    assert evidence["direction_reviews_collected"] == 1 and evidence["direction_products_with_reviews"] == 1
    assert result["review_quote"] is None and result["improvement"] is None
    assert result["differentiation_evidence"]["evidence_ids"] == []
    assert any("đúng mẫu" in gap for gap in result["evidence_gaps"])


def test_review_grounded_change_is_a_hypothesis_and_keeps_observed_history_separate():
    review = {"id": "R1", "product_id": "P1", "text": "The package arrived damaged, but the mug itself looked nice.", "evidence_ids": ["E-review1"]}
    history = {"direction_id": "D", "evidence_ids": ["E-history"], "usable_years": [2023, 2024, 2025], "monthly": [{"year": 2025}],
        "growth_pct": 8, "validation": {"folds": [{"test_year": 2025}]}, "selling_window_fit_pct": 80,
        "forecast": [{"year": 2026, "month": 11, "prediction": 15}, {"year": 2026, "month": 1, "prediction": 10}],
        "peak_months": [{"year": 2025, "month": 12}]}
    result = idea([product("P1")], [review], [history])
    assert result["differentiation_evidence"]["status"] == "review_grounded_hypothesis"
    assert "arrived damaged" in result["differentiation_evidence"]["observed_issue"]
    assert result["differentiation_evidence"]["evidence_ids"] == ["E-review1"]
    assert result["market_evidence"]["backtest_years"] == [2025]
    assert result["market_evidence"]["selling_month_forecasts"] == [{"year": 2026, "month": 11, "prediction": 15, "historical_min": None, "historical_max": None}]
    assert result["market_evidence"]["sample_reviews_collected"] == 1
    assert "E-history" in result["evidence_ids"]
    assert result["status"] == "watchlist"  # Richer presentation never upgrades the opportunity rubric.
