import csv
import io
import json
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from market_research.common import read_json, write_json
from market_research.storage.run import Run
from market_research.ui.workspace import Workspace
from test_v2_http import app
from test_v2_workflow import fixture_transport


def post(base, path, body):
    request = Request(base + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "X-Research-Client": "local"})
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def get(base, path):
    with urlopen(base + path, timeout=10) as response:
        return json.load(response)


def seed(manager):
    run = Run("products-test", manager.root)
    run.manifest.update(mode="offline", status="partial", summary={"category": "Q4 samples"})
    run.save()
    rows = []
    for pid, title, price, reviews in [("P-ten", "Ten dollar sample", 10, 0), ("P-two", "=Unsafe CSV formula", 2, 100), ("P-none", "Unknown price", None, None)]:
        rows.append({"product_id": pid, "title": title, "price": price, "currency": "USD", "rating": 4.5, "review_count": reviews,
                     "source": "amazon", "merchant": "Amazon.com", "asin": "B012345678", "url": "https://amazon.com/dp/B012345678",
                     "observed_at": "2026-10-22T00:00:00Z", "evidence_ids": ["E-source"]})
    write_json(run.path / "dataset.json", {"products": rows})
    (run.output / "report.md").write_text("# Original report\nOriginal evidence", encoding="utf-8")
    (run.output / "report.html").write_text("<h1>Original report</h1>", encoding="utf-8")
    return run


def test_product_sort_filter_csv_and_missing_values(app):
    base, manager = app
    seed(manager)
    query = "/api/products?" + urlencode({"sort": "price", "order": "asc"})
    rows = get(base, query)["items"]
    assert [r["product_id"] for r in rows] == ["P-two", "P-ten", "P-none"]
    descending = get(base, "/api/products?sort=price&order=desc")["items"]
    assert [r["product_id"] for r in descending] == ["P-ten", "P-two", "P-none"]
    assert get(base, "/api/products?min_price=5&max_price=15")["total"] == 1
    assert get(base, "/api/products?q=unknown")["total"] == 1
    with urlopen(base + "/api/products/export.csv?sort=price&order=asc") as response:
        raw = response.read()
        assert response.headers.get_content_type() == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
    assert raw.startswith(b"\xef\xbb\xbf")
    exported = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert exported[0]["Sản phẩm"].startswith("'=Unsafe")
    assert exported[0]["Giá"] == "2"
    assert exported[-1]["Giá"] == ""
    assert exported[1]["Lượt đánh giá"] == "0"
    assert exported[0]["Mã bằng chứng"] == "E-source"


def test_saved_items_survive_workspace_reload(app):
    base, manager = app
    run = seed(manager)
    post(base, "/api/workspace/save", {"kind": "run", "run_id": run.id, "saved": True})
    post(base, "/api/workspace/save", {"kind": "product", "run_id": run.id, "product_id": "P-ten", "saved": True})
    assert get(base, "/api/runs")[0]["saved"] is True
    assert get(base, "/api/products?saved=1")["items"][0]["product_id"] == "P-ten"
    state = Workspace(manager.root).state()
    assert state["saved_runs"] == [run.id]
    assert state["saved_products"] == [run.id + ":P-ten"]
    post(base, "/api/workspace/save", {"kind": "product", "run_id": run.id, "product_id": "P-ten", "saved": False})
    assert get(base, "/api/products?saved=1")["total"] == 0


def test_multi_sort_priority_ties_missing_values_and_csv(app):
    base, manager = app
    run = seed(manager)
    template = read_json(run.path / "dataset.json")["products"][0]
    cases = [
        ("high-expensive", 5, 30, 50),
        ("high-cheap", 5, 10, 10),
        ("low-cheap", 4.5, 2, 100),
        ("unknown-rating", None, 1, None),
        ("high-unknown-price", 5, None, 20),
        ("high-cheap-popular", 5, 10, 80),
    ]
    rows = [{**template, "product_id": pid, "title": pid, "rating": rating, "price": price, "review_count": reviews} for pid, rating, price, reviews in cases]
    write_json(run.path / "dataset.json", {"products": rows})
    rules = [{"field": "rating", "order": "desc"}, {"field": "price", "order": "asc"}, {"field": "review_count", "order": "desc"}]
    query = urlencode({"sorts": json.dumps(rules)})
    result = get(base, "/api/products?" + query)["items"]
    expected = ["high-cheap-popular", "high-cheap", "high-expensive", "high-unknown-price", "low-cheap", "unknown-rating"]
    assert [row["product_id"] for row in result] == expected
    with urlopen(base + "/api/products/export.csv?" + query) as response:
        exported = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
    assert [row["Sản phẩm"] for row in exported] == expected
    reversed_rules = [{"field": "price", "order": "asc"}, {"field": "rating", "order": "desc"}]
    other = get(base, "/api/products?" + urlencode({"sorts": json.dumps(reversed_rules)}))["items"]
    assert other[0]["product_id"] == "unknown-rating"
    assert other[-1]["product_id"] == "high-unknown-price"


@pytest.mark.parametrize("rules", [
    "invalid-json", "[]", "null",
    '[{"field":"rating","order":"desc"},{"field":"rating","order":"asc"}]',
    '[{"field":"price","order":"sideways"}]',
    '[{"field":"secret","order":"asc"}]',
])
def test_multi_sort_rejects_invalid_criteria(app, rules):
    base, _ = app
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/api/products?" + urlencode({"sorts": rules}))
    assert error.value.code == 400


def test_editor_preserves_original_escapes_content_and_keeps_versions(app, monkeypatch):
    # Windows clock resolution may give two explicit saves the same timestamp.
    monkeypatch.setattr("market_research.ui.workspace.now", lambda: "2026-10-28T00:00:00+00:00")
    base, manager = app
    run = seed(manager)
    original = (run.output / "report.md").read_bytes()
    assert get(base, f"/api/runs/{run.id}/editor")["content"].startswith("# Original")
    content = '# My report\n<script>alert("unsafe")</script>\n\n| Name | Price |\n| --- | --- |\n| Item | 2 |'
    post(base, f"/api/runs/{run.id}/editor", {"title": "My edited report", "content": content})
    post(base, f"/api/runs/{run.id}/editor", {"title": "Second title", "content": content + "\nSecond save"})
    assert (run.output / "report.md").read_bytes() == original
    html = (run.output / "report-edited.html").read_text(encoding="utf-8")
    assert '<script>alert("unsafe")</script>' not in html
    assert "&lt;script&gt;" in html
    assert "<table>" in html
    assert len(list((run.path / "edits").glob("*.json"))) == 2
    assert get(base, f"/api/runs/{run.id}/editor")["edited"] is True
    assert get(base, "/api/runs")[0]["user_title"] == "Second title"
    assert get(base, "/api/runs")[0]["saved"] is True


@pytest.mark.parametrize("query", ["sort=invalid", "min_price=nan", "min_price=20&max_price=1", "page=0", "run_id=..%2F..%2Fapi"])
def test_product_query_validation(app, query):
    base, _ = app
    with pytest.raises(HTTPError) as error:
        urlopen(base + "/api/products?" + query)
    assert error.value.code == 400


def test_stop_endpoint_waits_for_inflight_request_and_does_not_start_another(app, monkeypatch):
    from market_research.ui import server as ui_server
    base, manager = app
    entered, release = threading.Event(), threading.Event()
    calls = []
    real_execute = ui_server.execute
    transport = fixture_transport(calls)

    def blocked(provider, params):
        entered.set()
        assert release.wait(5)
        return transport(provider, params)

    monkeypatch.setattr(ui_server, "execute", lambda *args, **kwargs: real_execute(*args, transport=blocked, **kwargs))
    config = {"brief": "Desk organizer", "niches": [{"name": "Desk", "seeds": ["desk organizer"]}], "llm": {"enabled": False}, "sources": {"web": False}, "discovery": {"enabled": False}, "trends": {"provider": "serpapi"}}
    run_id = post(base, "/api/runs", config)["run_id"]
    try:
        assert entered.wait(3)
        result = post(base, f"/api/runs/{run_id}/stop", {})
        assert result["status"] == "cancelling"
        assert get(base, f"/api/runs/{run_id}")["status"] == "cancelling"
    finally:
        release.set()
    manager.jobs[run_id].result(timeout=10)
    state = get(base, f"/api/runs/{run_id}")
    assert state["status"] == "cancelled"
    assert state["errors"] == []
    assert len(calls) == 1
    assert state["request_counts"]["serpapi"] == 1
    assert state["can_stop"] is False
    assert read_json(manager.root / "data/runs" / run_id / "manifest.json")["input"]["limits"]["serpapi_requests"] == 20
