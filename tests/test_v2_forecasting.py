from datetime import date, timedelta

from market_research.forecasting.series import monthly
from market_research.forecasting.assess import forecast


def annual_months(years):
    return [{"year": y, "month": m, "value": float(m*3), "status": "complete", "observed_days": 30, "calendar_days": 30, "positive_points": 4} for y in years for m in range(1, 13)]


def test_crossing_week_is_weighted_by_calendar_days():
    rows = monthly([{"start": "2025-10-28", "end": "2025-11-04", "value": 70, "partial": False}], [2025], "2025-12-31")
    october, november = rows[9], rows[10]
    assert october["observed_days"] == 4 and november["observed_days"] == 3
    assert october["value"] == november["value"] == 70


def test_partial_source_points_and_future_are_not_zero():
    rows = monthly([{"start": "2026-10-18", "end": "2026-10-25", "value": 80, "partial": True}], [2026], "2026-10-22")
    assert rows[9]["value"] is None
    assert rows[10]["status"] == "future" and rows[10]["value"] is None


def test_2026_cannot_change_2026_prediction_or_2025_holdout():
    baseline = annual_months([2023, 2024, 2025])
    result = forecast(baseline, [2023, 2024, 2025], 2026, [11, 12])
    distorted = annual_months([2026])
    for r in distorted:
        r["value"] = 9999
    changed = forecast(baseline + distorted, [2023, 2024, 2025], 2026, [11, 12])
    assert [r["prediction"] for r in result["forecast"]] == [r["prediction"] for r in changed["forecast"]]
    assert result["backtest"] == changed["backtest"]
    assert result["backtest"]["mae"] == 0


def test_missing_year_does_not_create_false_stability():
    result = forecast(annual_months([2025]), [2023, 2024, 2025], 2026, [11])
    assert result["stability"] == "insufficient"
    assert all(r["prediction"] is None for r in result["forecast"])


def test_zero_history_does_not_generate_growth_or_demand():
    rows = annual_months([2023, 2024, 2025])
    for row in rows:
        row.update(value=0, positive_points=0)
    result = forecast(rows, [2023, 2024, 2025], 2026, [11])
    assert result["growth_pct"] is None
    assert result["stability"] == "insufficient"
