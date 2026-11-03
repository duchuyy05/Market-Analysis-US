from copy import deepcopy

import pytest

from market_research.llm.plan import validate_plan


def payload(**overrides):
    return {"brief": "Meaningful year-end gifts for parents and partners", "chosen_niches": [],
            "as_of_date": "2026-10-29", "history_years": [2022, 2023, 2024, 2025], "target_year": 2026,
            "explicit_constraints": {"selling_months": None, "price_range": None,
                                     "preferences": [], "required_features": [], "excluded_features": [],
                                     "preparation_days": None}, **overrides}


def plan(**overrides):
    return {"category": "Year-end gifts", "niches": [{"name": "Warm gifts", "seeds": ["heated throw", "coffee mug"]}], **overrides}


def test_minimal_legacy_plan_defaults_optional_fields_without_generated_ids():
    result = validate_plan(plan(), payload())
    assert result["category"] == "Year-end gifts"
    assert result["selling_months"] is None
    assert result["required_features"] == result["preferences"] == result["assumptions"] == []
    assert "id" not in result["niches"][0]


def test_missing_category_requires_model_repair_unless_user_supplied_it():
    value = plan()
    value.pop("category")
    with pytest.raises(ValueError, match="category"):
        validate_plan(value, payload())
    assert validate_plan(value, payload(explicit_category="Chosen category"))["category"] == "Chosen category"


@pytest.mark.parametrize("changes", [
    {"category": None}, {"category": "  "}, {"category": []},
    {"niches": []}, {"niches": [{"name": " ", "seeds": ["mug"]}]},
    {"niches": [{"name": "Gifts", "seeds": []}]},
    {"niches": [{"name": "Gifts", "seeds": ["  "]}]},
    {"niches": [{"name": "Gifts", "seeds": ["caf\u00e9 mug"]}]},
    {"niches": [{"name": "Gifts", "seeds": ["x"*201]}]},
    {"niches": [{"name": "Gifts", "seeds": [123]}]},
    {"selling_months": [13]}, {"selling_months": []}, {"selling_months": [True]},
    {"price_range": [40, 10]}, {"price_range": [10, float("inf")]},
    {"required_features": {}}, {"excluded_features": [1]}, {"preferences": "cheap"},
    {"assumptions": {}}, {"assumptions": [None]},
    {"preparation_days": -1}, {"preparation_days": True},
    {"summary_vi": {"text": "wrong type"}},
])
def test_invalid_effective_plan_is_rejected_for_repair(changes):
    with pytest.raises(ValueError):
        validate_plan(plan(**changes), payload())


def test_explicit_constraints_override_invalid_model_values_before_validation():
    result = validate_plan(plan(category=None, selling_months=[13], price_range=[40, 10],
                                required_features={}, excluded_features={}, preferences={}, preparation_days=-2),
        payload(explicit_category="Chosen gifts", explicit_constraints={"selling_months": [12, 11],
            "price_range": [10, 40], "required_features": ["washable"], "excluded_features": ["glass"],
            "preferences": ["lightweight"], "preparation_days": 0}))
    assert result["category"] == "Chosen gifts"
    assert result["selling_months"] == [11, 12]
    assert result["price_range"] == [10, 40]
    assert result["required_features"] == ["washable"]
    assert result["excluded_features"] == ["glass"]
    assert result["preferences"] == ["lightweight"]
    assert result["preparation_days"] == 0


def test_unspecified_explicit_defaults_do_not_erase_inferred_fields():
    result = validate_plan(plan(selling_months=[11, 12], preferences=["compact"], required_features=["washable"]), payload())
    assert result["selling_months"] == [11, 12]
    assert result["preferences"] == ["compact"]
    assert result["required_features"] == ["washable"]


def test_chosen_niches_preserve_user_scope_and_explicit_seeds():
    result = validate_plan(plan(niches=[{"name": "Warm gifts", "seeds": ["heated throw"]},
                                       {"name": "Photo gifts", "seeds": ["photo frame"]}]),
                           payload(chosen_niches=[{"name": "Photo gifts", "seeds": ["photo ornament"]}]))
    assert len(result["niches"]) == 1
    assert result["niches"][0]["name"] == "Photo gifts"
    assert result["niches"][0]["seeds"] == ["photo ornament"]


def test_chosen_niche_without_seeds_uses_model_seed_but_preserves_name():
    result = validate_plan(plan(), payload(chosen_niches=[{"name": "For parents", "seeds": []}]))
    assert result["niches"][0]["name"] == "For parents"
    assert result["niches"][0]["seeds"] == ["heated throw", "coffee mug"]


def test_safe_typography_and_whitespace_are_normalized_without_translation():
    value = plan(niches=[{"name": " Gifts ", "seeds": [" hand\u2011warmer ", "mother\u2019s day mug", "coffee   mug", "coffee mug"]}])
    result = validate_plan(value, payload())
    assert result["niches"][0]["seeds"] == ["hand-warmer", "mother's day mug", "coffee mug"]
    assert result["niches"][0]["name"] == "Gifts"


def test_plan_validation_does_not_mutate_model_or_payload():
    value, inputs = plan(selling_months=[12, 11]), payload()
    before_value, before_inputs = deepcopy(value), deepcopy(inputs)
    validate_plan(value, inputs)
    assert value == before_value
    assert inputs == before_inputs
