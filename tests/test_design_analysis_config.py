"""The observed design year is independent of the forecast training years."""
import pytest

from market_research.config import validate_config
from market_research.workflow.quality import outcome


def test_analysis_year_can_be_current_or_any_past_year_without_changing_training():
    for year in (None, 2004, 2025, 2026):
        cfg = validate_config({"brief": "Singer print shirts for November", "as_of_date": "2026-11-02",
            "trends": {"history_scope": "seasonal", "history_months": [11], "analysis_year": year}})
        assert cfg["trends"]["analysis_year"] == year
        assert cfg["history_years"] == [2023, 2024, 2025]


@pytest.mark.parametrize("year", [True, 2027, 2003, "2025", 2025.5])
def test_invalid_or_future_analysis_year_is_rejected(year):
    with pytest.raises(ValueError, match="Năm phân tích Trends"):
        validate_config({"brief": "Printed shirts", "as_of_date": "2026-11-02", "trends": {"analysis_year": year}})


def test_current_month_screen_keeps_partial_observations_visible():
    state = outcome("screen", {"selection_basis": "selected_month_observations", "selection_months": [11], "analysis_year": 2026,
        "rows": [{"status": "available", "partial_period": True}]}, {})
    assert state["status"] == "partial"
    assert "tháng 11 năm 2026" in state["note"]
    assert "1 có kỳ quan sát chưa đầy đủ" in state["note"]
