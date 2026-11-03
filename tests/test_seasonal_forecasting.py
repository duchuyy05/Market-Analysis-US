"""Selected-month analysis keeps missing scope and held-out periods truthful."""
import calendar
from copy import deepcopy

import pytest

from market_research.forecasting.seasonal import forecast
from market_research.analysis.keyword_monthly import build
from market_research.analysis.monthly_priority import priority


def months(years=(2023, 2024, 2025), selected=(10, 11, 12), values=(20, 40, 80)):
    return [{"year": year, "month": month, "value": values[index], "status": "complete",
             "observed_days": calendar.monthrange(year, month)[1], "calendar_days": calendar.monthrange(year, month)[1],
             "positive_points": 4 if values[index] > 0 else 0, "native_step_days": 7}
            for year in years for index, month in enumerate(selected)]


def config():
    return {"history_years": [2023, 2024, 2025], "target_year": 2026, "selling_months": [11, 12],
            "market": "US", "as_of_date": "2026-10-30", "trends": {"history_scope": "seasonal", "history_months": [10, 11, 12]}}


def history(kid, query, values):
    data = months(values=values)
    return {"keyword_id": kid, "measurement_query": query, "status": "available", "monthly": data,
            "history_scope": "seasonal", "history_months": [10, 11, 12], "evidence_ids": ["E" + kid],
            "normalization_context": {"scale": "anchor_ratio_100", "anchor": "gift basket", "market": "US",
                "history_scope": "seasonal", "history_months": [10, 11, 12],
                "date_range": "2023-10-01 2023-12-31,2024-10-01 2024-12-31,2025-10-01 2025-12-31",
                "anchor_monthly": months(values=(20, 20, 20))},
            **forecast(data, [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])}


def test_q4_only_has_q4_forecasts_and_holdout_coverage():
    result = forecast(months(), [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    assert result["usable_years"] == [2023, 2024, 2025]
    assert [r["month"] for r in result["forecast"]] == [10, 11, 12]
    assert [r["prediction"] for r in result["forecast"]] == [20, 40, 80]
    folds = result["validation"]["folds"]
    assert len(folds) == 1 and folds[0]["train_years"] == [2023, 2024]
    assert folds[0]["months_tested"] == 3
    assert folds[0]["metrics"]["mae"] == 0
    assert result["validation"]["confidence"]["coverage_pct"] == 100
    assert result["validation"]["scope"] == result["seasonal_stability"]["scope"] == "selected_months"
    assert result["metric_unit"] == "anchor_100"
    assert all(r["scope"] == "selected_months" for r in result["annual_means"] + result["peak_months"])


def test_target_year_does_not_change_fitted_forecast_or_holdout():
    original = forecast(months(), [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    changed = forecast(months() + months((2026,), values=(9999, 9999, 9999)), [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    assert [r["prediction"] for r in changed["forecast"]] == [r["prediction"] for r in original["forecast"]]
    assert original["validation"] == changed["validation"]
    assert original["backtest"] == changed["backtest"]


def test_missing_selected_month_is_not_a_complete_cycle():
    rows = [r for r in months() if (r["year"], r["month"]) != (2024, 11)]
    result = forecast(rows, [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    assert result["usable_years"] == [2023, 2025]
    assert result["validation"]["folds"] == []
    assert result["validation"]["confidence"]["coverage_pct"] < 100
    assert len(result["forecast"]) == 3
    assert result["growth_pct"] is None  # do not skip 2024 and call 2023→2025 YoY


def test_zero_holdout_is_tested_instead_of_removed():
    rows = months((2023, 2024)) + months((2025,), values=(0, 0, 0))
    result = forecast(rows, [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    assert result["usable_years"] == [2023, 2024]
    fold = result["validation"]["folds"][0]
    assert fold["test_year"] == 2025 and fold["months_tested"] == 3
    assert fold["metrics"]["mae"] > 0 and fold["metrics"]["wape_pct"] is None
    assert all(r["actual"] == 0 for r in fold["rows"])


def test_single_selected_month_can_compare_years_but_not_annual_profile():
    result = forecast(months(selected=(12,), values=(150,)), [2023, 2024, 2025], 2026, [12], [12])
    assert result["usable_years"] == [2023, 2024, 2025]
    assert result["forecast"][0]["prediction"] == 150  # anchor scale is allowed above100
    assert result["seasonal_stability"]["profile_correlation"] is None
    assert result["seasonal_stability"]["status"] == "stable"
    assert result["validation"]["folds"][0]["months_tested"] == 1


def test_all_zero_season_and_one_spike_do_not_produce_confident_demand():
    rows = months(values=(0, 0, 0))
    result = forecast(rows, [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])
    assert result["usable_years"] == []
    assert all(r["prediction"] is None for r in result["forecast"])
    for row in rows:
        row.update(value=1 if row["month"] == 12 else 0, positive_points=1 if row["month"] == 12 else 0)
    assert forecast(rows, [2023, 2024, 2025], 2026, [11, 12], [10, 11, 12])["usable_years"] == []


def test_leap_month_coverage_counts_selected_days_only():
    result = forecast(months((2019, 2020, 2021), selected=(2,), values=(20,)), [2019, 2020, 2021], 2022, [2], [2])
    assert result["validation"]["confidence"]["coverage_pct"] == 100
    assert result["validation"]["folds"][0]["months_tested"] == 1


def test_monthly_rankings_leave_uncollected_months_unranked():
    keywords = [{"id": "A", "text": "printed calendar", "niche_id": "N"}, {"id": "B", "text": "tote bag", "niche_id": "N"}]
    result = build(config(), keywords, [history("A", "printed calendar", (20, 40, 80)), history("B", "tote bag", (30, 60, 120))])
    outside = [r for r in result["rows"] if r["month"] < 10]
    assert all(r["status"] == "not_collected" and r["seasonality_rank"] is None and r["demand_rank"] is None for r in outside)
    assert all(all(y["value"] is None for y in r["year_observations"]) for r in outside)
    december = {r["keyword_id"]: r for r in result["rows"] if r["month"] == 12}
    assert december["B"]["demand_metric"] == 1.2 and december["A"]["demand_metric"] == .8
    assert december["B"]["demand_rank"] == 1 and december["A"]["demand_rank"] == 2
    assert december["B"]["seasonal_score"] == december["A"]["seasonal_score"] == 100
    assert result["coverage"]["keywords_with_two_complete_cycles"] == 2
    assert all(m["status"] == "not_collected" for m in result["months"][:9])
    assert "không phải đỉnh của cả năm" in result["note"]


def test_annual_data_outside_requested_scope_cannot_change_q4_ranks():
    keyword = {"id": "A", "text": "printed calendar", "niche_id": "N"}
    original = history("A", "printed calendar", (20, 40, 80))
    modified = deepcopy(original)
    modified["monthly"] += months(selected=tuple(range(1, 10)), values=(9999,) * 9)
    assert build(config(), [keyword], [modified]) == build(config(), [keyword], [original])


def test_selling_month_priority_uses_calibrated_period_data():
    keywords = [{"id": "A", "text": "printed calendar", "niche_id": "N"}, {"id": "B", "text": "tote bag", "niche_id": "N"}]
    ranking = build(config(), keywords, [history("A", "printed calendar", (20, 40, 80)), history("B", "tote bag", (30, 60, 120))])
    screening = {"rows": [{"keyword_id": k["id"], "keyword": k["text"], "measurement_query": k["text"], "rank": None, "evidence_ids": [], "status": "unavailable"} for k in keywords]}
    result = priority(config(), {"keywords": keywords}, screening, ranking)
    assert result["selection_basis"] == "historical_selling_months"
    assert next(r for r in result["rows"] if r["keyword_id"] == "B")["rank"] == 1
    assert all(r["monthly_usable_years"] == [2023, 2024, 2025] for r in result["rows"])


@pytest.mark.parametrize("selected", [[], [0], [13]])
def test_invalid_season_months_are_rejected(selected):
    with pytest.raises(ValueError):
        forecast(months(), [2023, 2024, 2025], 2026, [11, 12], selected)
