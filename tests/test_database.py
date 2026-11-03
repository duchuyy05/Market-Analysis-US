import json
from pathlib import Path
import sqlite3
import threading

import pytest

from market_research.common import read_json, write_json
from market_research.storage.database import Database, product_identity
from market_research.storage.run import Run


def dataset(price=20, year=2026):
    return {"config": {"niches": [{"id": "N", "name": "Gifts"}]},
        "keywords": [{"id": "K", "text": "blanket", "niche_id": "N", "origin": "user"}],
        "keyword_screening": [{"keyword_id": "K", "measurement_query": "blanket", "status": "available", "score": 80}],
        "directions": [{"id": "D", "niche_id": "N", "keyword_id": "K", "keyword": "blanket"}],
        "products": [{"product_id": "P", "asin": "B012345678", "source": "amazon", "title": "Blanket", "url": "https://www.amazon.com/dp/B012345678", "price": price, "currency": "USD", "rating": 4.5, "review_count": 10, "merchant": "Shop", "variant": "blue", "observed_at": f"{year}-10-29T00:00:00Z"}],
        "offers": [{"offer_id": "O", "product_id": "P", "observed_at": f"{year}-10-29T00:00:00Z", "price": price, "currency": "USD", "variant": "blue", "merchant": "Shop"}],
        "reviews": [{"id": "R", "product_id": "P", "asin": "B012345678", "text": "Soft blanket", "kind": "excerpt", "rating": None}],
        "histories": [{"direction_id": "D", "measurement_query": "blanket", "monthly": [{"year": 2021, "month": 10, "value": 10, "status": "complete", "observed_days": 31}],
            "forecast": [{"year": 2026, "month": 11, "prediction": 20, "observed": None, "observation_status": "future"}],
            "backtest": {"train_years": [2021, 2022], "test_year": 2023, "mae": 2, "seasonal_naive_mae": 3, "folds": [{"test_year": 2023, "train_years": [2021, 2022], "mae": 2, "seasonal_naive_mae": 3}]}}]}


def test_database_is_primary_when_json_mirrors_are_missing_or_stale(tmp_path):
    run = Run("primary", tmp_path)
    run.manifest.update(status="running", input_hash="immutable", usage=[{"provider": "serpapi", "engine": "amazon", "status": "received"}])
    run.save()
    run.checkpoint("discover", {"keywords": ["blanket"]})
    run.save_dataset(dataset())
    run.log("discover", "result", "Found blanket")
    write_json(run.path / "manifest.json", {"run_id": run.id, "status": "wrong-stale-json"})
    (run.path / "dataset.json").unlink()
    (run.path / "checkpoints/discover.json").unlink()
    again = Run(run.id, tmp_path)
    assert again.manifest["status"] == "running"
    assert again.manifest["input_hash"] == "immutable"
    assert len(again.manifest["usage"]) == 1
    assert again.stage_data("discover") == {"keywords": ["blanket"]}
    assert again.load_dataset()["products"][0]["price"] == 20
    assert again.db.list_events(run.id, "discover")[0]["message"] == "Found blanket"


def test_dataset_normalized_tables_are_queryable_without_reading_csv(tmp_path):
    run = Run("tables", tmp_path)
    run.save_dataset(dataset())
    with run.db.connection() as conn:
        assert conn.execute("SELECT price,currency FROM product_snapshots").fetchone()[:] == (20, "USD")
        assert conn.execute("SELECT body,rating FROM reviews").fetchone()[:] == ("Soft blanket", None)
        assert conn.execute("SELECT year,month,value FROM trend_observations").fetchone()[:] == (2021, 10, 10)
        assert conn.execute("SELECT test_year,mae,baseline_mae FROM forecast_backtests WHERE fold_id='summary'").fetchone()[:] == (2023, 2, 3)
        assert conn.execute("SELECT observed,observation_status FROM forecast_values").fetchone()[:] == (None, "future")
        assert conn.execute("SELECT name FROM niches").fetchone()[0] == "Gifts"


def test_failed_dataset_update_rolls_back_json_blob_and_relational_rows(tmp_path):
    run = Run("atomic", tmp_path)
    run.save_dataset(dataset())
    broken = dataset(99)
    broken["products"].append({"title": "Missing ID"})
    with pytest.raises(KeyError):
        run.db.save_dataset(run.id, broken)
    assert run.db.get_dataset(run.id)["products"][0]["price"] == 20
    with run.db.connection() as conn:
        assert conn.execute("SELECT price FROM product_snapshots").fetchone()[0] == 20


def test_rolling_validation_and_legacy_backtests_remain_queryable_together(tmp_path):
    run = Run("validation", tmp_path)
    data = dataset()
    data["histories"][0]["validation"] = {
        "metrics": {"mae": 4.5, "wape_pct": 12},
        "baseline_metrics": {"mae": 6},
        "folds": [
            {"test_year": 2023, "train_years": [2021, 2022], "metrics": {"mae": 0}, "baseline_metrics": {"mae": 3}},
            {"test_year": 2024, "train_years": [2021, 2022, 2023], "metrics": {"mae": 9}, "baseline_metrics": {"mae": 9}},
        ],
    }
    run.save_dataset(data)
    with run.db.connection() as conn:
        rows = conn.execute("SELECT fold_id,test_year,mae,baseline_mae,train_years_json FROM forecast_backtests ORDER BY fold_id").fetchall()
    values = {r[0]: tuple(r[1:]) for r in rows}
    assert values["summary"][:3] == (2023, 2, 3)
    assert values["0"][:3] == (2023, 2, 3)
    assert values["validation-summary"][:3] == (None, 4.5, 6)
    assert values["validation-0"] == (2023, 0, 3, "[2021,2022]")
    assert values["validation-1"] == (2024, 9, 9, "[2021,2022,2023]")


def test_migration_is_idempotent_and_never_overwrites_newer_db_state(tmp_path):
    root = tmp_path / "data/runs/legacy"
    manifest = {"run_id": "legacy", "created_at": "2026-10-29", "status": "partial", "input_hash": "same", "usage": [{"provider": "serpapi", "status": "received"}], "stages": {}}
    write_json(root / "manifest.json", manifest)
    write_json(root / "evidence.json", {})
    write_json(root / "checkpoints/history.json", [{"direction_id": "D"}])
    write_json(root / "dataset.json", dataset())
    root.joinpath("events.jsonl").write_text(json.dumps({"at": "2026-10-29", "stage": "history", "event": "done", "message": "Imported"})+"\n", encoding="utf-8")
    write_json(tmp_path / "data/workspace/state.json", {"saved_runs": ["legacy"], "saved_products": [], "edited": {}})
    db = Database(tmp_path)
    first = db.migrate_legacy()
    assert first["runs"] == first["datasets"] == first["workspace"] == 1
    assert first["events"] == 1
    changed = {**manifest, "status": "complete"}
    db.save_run(changed)
    second = db.migrate_legacy()
    assert second["runs"] == second["datasets"] == second["events"] == 0
    assert db.get_manifest("legacy")["status"] == "complete"
    assert read_json(root / "manifest.json")["status"] == "partial"
    assert db.get_workspace()["saved_runs"] == ["legacy"]
    assert db.get_manifest("legacy")["input_hash"] == "same"


def test_snapshots_preserve_same_product_across_actual_capture_years(tmp_path):
    one, two = Run("capture-2025", tmp_path), Run("capture-2026", tmp_path)
    one.save_dataset(dataset(20, 2025))
    two.save_dataset(dataset(22, 2026))
    history = two.db.product_history("B012345678")
    assert [r["price"] for r in history] == [20, 22]
    assert {r["run_id"] for r in history} == {one.id, two.id}
    summary = two.db.product_stability("B012345678")
    assert summary["observed_years"] == [2025, 2026]
    assert summary["status"] == "available"
    assert two.db.product_history("B012345678", before="2025-12-31")[0]["price"] == 20


def test_no_historical_product_capture_stays_insufficient(tmp_path):
    run = Run("only-now", tmp_path)
    run.save_dataset(dataset())
    summary = run.db.product_stability("B012345678")
    assert summary["observed_years"] == [2026]
    assert summary["status"] == "insufficient_history"
    assert summary["snapshot_count"] == 1
    assert run.db.product_history("B012345678", before="2023-12-31") == []


def test_zero_price_does_not_turn_into_missing_and_unknown_stays_null(tmp_path):
    run = Run("unknown", tmp_path)
    run.save_dataset(dataset(0))
    assert run.db.product_history("B012345678")[0]["price"] == 0
    run.save_dataset(dataset(None))
    with run.db.connection() as conn:
        assert conn.execute("SELECT price FROM product_snapshots").fetchone()[0] is None


def test_manifest_writes_are_thread_safe_and_usage_updates_replace_same_attempt(tmp_path):
    run = Run("threads", tmp_path)
    errors = []
    def update(index):
        try:
            for value in range(4):
                manifest = {"run_id": run.id, "created_at": "2026-10-29", "status": str(value), "stages": {}, "usage": [{"provider": "serpapi", "status": str(value)}]}
                run.db.save_run(manifest)
        except Exception as error:
            errors.append(error)
    workers = [threading.Thread(target=update, args=(i,)) for i in range(3)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    assert errors == []
    with run.db.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_identity_and_queries_do_not_merge_different_non_amazon_listings(tmp_path):
    assert product_identity({"asin": "b012345678", "source": "shopping"}) == "amazon:B012345678"
    assert product_identity({"source": "shopping", "provider_product_id": "1"}) != product_identity({"source": "shopping", "provider_product_id": "2"})
    run = Run("safe-query", tmp_path)
    assert run.db.product_history("x' OR 1=1 --") == []


def test_future_schema_is_rejected_without_downgrading(tmp_path):
    path = tmp_path / "data/market_research.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError, match="mới hơn"):
        Database(tmp_path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 999
