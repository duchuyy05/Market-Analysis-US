import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from market_research.ui.server import Manager, handler_class


@pytest.fixture
def app(tmp_path):
    manager = Manager(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(manager))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}", manager
    server.shutdown()
    server.server_close()
    manager.pool.shutdown(wait=True)


def test_ui_and_output_boundary(app):
    base, _ = app
    with urlopen(base) as response:
        assert response.status == 200
        assert "research-form" in response.read().decode()
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/outputs/../api/.env")
    assert error.value.code == 403
    request = Request(base + "/api/runs", data=b"{}", headers={"Content-Type": "application/json"})
    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == 403


def test_report_images_only_served_under_per_run_assets(app):
    base, manager = app
    for relative in ("outputs/sample/assets/photo.png", "outputs/sample/photo.png", "data/runs/sample/assets/private.png"):
        target = manager.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fixture-image")
    with urlopen(base + "/outputs/sample/assets/photo.png") as response:
        assert response.headers.get_content_type() == "image/png"
        assert response.read() == b"fixture-image"
    for path in ("/outputs/sample/photo.png", "/outputs/../data/runs/sample/assets/private.png"):
        with pytest.raises(HTTPError) as error:
            urlopen(base + path)
        assert error.value.code == 403


def test_ui_reads_sqlite_when_json_exports_are_stale(app):
    from market_research.common import write_json
    from market_research.storage.run import Run
    base, manager = app
    run = Run("db-primary-ui", manager.root)
    run.manifest.update(status="partial", summary={"category": "Database current title"})
    run.save()
    run.checkpoint("history", [{"direction_id": "D1", "measurement_query": "gifts", "usable_years": [2021, 2022, 2023],
                                "validation": {"metrics": {"mae": 2}, "confidence": {"coverage_pct": 100, "fold_count": 1}}}])
    run.db.save_dataset(run.id, {"products": [{"product_id": "P1", "title": "Current DB product", "price": 7, "currency": "USD", "source": "amazon"}]})
    write_json(run.path / "manifest.json", {**run.manifest, "summary": {"category": "Stale JSON title"}})
    write_json(run.path / "dataset.json", {"products": []})
    with urlopen(base + "/api/runs/" + run.id) as response:
        state = json.load(response)
    assert state["summary"]["category"] == "Database current title"
    assert state["historical_overview"][0]["metrics"]["mae"] == 2
    with urlopen(base + "/api/products") as response:
        assert json.load(response)["items"][0]["title"] == "Current DB product"


@pytest.mark.parametrize("path, content_type", [
    ("/", "text/html"),
    ("/assets/app.js", "application/javascript"),
    ("/assets/style.css", "text/css"),
])
def test_web_content_types_ignore_windows_file_associations(app, monkeypatch, path, content_type):
    # Windows can associate .js with text/plain; nosniff then disables the UI.
    monkeypatch.setattr(mimetypes, "guess_type", lambda *args, **kwargs: ("text/plain", None))
    base, _ = app
    with urlopen(base + path) as response:
        assert response.headers.get_content_type() == content_type
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"


def test_one_submission_creates_offline_report_and_downloads(app):
    base, manager = app
    cfg = {"brief": "Phat lai Q4", "mode": "offline", "as_of_date": "2026-10-22", "llm": {"enabled": False}}
    request = Request(base + "/api/runs", data=json.dumps(cfg).encode(), headers={"Content-Type": "application/json", "X-Research-Client": "local"})
    with urlopen(request) as response:
        run_id = json.load(response)["run_id"]
    manager.jobs[run_id].result(timeout=30)
    with urlopen(base + "/api/runs/" + run_id) as response:
        state = json.load(response)
    assert state["status"] == "partial"  # Archived bundle has no Shopping snapshots.
    assert state["summary"]["niches"] == 3
    assert "report.html" in state["files"]
    with urlopen(base + "/outputs/" + run_id + "/report.html") as response:
        html = response.read().decode()
        assert "PHÁT LẠI DỮ LIỆU ĐÃ LƯU" in html
        assert "Lịch sử 2023, 2024, 2025 và dự báo tham khảo 2026" in html
    with urlopen(base + "/outputs/" + run_id + "/dataset.json") as response:
        dataset = json.load(response)
    assert len(dataset["histories"]) == 10
    assert all(history["status"] == "available" for history in dataset["histories"])
    for history in dataset["histories"]:
        assert {2023, 2024, 2025} <= {month["year"] for month in history["monthly"]}
        assert history["forecast"]
    with urlopen(base + "/outputs/" + run_id + "/tables/products.csv") as response:
        assert response.read().startswith(b"\xef\xbb\xbf")


def test_cross_origin_submission_rejected(app):
    base, _ = app
    request = Request(base + "/api/runs", data=b"{}", headers={"Content-Type": "application/json", "X-Research-Client": "local", "Origin": "https://foreign.test"})
    with pytest.raises(HTTPError) as error:
        urlopen(request)
    assert error.value.code == 403


def test_orphaned_run_exposes_resume_state(app):
    from market_research.storage.run import Run
    base, manager = app
    run = Run("orphaned", manager.root)
    run.manifest["status"] = "running"
    run.save()
    with urlopen(base + "/api/runs/orphaned") as response:
        state = json.load(response)
    assert state["status"] == "interrupted"


def test_javascript_submission_and_q4_report(app):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed only for the JavaScript interaction checks")
    base, _ = app
    result = subprocess.run(
        [node, "--test", str(Path(__file__).with_name("check_ui.mjs"))],
        env={**os.environ, "RESEARCH_UI_BASE": base},
        capture_output=True, text=True, encoding="utf-8", timeout=40,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_discovery_status_is_available_from_checkpoints_before_report_exists(app):
    from market_research.common import write_json
    from market_research.storage.run import Run
    base, manager = app
    run = Run("screening-status", manager.root)
    run.manifest.update(status="partial", usage=[{"provider": "google_trends_free", "status": "received"}])
    run.save()
    run.checkpoint("screen", {"note": "Measured pool", "rows": [{"keyword": "candle warmer", "score": 90}]})
    run.checkpoint("discover", {"discovery_sources": [{"sites": ["etsy"], "status": "available", "count": 1}], "web_context": [{"title": "Gift", "platform": "etsy", "url": "https://etsy.com/listing/1", "excerpt": "Not repeated in polling"}]})
    with urlopen(base + "/api/settings") as response:
        settings = json.load(response)
    assert settings["capabilities"]["free_trends"] is True
    assert settings["capabilities"]["seasonal_history"] is True
    assert settings["capabilities"]["design_month_screening"] is True
    assert settings["capabilities"]["manufacturing_models"] is True
    assert settings["capabilities"]["design_content"] is True
    assert settings["capabilities"]["exa_discovery"] is True
    assert settings["capabilities"]["public_scrapers"] is True
    assert type(settings["keys"]["EXA_API_KEY"]) is bool
    assert settings["capabilities"]["company_domain"] is True
    assert settings["capabilities"]["apify"] is False
    with urlopen(base + "/api/runs/" + run.id) as response:
        state = json.load(response)
    assert state["request_counts"]["google_trends_free"] == 1
    assert state["discovery_overview"]["rows"][0]["keyword"] == "candle warmer"
    assert state["discovery_overview"]["pages"][0]["url"] == "https://etsy.com/listing/1"
    assert "excerpt" not in state["discovery_overview"]["pages"][0]
    assert state["files"] == []


def test_waiting_trends_exposes_real_counts_and_subcap_without_changing_the_run(app):
    from market_research.config import validate_config
    from market_research.storage.run import Run
    base, manager = app
    run = Run("waiting-sparse-diagnosis", manager.root)
    config = validate_config({"brief": "Keychain models", "as_of_date": "2026-11-02",
        "trends": {"history_scope": "seasonal", "history_months": [10, 11, 12]}, "limits": {"serpapi_requests": 30, "trends_serpapi_requests": 8}})
    usage = [{"provider": "serpapi", "engine": "google_trends", "status": "received"} for _ in range(8)]
    usage.append({"provider": "google_trends_free", "status": "HTTP 429"})
    run.manifest.update(input=config, status="awaiting_trends", current_stage="screen", usage=usage,
                        stages={"screen": {"status": "waiting"}, "monthly": {"status": "waiting"}})
    run.save()
    run.checkpoint("screen", {"analysis_year": 2025, "selection_months": [10, 11, 12], "rows": [
        *[{"keyword": "model " + str(i), "status": "low_signal", "rank": None} for i in range(32)],
        *[{"keyword": "pending " + str(i), "status": "unavailable", "rank": None} for i in range(6)]]})
    with urlopen(base + "/api/runs/" + run.id) as response:
        state = json.load(response)
    assert state["screening_diagnostics"]["measured"] == 32
    assert state["screening_diagnostics"]["unavailable"] == 6
    assert state["screening_diagnostics"]["retry_kind"] == "free_only"
    assert "8/8" in state["screening_diagnostics"]["summary"]
    assert manager.manifest(run.id)["input"] == config
    assert manager.manifest(run.id)["usage"] == usage


def test_stage_detail_returns_keywords_and_sanitized_bounded_logs(app):
    from market_research.storage.run import Run
    base, manager = app
    run = Run("stage-inspection", manager.root)
    run.manifest["stages"]["discover"] = {"status": "complete", "attempts": 1}
    run.save()
    run.checkpoint("discover", {"keywords": [{"id": "K1", "text": "candle warmer", "origin": "public_web", "api_key": "must-not-show"}]})
    (manager.root / ".env").write_text("TAVILY_API_KEY=private-test-key", encoding="utf-8")
    with (run.path / "events.jsonl").open("w", encoding="utf-8") as stream:
        for i in range(130):
            stream.write(json.dumps({"stage": "discover", "at": "2026-10-29T00:00:00Z", "event": "llm_response", "message": "private-test-key", "details": {"keywords": ["candle warmer"], "api_key": "must-not-show", "reasoning": "hidden-chain", "trace_file": "api/.env"}}) + "\n")
        stream.write('{"partial":')
    with urlopen(base + "/api/runs/" + run.id + "/stages/discover") as response:
        detail = json.load(response)
    assert detail["summary"]["keywords"][0]["text"] == "candle warmer"
    assert detail["truncated"] is True
    assert len(detail["logs"]) == 100
    assert "private-test-key" not in json.dumps(detail)
    assert "must-not-show" not in json.dumps(detail)
    assert "hidden-chain" not in json.dumps(detail)
    assert "api/.env" not in json.dumps(detail)
    assert "raw_file" not in detail


def test_stage_detail_validates_known_stage_and_run_boundary(app):
    from market_research.storage.run import Run
    base, manager = app
    run = Run("legacy-detail", manager.root)
    run.save()
    run.checkpoint("understand", {"category": "Gifts", "niches": [{"name": "Friends", "seeds": ["photo ornament"]}]})
    with urlopen(base + "/api/runs/legacy-detail/stages/understand") as response:
        detail = json.load(response)
    assert detail["summary"]["niches"][0]["seeds"] == ["photo ornament"]
    assert detail["logs"] == []
    for suffix, status in (("legacy-detail/stages/env", 400), ("unknown/stages/discover", 404), ("legacy-detail/stages/../../api/.env", 404)):
        with pytest.raises(HTTPError) as error:
            urlopen(base + "/api/runs/" + suffix)
        assert error.value.code == status
