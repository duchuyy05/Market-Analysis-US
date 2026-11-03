"""Monthly ranks honor scale, missing cycles, ties and target-year separation."""
from copy import deepcopy

from market_research.analysis.keyword_monthly import build


def config():
    return {"history_years": [2023, 2024, 2025], "target_year": 2026, "selling_months": [11, 12], "market": "US", "as_of_date": "2026-10-30"}


def months(values, years=(2023, 2024, 2025)):
    return [{"year": y, "month": m, "value": values[m - 1], "status": "complete", "positive_points": 4} for y in years for m in range(1, 13)]


def keyword(kid, query, niche="N"):
    return {"id": kid, "text": query, "niche_id": niche, "measurement_query": query}


def history(kid, query, values, *, queries=None, years=(2023, 2024, 2025)):
    return {"keyword_id": kid, "measurement_query": query, "status": "available", "monthly": months(values, years),
            "evidence_ids": ["E-" + kid], "normalization_context": {"scale": "shared_0_100", "queries": queries or [query]}}


def row(result, query, month):
    return next(r for r in result["rows"] if r["measurement_query"] == query and r["month"] == month)


def test_all_twelve_months_rank_seasonality_not_highest_raw_index():
    winter = [10] * 10 + [100, 80]
    steady = [90] * 12
    result = build(config(), [keyword("W", "winter gift"), keyword("S", "steady gift")],
                   [history("W", "winter gift", winter), history("S", "steady gift", steady)])
    assert [m["month"] for m in result["months"]] == list(range(1, 13))
    assert row(result, "winter gift", 11)["seasonal_score"] == 100
    assert row(result, "winter gift", 1)["seasonality_rank"] == 2
    assert row(result, "steady gift", 1)["seasonality_rank"] == 1
    assert all(r["demand_rank"] is None for r in result["rows"])  # each is a separate query scale


def test_different_batches_do_not_become_one_global_demand_rank():
    keywords = [keyword(k, q) for k, q in [("A", "gift a"), ("B", "gift b"), ("C", "gift c"), ("D", "gift d")]]
    histories = [history("A", "gift a", [20] * 12, queries=["gift a", "gift b"]),
                 history("B", "gift b", [10] * 12, queries=["gift a", "gift b"]),
                 history("C", "gift c", [90] * 12, queries=["gift c", "gift d"]),
                 history("D", "gift d", [30] * 12, queries=["gift c", "gift d"])]
    result = build(config(), keywords, histories)
    assert row(result, "gift a", 11)["demand_rank"] == row(result, "gift c", 11)["demand_rank"] == 1
    assert row(result, "gift b", 11)["demand_rank"] == row(result, "gift d", 11)["demand_rank"] == 2
    assert row(result, "gift a", 11)["comparison_group"] != row(result, "gift c", 11)["comparison_group"]
    assert len(result["months"][10]["comparison_groups"]) == 2


def test_common_anchor_can_compare_batches_with_different_raw_scales():
    a, b = history("A", "gift a", [20] * 12), history("B", "gift b", [60] * 12)
    for h, anchor_value in [(a, 10), (b, 60)]:
        h["normalization_context"].update(anchor="gift basket", scale="shared_anchor", date_range="2023-01-01 2026-10-30", market="US", anchor_monthly=months([anchor_value] * 12))
    result = build(config(), [keyword("A", "gift a"), keyword("B", "gift b")], [a, b])
    assert row(result, "gift a", 11)["demand_metric"] == 2
    assert row(result, "gift b", 11)["demand_metric"] == 1
    assert row(result, "gift a", 11)["demand_rank"] == 1
    assert row(result, "gift b", 11)["demand_rank"] == 2


def test_same_anchor_name_in_different_windows_is_not_comparable():
    a, b = history("A", "gift a", [20] * 12), history("B", "gift b", [60] * 12)
    for h, window in [(a, "2023-01-01 2026-10-29"), (b, "2023-01-01 2026-10-30")]:
        h["normalization_context"].update(anchor="gift basket", scale="shared_anchor", date_range=window, anchor_monthly=months([10] * 12))
    result = build(config(), [keyword("A", "gift a"), keyword("B", "gift b")], [a, b])
    assert all(r["demand_rank"] is None for r in result["rows"])


def test_missing_and_zero_months_never_fill_up_a_ranking():
    missing = history("M", "missing gift", [10] * 12, years=(2025,))
    zero = history("Z", "zero gift", [0] * 12)
    result = build(config(), [keyword("M", "missing gift"), keyword("Z", "zero gift"), keyword("U", "unobserved gift")], [missing, zero])
    assert result["status"] == "unavailable"
    assert all(not m["rankings"] for m in result["months"])
    assert row(result, "unobserved gift", 11)["year_observations"][0]["value"] is None
    assert row(result, "zero gift", 11)["year_observations"][0]["value"] == 0
    assert all(r["seasonality_rank"] is None for r in result["rows"])


def test_target_year_values_cannot_change_historical_monthly_ranks():
    h = history("A", "gift a", list(range(10, 22)))
    original = build(config(), [keyword("A", "gift a")], [h])
    changed = deepcopy(h)
    changed["monthly"] += months([9999] * 12, years=(2026,))
    changed["usable_years"] = [2023, 2024, 2025, 2026]
    assert build(config(), [keyword("A", "gift a")], [changed]) == original


def test_shared_query_keeps_niche_context_without_counting_twice_and_ties_remain_ties():
    a, b = history("A", "gift a", [20] * 12), history("B", "gift b", [10] * 12)
    result = build(config(), [keyword("A", "gift a", "N1"), keyword("AA", "gift a", "N2"), keyword("B", "gift b")], [a, b])
    assert result["coverage"]["candidate_keywords"] == 2
    assert result["coverage"]["original_keyword_contexts"] == 3
    assert row(result, "gift a", 11)["niche_ids"] == ["N1", "N2"]
    assert row(result, "gift a", 11)["seasonality_rank"] == row(result, "gift b", 11)["seasonality_rank"] == 1


def test_nonconsecutive_years_do_not_create_a_false_latest_yoy():
    h = history("A", "gift a", [20] * 12, years=(2023, 2025))
    result = build(config(), [keyword("A", "gift a")], [h])
    assert row(result, "gift a", 11)["latest_yoy_pct"] is None
    assert row(result, "gift a", 11)["seasonality_rank"] == 1
