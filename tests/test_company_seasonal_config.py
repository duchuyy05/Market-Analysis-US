"""Reject contradictory collection scopes before any source request."""
import pytest

from market_research.config import validate_config
from market_research.workflow.planning import seasonal_windows, trends_plan


def base(**changes):
    return validate_config({"brief": "Printed Christmas gifts", "as_of_date": "2026-10-30", **changes})


def test_new_live_defaults_to_company_but_offline_replay_stays_general():
    assert base()["business"]["profile"] == "custom_manufacturing"
    assert len(base()["business"]["categories"]) == 7
    assert base(mode="offline")["business"]["profile"] == "general"


def test_seasonal_requires_its_monthly_branch_and_canonicalizes_months():
    value = base(trends={"history_scope": "seasonal", "history_months": [12, 10, 11, 10], "monthly_rankings": False})
    assert value["trends"]["monthly_rankings"] is True
    assert value["trends"]["history_months"] == [10, 11, 12]


def test_trends_validation_identifies_wrong_shape_and_unsupported_fields():
    with pytest.raises(ValueError, match="trends phải là một object"):
        base(trends=[10, 11, 12])
    with pytest.raises(ValueError, match="trường không hỗ trợ: end_date, start_date"):
        base(trends={"start_date": "2023-10-01", "end_date": "2023-12-31"})


def test_nonconsecutive_years_and_months_create_only_selected_source_windows():
    value = base(history_years=[2021, 2023, 2025],
                 trends={"history_scope": "seasonal", "history_months": [10, 12]})
    windows = seasonal_windows(value)
    assert windows == [
        {"year": year, "months": [month], "start": f"{year}-{month:02d}-01", "end": f"{year}-{month:02d}-31"}
        for year in [2021, 2023, 2025] for month in [10, 12]
    ]
    assert len(windows) == 6


@pytest.mark.parametrize("changes", [
    {"business": {"profile": []}}, {"business": {"profile": "custom_manufacturing", "categories": []}},
    {"business": {"categories": ["pharmaceuticals"]}}, {"business": True},
    {"trends": {"history_scope": [], "history_months": [10]}},
    {"trends": {"history_scope": "seasonal", "history_months": [0, 13]}},
    {"trends": {"history_scope": "seasonal"}, "selling_months": [1, 2]},
    {"trends": {"history_scope": "seasonal"}, "comparison_periods": [{"start": "2023-01", "end": "2023-12"}]},
    {"trends": {"history_scope": "seasonal"}, "comparison_periods": [{"start": "2021-10", "end": "2021-12"}]},
    {"mode": "offline", "trends": {"history_scope": "seasonal"}},
])
def test_invalid_business_or_collection_rejected_before_sources(changes):
    with pytest.raises(ValueError):
        base(**changes)


def test_economy_plan_counts_design_screening_and_reuses_overlapping_history():
    value = base(trends={"history_scope": "seasonal"}, limits={"candidate_keywords": 64, "monthly_keywords": 10, "top_keywords": 5,
        "serpapi_requests": 20, "trends_serpapi_requests": 11, "serpapi_product_reserve": 8})
    plan = trends_plan(value)
    assert plan["history_estimate"] == 9 and plan["screening_estimate"] == 16
    assert plan["shared_history_estimate"] == 3 and plan["paid_estimate"] == 22
    assert plan["history_keywords"] == 10 and plan["history_reserve"] == 9
