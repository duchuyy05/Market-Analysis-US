"""Candidate-wide trends remain primary SQLite data even without product selection."""
from copy import deepcopy
import json

import pytest

from market_research.storage.database import merged_histories
from market_research.storage.run import Run
from test_database import dataset


def candidate_history():
    return {"direction_id": "candidate-K2", "keyword_id": "K2", "measurement_query": "book light",
            "evidence_ids": ["E-candidate"],
            "normalization_context": {"anchor": "gift basket", "date_range": "2021-01-01 2026-10-30", "market": "US"},
            "monthly": [{"year": 2021, "month": 1, "value": 0, "status": "complete", "observed_days": 31},
                        {"year": 2021, "month": 2, "value": None, "status": "unavailable", "observed_days": 0}],
            "forecast": [{"year": 2026, "month": 11, "prediction": None, "observed": None, "observation_status": "future"}],
            "validation": {"metrics": {"mae": None}, "baseline_metrics": {"mae": None}, "folds": []}}


def research_data():
    data = dataset()
    data["keywords"].append({"id": "K2", "text": "book light", "niche_id": "N", "origin": "llm_expansion"})
    data["keyword_histories"] = [candidate_history()]
    data["keyword_monthly"] = {"status": "partial", "rows": [{"month": 1, "keyword_id": "K2", "seasonality_rank": None,
                                                   "demand_rank": None, "reason": "Thiếu năm để xếp hạng"}]}
    return data


def test_nonselected_candidate_histories_and_monthly_rankings_roundtrip_without_csv(tmp_path):
    run = Run("candidate-primary", tmp_path)
    data = research_data()
    run.save_dataset(data)
    (run.path / "dataset.json").unlink()
    restored = Run(run.id, tmp_path).load_dataset()
    assert restored["keyword_histories"] == data["keyword_histories"]
    assert restored["keyword_monthly"] == data["keyword_monthly"]
    with run.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM directions WHERE direction_id='candidate-K2'").fetchone()[0] == 0
        values = conn.execute("SELECT year,month,value,status,payload_json FROM trend_observations WHERE direction_id='candidate-K2' ORDER BY month").fetchall()
        assert [tuple(row[:4]) for row in values] == [(2021, 1, 0, "complete"), (2021, 2, None, "unavailable")]
        payload = json.loads(values[0][4])
        assert payload["keyword_id"] == "K2" and payload["evidence_ids"] == ["E-candidate"]
        assert payload["normalization_context"]["anchor"] == "gift basket"
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_selected_history_precedence_is_atomic_and_does_not_duplicate_observations(tmp_path):
    run = Run("selected-wins", tmp_path)
    data = research_data()
    duplicate = deepcopy(data["histories"][0])
    duplicate["monthly"][0]["value"] = 999
    duplicate["forecast"][0]["prediction"] = 999
    data["keyword_histories"].append(duplicate)
    assert next(h for h in merged_histories(data) if h["direction_id"] == "D")["monthly"][0]["value"] == 10
    original = deepcopy(data)
    run.save_dataset(data)
    run.save_dataset(data)
    assert data == original
    with run.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM trend_observations").fetchone()[0] == 3
        assert conn.execute("SELECT value FROM trend_observations WHERE direction_id='D'").fetchone()[0] == 10
        assert conn.execute("SELECT prediction FROM forecast_values WHERE direction_id='D'").fetchone()[0] == 20
        assert conn.execute("SELECT count(*) FROM forecast_values").fetchone()[0] == 2


def test_failed_candidate_projection_rolls_back_dataset_and_previous_series(tmp_path):
    run = Run("candidate-atomic", tmp_path)
    data = research_data()
    run.save_dataset(data)
    broken = deepcopy(data)
    broken["keyword_histories"][0]["monthly"].append({"month": 3, "value": 9})
    with pytest.raises(KeyError):
        run.db.save_dataset(run.id, broken)
    assert run.db.get_dataset(run.id) == data
    with run.db.connection() as conn:
        assert conn.execute("SELECT count(*) FROM trend_observations").fetchone()[0] == 3
