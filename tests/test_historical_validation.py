import calendar
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from market_research.config import validate_config
from market_research.forecasting.assess import forecast
from market_research.forecasting.validation import metrics
from market_research.forecasting.series import parse_timeline, monthly


def months(years):
    return [{"year": y, "month": m, "value": float(m * 3 + (y - 2021)), "status": "complete",
             "observed_days": calendar.monthrange(y, m)[1], "calendar_days": calendar.monthrange(y, m)[1],
             "positive_points": 4} for y in years for m in range(1, 13)]


def test_2021_2025_has_three_strictly_historical_holdouts_and_selling_metrics():
    result = forecast(months(range(2021, 2027)), list(range(2021, 2026)), 2026, [11, 12])
    validation = result["validation"]
    assert [f["test_year"] for f in validation["folds"]] == [2023, 2024, 2025]
    assert all(max(f["train_years"]) < f["test_year"] for f in validation["folds"])
    assert validation["metrics"]["n"] == 36
    assert validation["selling_metrics"]["n"] == 6
    assert validation["baseline_metrics"]["mae"] == 1
    assert validation["confidence"]["coverage_pct"] == 100
    assert validation["skill_pct"] < 0  # Slow median is worse than last year for linear growth.
    assert validation["confidence"]["level"] == "limited"


def test_target_year_cannot_leak_into_predictions_or_validation_even_if_requested():
    original = months(range(2021, 2027))
    changed = deepcopy(original)
    for row in changed:
        if row["year"] == 2026:
            row["value"] = 9999
    a = forecast(original, list(range(2021, 2027)), 2026, [12])
    b = forecast(changed, list(range(2021, 2027)), 2026, [12])
    assert a["validation"] == b["validation"]
    assert a["same_period"] == b["same_period"]
    assert [r["prediction"] for r in a["forecast"]] == [r["prediction"] for r in b["forecast"]]
    assert 2026 not in a["usable_years"]


def test_missing_selected_year_reduces_coverage_and_missing_previous_year_is_not_baseline():
    result = forecast(months([2021, 2022, 2024]), [2021, 2022, 2023, 2024], 2026, [11, 12])
    validation = result["validation"]
    assert 74 < validation["confidence"]["coverage_pct"] < 76
    assert validation["folds"][0]["test_year"] == 2024
    assert validation["baseline_metrics"]["n"] == 0
    assert validation["skill_pct"] is None
    assert result["same_period"][2]["mean_index"] is None
    assert result["same_period"][3]["yoy_pct"] is None


def test_same_selling_months_yoy_and_profile_stability():
    result = forecast(months([2021, 2022, 2023]), [2021, 2022, 2023], 2026, [11, 12])
    first, second, _ = result["same_period"]
    assert first["mean_index"] == 34.5
    assert second["yoy_pct"] == pytest.approx(2.899)
    assert result["seasonal_stability"]["profile_correlation"] == 1
    assert result["seasonal_stability"]["status"] == "stable"


def test_zero_safe_errors_preserve_undefined_wape():
    result = metrics([{"actual": 0, "prediction": 0}])
    assert result == {"mae": 0, "rmse": 0, "wape_pct": None, "smape_pct": 0, "n": 1}
    assert metrics([{"actual": 0, "prediction": 2}])["smape_pct"] == 200
    assert metrics([{"actual": None, "prediction": 2}])["n"] == 0


def test_complete_zero_demand_year_remains_tested_instead_of_hiding_decline():
    rows = months([2021, 2022, 2023])
    for row in rows:
        if row["year"] == 2023:
            row.update(value=0, positive_points=0)
    result = forecast(rows, [2021, 2022, 2023], 2026, [11, 12])
    assert result["usable_years"] == [2021, 2022]
    assert result["validation"]["folds"][0]["test_year"] == 2023
    assert result["validation"]["metrics"]["mae"] > 0
    assert result["validation"]["metrics"]["wape_pct"] is None


def test_monthly_resolution_accepts_two_seasonal_months_but_not_single_spike():
    rows = months([2021, 2022, 2023])
    for row in rows:
        row.update(value=50 if row["month"] >= 11 else 0, positive_points=int(row["month"] >= 11), native_step_days=30)
    assert forecast(rows, [2021, 2022, 2023], 2026, [11, 12])["usable_years"] == [2021, 2022, 2023]
    for row in rows:
        if row["month"] == 11:
            row.update(value=0, positive_points=0)
    assert forecast(rows, [2021, 2022, 2023], 2026, [12])["usable_years"] == []


def test_six_year_native_monthly_timeline_keeps_february_and_partial_cutoff_honest():
    points = [{"timestamp": str(int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp())),
               "values": [{"query": "ornaments", "extracted_value": 60 if m in [11, 12] else 0}]}
              for y in range(2020, 2027) for m in range(1, 13) if (y, m) <= (2026, 10)]
    parsed = parse_timeline({"response": {"interest_over_time": {"timeline_data": points}}}, "ornaments")
    assert parsed[-1]["end"] == "2026-11-01"
    rows = monthly(parsed, list(range(2020, 2027)), "2026-10-29")
    assert next(r for r in rows if (r["year"], r["month"]) == (2020, 2))["observed_days"] == 29
    october = next(r for r in rows if (r["year"], r["month"]) == (2026, 10))
    assert october["status"] == "partial" and october["observed_days"] == 29
    result = forecast(rows, list(range(2020, 2026)), 2026, [11, 12])
    assert result["usable_years"] == list(range(2020, 2026))
    assert len(result["validation"]["folds"]) == 4


@pytest.mark.parametrize("years", [[2021, 2021], [2025, 2026], list(range(2019, 2026))])
def test_invalid_history_selection_rejected(years):
    with pytest.raises(ValueError):
        validate_config({"brief": "Gifts", "as_of_date": "2026-10-29", "history_years": years})


def test_earlier_years_accepted_without_including_target_year():
    cfg = validate_config({"brief": "Gifts", "as_of_date": "2026-10-29", "history_years": list(range(2021, 2026)), "target_year": 2026})
    assert cfg["history_years"] == list(range(2021, 2026))
