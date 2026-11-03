import copy
import json
from pathlib import Path

import pytest

from market_research.common import read_json
from market_research.config import validate_config as current_config
from market_research.pipeline import execute, rebuild
from market_research.analysis.opportunities import constraints


def validate_config(value):
    """Keep legacy adapter coverage explicit; broad/free flow has separate tests."""
    return current_config({"business": {"profile": "general", "categories": []}, "discovery": {"enabled": False}, "trends": {"provider": "serpapi"}, **value,
                           "sources": {"shopping": True, **value.get("sources", {})}})


def fixture_transport(calls, shopping_empty=False):
    def request(provider, params):
        calls.append((provider, copy.deepcopy(params)))
        if provider == "openrouter":
            payload = json.loads(params["messages"][1]["content"])
            if "brief" in payload:
                value = {"category": "Home organization", "summary_vi": "Đồ sắp xếp nhà", "selling_months": [11, 12], "assumptions": [], "niches": [{"name": "Bàn học", "seeds": ["desk organizer"]}, {"name": "Bếp", "seeds": ["kitchen organizer"]}, {"name": "Tủ đồ", "seeds": ["closet organizer"]}]}
            else:
                seed = payload["keywords"][0]
                value = {"directions": [{"name": seed["text"], "representative_keyword_id": seed["id"], "keyword_ids": [k["id"] for k in payload["keywords"]]}]}
            return {"choices": [{"message": {"content": json.dumps(value)}}], "model": "fixture-model", "usage": {"cost": 0}}
        if params.get("data_type") == "RELATED_QUERIES":
            return {"related_queries": {"rising": [{"query": params["q"] + " bamboo", "value": "+200%", "link": "https://trends.google.com/trends/explore?q=test"}]}}
        if params.get("data_type") == "TIMESERIES":
            return {"interest_over_time": {"timeline_data": []}}
        if params.get("engine") == "amazon":
            prefix = params["k"].split()[0]
            asin = {"desk": "B012345671", "kitchen": "B012345672", "closet": "B012345673"}[prefix]
            return {"organic_results": [{"title": params["k"] + " bamboo", "asin": asin, "extracted_price": 20, "bought_last_month": "100+ bought in past month", "sponsored": False}]}
        if params.get("engine") == "google_shopping":
            return {"shopping_results": [] if shopping_empty else [{"title": params["q"] + " bamboo", "link": "https://shop.test/" + params["q"].replace(" ", "-"), "source": "Fixture merchant", "price": "$21", "extracted_price": 21, "sponsored": False}]}
        if params.get("engine") == "amazon_product":
            return {"product_results": {"title": "Example organizer", "extracted_price": 22, "bought_last_month": "100+ bought in past month"}, "product_specifications": {"material": "bamboo"}}
        if provider == "tavily":
            return {"results": []}
        raise AssertionError(params)
    return request


def test_description_runs_end_to_end_without_hand_selected_keywords(tmp_path):
    calls = []
    config = validate_config({"brief": "Tìm đồ sắp xếp nhà ở Mỹ", "sources": {"trends": True, "web": False}})
    run = execute(config, root=tmp_path, run_id="description", transport=fixture_transport(calls), event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert len(data["config"]["niches"]) == 3
    assert len(data["keywords"]) == 6
    assert any(k["origin"] == "provider_related" for k in data["keywords"])
    assert len(data["products"]) == 6
    assert all(len(i["evidence_ids"]) > 0 for i in data["ideas"])
    assert (run.output / "report.html").exists()
    assert (run.output / "catalog.html").exists()
    assert read_json(run.output / "validation.json")["errors"] == []
    assert "Lịch sử" in (run.output / "report.md").read_text(encoding="utf-8")
    assert sum(provider == "openrouter" for provider, _ in calls) == 4


def test_report_only_never_calls_provider(tmp_path):
    calls = []
    run = execute(validate_config({"brief": "Organizers", "sources": {"web": False}}), root=tmp_path, run_id="report-only", transport=fixture_transport(calls), event=lambda _: None)
    count = len(calls)
    usage = copy.deepcopy(run.manifest["usage"])
    input_hash = run.manifest["input_hash"]
    # DB remains authoritative after migration, even if a mirror goes missing.
    (run.path / "dataset.json").unlink()
    rebuild(run.id, tmp_path)
    assert len(calls) == count
    from market_research.storage.run import Run
    updated = Run(run.id, tmp_path)
    data = updated.load_dataset()
    assert updated.manifest["usage"] == usage
    assert updated.manifest["input_hash"] == input_hash
    assert data["analysis_revision"]["provider_requests"] == 0
    assert updated.stage_data("history") == data["histories"]
    assert read_json(run.output / "tables/ideas.json") == data["ideas"]
    assert read_json(run.output / "tables/forecasts.json") == [{"direction_id": h["direction_id"], **row, "evidence_ids": h.get("evidence_ids", [])} for h in data["histories"] for row in h["forecast"]]
    assert (run.output / "sources.json").exists()


def test_resume_invalidates_downstream_when_partial_source_recovers(tmp_path):
    calls = []
    cfg = validate_config({"brief": "Organizers", "sources": {"web": False}})
    first = execute(cfg, root=tmp_path, run_id="resume", transport=fixture_transport(calls, shopping_empty=True), event=lambda _: None)
    # Simulate a temporary missing response by marking only search partial.
    first.manifest["stages"]["search"]["status"] = "partial"
    first.save()
    from market_research.common import write_json
    # Remove empty response caches to emulate an expired failed provider response.
    for path in (first.path / "raw/serpapi").glob("*.json"):
        body = read_json(path)
        if body["parameters"].get("engine") == "google_shopping":
            body["error"] = "temporary fixture failure"
            write_json(path, body)
    resumed = execute(run_id=first.id, root=tmp_path, transport=fixture_transport(calls), event=lambda _: None)
    data = read_json(resumed.path / "dataset.json")
    assert len(data["products"]) == 6
    assert resumed.manifest["stages"]["ideas"]["attempts"] >= 1
    assert sum(p == "serpapi" and args.get("engine") == "amazon" for p, args in calls) == 3


def test_price_missing_is_pending_not_zero_or_pass():
    cfg = validate_config({"brief": "Products", "price_range": [10, 30]})
    p = {"title": "Toy", "description": "", "attributes": {}, "price": None, "currency": None}
    assert constraints(p, cfg)["status"] == "pending_verification"


def test_source_text_is_escaped_in_report(tmp_path):
    calls = []
    run = execute(validate_config({"brief": "<script>alert(1)</script>", "sources": {"web": False}}), root=tmp_path, run_id="escape", transport=fixture_transport(calls), event=lambda _: None)
    html = (run.output / "report.html").read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_resume_rejects_changed_config(tmp_path):
    cfg = validate_config({"brief": "Organizers", "sources": {"web": False}})
    run = execute(cfg, root=tmp_path, run_id="locked", transport=fixture_transport([]), event=lambda _: None)
    changed = {**cfg, "brief": "Other products"}
    with pytest.raises(ValueError, match="khóa"):
        execute(changed, root=tmp_path, run_id=run.id, event=lambda _: None)


def test_offline_does_not_relabel_archive_as_a_different_market_study(tmp_path):
    cfg = validate_config({"mode": "offline", "brief": "New products", "category": "Unrelated electronics"})
    with pytest.raises(RuntimeError, match="Offline"):
        execute(cfg, root=tmp_path, run_id="wrong-archive", event=lambda _: None)
