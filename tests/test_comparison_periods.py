import calendar
from datetime import datetime, timezone

import pytest

from market_research.config import validate_config
from market_research.forecasting.periods import summarize
from market_research.storage.run import Run
from market_research.workflow.history import analyze


def config(periods=None):
    return validate_config({"brief": "Christmas gifts", "as_of_date": "2026-10-29", "selling_months": [11, 12], "comparison_periods": periods or []})


def month(year, number, value, observed_days=None):
    days = calendar.monthrange(year, number)[1]
    observed_days = days if observed_days is None else observed_days
    return {"year": year, "month": number, "value": value, "observed_days": observed_days,
            "status": "complete" if observed_days == days else "partial" if observed_days else "unavailable"}


def test_periods_preserve_separate_seasons_and_sort_without_mutating_input():
    periods = [{"start": "2024-10", "end": "2024-12"}, {"start": "2023-10", "end": "2023-12"}]
    cfg = config(periods)
    assert cfg["comparison_periods"] == list(reversed(periods))
    assert periods[0]["start"] == "2024-10"
    assert config()["comparison_periods"] == []


@pytest.mark.parametrize("periods", [
    [{"start": "2024-13", "end": "2024-12"}],
    [{"start": "2024-12", "end": "2024-10"}],
    [{"start": "2026-10", "end": "2026-12"}],
    [{"start": "2003-10", "end": "2003-12"}],
    [{"start": "2023-10", "end": "2023-12", "label": "extra"}],
    [{"start": "2023-10", "end": "2023-12"}] * 2,
    [{"start": "2004-01", "end": "2023-12"}],
    [{"start": "2023-01", "end": "2023-01"}] * 13,
    "2023-10..2023-12",
])
def test_invalid_periods_are_rejected(periods):
    with pytest.raises(ValueError):
        config(periods)


def test_period_aggregation_uses_same_series_and_reports_missing_instead_of_zero():
    periods = [{"start": "2023-10", "end": "2023-12"}, {"start": "2024-10", "end": "2024-12"}, {"start": "2025-10", "end": "2025-12"}]
    values = [month(2023, m, 10) for m in (10, 11, 12)] + [month(2024, m, 20) for m in (10, 11, 12)]
    rows = summarize(values, periods, ["E-source"])
    assert rows[0]["mean_index"] == 10
    assert rows[1]["mean_index"] == 20 and rows[1]["change_vs_previous_pct"] == 100
    assert rows[2]["status"] == "unavailable" and rows[2]["mean_index"] is None
    assert rows[2]["coverage_pct"] == 0
    assert rows[0]["evidence_ids"] == ["E-source"]


def test_partial_and_zero_baseline_do_not_produce_false_growth():
    periods = [{"start": "2023-10", "end": "2023-12"}, {"start": "2024-10", "end": "2024-12"}]
    values = [month(2023, m, 0) for m in (10, 11, 12)] + [month(2024, 10, 20, 10)]
    rows = summarize(values, periods)
    assert rows[0]["mean_index"] == 0 and rows[0]["status"] == "complete"
    assert rows[1]["status"] == "partial" and rows[1]["observed_days"] == 10
    assert rows[1]["change_vs_previous_pct"] is None


def test_multiple_periods_use_one_history_fetch_and_keep_forecast_training_years(tmp_path, monkeypatch):
    cfg = config([{"start": "2020-10", "end": "2020-12"}, {"start": "2024-10", "end": "2024-12"}])
    calls = []
    def history(client, query, request):
        calls.append(request)
        points = []
        for year in range(2020, 2027):
            for number in range(1, 13):
                if (year, number) > (2026, 10):
                    break
                stamp = int(datetime(year, number, 1, tzinfo=timezone.utc).timestamp())
                points.append({"timestamp": str(stamp), "values": [{"query": query, "extracted_value": 10 + number}]})
        return {"provider": "fixture", "parameters": {"date": "2020-01-01 2026-10-29"}, "response": {"interest_over_time": {"timeline_data": points}},
                "retrieved_at": "2026-10-29T00:00:00Z", "raw_file": "raw/fixture.json"}
    monkeypatch.setattr("market_research.workflow.history.trends.history", history)
    run = Run("period-test", tmp_path)
    direction = {"id": "D", "keyword": "gift basket", "keyword_id": "K"}
    result = analyze(run, None, cfg, [direction])
    assert len(calls) == 1
    assert min(calls[0]["history_years"]) == 2020
    assert cfg["history_years"] == [2023, 2024, 2025]
    assert len(result[0]["comparison_periods"]) == 2
    assert all(row["status"] == "complete" for row in result[0]["comparison_periods"])
    assert result[0]["backtest"]["train_years"] == [2023, 2024]
    analyze(run, None, cfg, [direction])
    assert len(calls) == 1
