"""Selling-window selection respects historical scope and comparable anchors."""
from copy import deepcopy

from market_research.analysis.monthly_priority import priority


def config():
    return {"selling_months": [11, 12]}


def discovery():
    return {"keywords": [{"id": "A", "text": "christmas gift"}, {"id": "B", "text": "summer gift"}, {"id": "C", "text": "unmeasured gift"}]}


def screening():
    return {"status": "available", "method": "recent", "note": "Recent 28 days.", "rows": [
        {"keyword_id": "A", "keyword": "christmas gift", "measurement_query": "christmas gift", "rank": 2, "score": 50, "status": "available", "relative_interest": .5, "growth_pct": -20, "evidence_ids": ["E-recent-A"]},
        {"keyword_id": "B", "keyword": "summer gift", "measurement_query": "summer gift", "rank": 1, "score": 90, "status": "available", "relative_interest": .9, "growth_pct": 100, "evidence_ids": []},
        {"keyword_id": "C", "keyword": "unmeasured gift", "measurement_query": "unmeasured gift", "rank": 3, "score": 5, "status": "available", "relative_interest": .05, "growth_pct": 1, "evidence_ids": []}]}


def monthly():
    return {"rows": [{"measurement_query": query, "month": month, "status": "available", "demand_metric_kind": "query_to_anchor_ratio",
        "demand_metric": demand, "seasonal_score": fit, "usable_years": [2023, 2024, 2025], "demand_years": [2023, 2024, 2025],
        "comparison_group": "shared-anchor", "comparison_label": "gift basket", "evidence_ids": ["E-history-" + query]}
        for query, demand, fit in [("christmas gift", 2, 100), ("summer gift", .2, 10)] for month in [11, 12]]}


def test_selling_month_history_can_outweigh_recent_interest_without_rewriting_recent_facts():
    original = screening()
    saved = deepcopy(original)
    result = priority(config(), discovery(), original, monthly())
    christmas, summer, unknown = result["rows"]
    assert christmas["rank"] == 1 and summer["rank"] == 2
    assert christmas["score"] == 100 and summer["score"] == 0
    assert christmas["recent_rank"] == 2 and christmas["recent_score"] == 50
    assert christmas["relative_interest"] == .5 and christmas["growth_pct"] == -20
    assert christmas["monthly_demand_ratio"] == 2 and christmas["selection_months"] == [11, 12]
    assert "E-recent-A" in christmas["evidence_ids"] and "E-history-christmas gift" in christmas["evidence_ids"]
    assert unknown["rank"] is None and unknown["status"] == "unavailable"
    assert original == saved


def test_one_missing_selling_month_does_not_inherit_verified_historical_rank():
    ranks = monthly()
    ranks["rows"] = [r for r in ranks["rows"] if not (r["measurement_query"] == "summer gift" and r["month"] == 12)]
    result = priority(config(), discovery(), screening(), ranks)
    assert result["monthly_measured_keywords"] == 1
    assert result["rows"][1]["rank"] is None


def test_raw_batch_indices_cannot_be_used_for_global_product_selection():
    ranks = monthly()
    for row in ranks["rows"]:
        row["demand_metric_kind"] = "same_batch_index"
    result = priority(config(), discovery(), screening(), ranks)
    assert result["method"] == "recent_screening_fallback_v1"
    assert result["selection_basis"] == "recent_interest_fallback"
    assert result["monthly_measured_keywords"] == 0
    assert result["rows"][0]["rank"] == 2
    assert all(r["monthly_demand_ratio"] is None for r in result["rows"])


def test_incompatible_anchor_groups_are_not_mixed():
    ranks = monthly()
    for row in ranks["rows"]:
        if row["measurement_query"] == "summer gift":
            row["comparison_group"] = "other-window"
    result = priority(config(), discovery(), screening(), ranks)
    assert result["monthly_measured_keywords"] == 1
    assert result["excluded_comparison_groups"] == 1
    assert sum(r["rank"] is not None for r in result["rows"]) == 1


def test_low_anchor_coverage_or_one_cycle_cannot_claim_historical_priority():
    ranks = monthly()
    for row in ranks["rows"]:
        row["demand_years"] = [2025]
    result = priority(config(), discovery(), screening(), ranks)
    assert result["method"] == "recent_screening_fallback_v1"
    assert "không phải xác minh nhu cầu" in result["note"]


def test_alias_keyword_context_uses_the_actual_measurement_query():
    pool = {"keywords": [{"id": "A", "text": "custom christmas gift for parents"}]}
    measured = {**screening(), "rows": [screening()["rows"][0]]}
    result = priority(config(), pool, measured, monthly())
    assert result["rows"][0]["monthly_demand_ratio"] == 2
    assert result["rows"][0]["selection_basis"] == "historical_selling_months"


def test_selling_months_need_two_common_years_not_disjoint_anchor_samples():
    ranks = monthly()
    for row in ranks["rows"]:
        row["demand_years"] = [2023, 2024] if row["month"] == 11 else [2024, 2025]
    result = priority(config(), discovery(), screening(), ranks)
    assert result["method"] == "recent_screening_fallback_v1"
