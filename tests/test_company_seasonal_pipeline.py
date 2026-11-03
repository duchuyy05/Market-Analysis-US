"""One complete company/Q4 workflow, with fake sources and no paid requests."""
import hashlib
from datetime import date, datetime, timedelta, timezone

from market_research.config import validate_config
from market_research.pipeline import execute, rebuild
from market_research.providers.client import Client
from market_research.reporting.document import Document
from market_research.storage.run import Run
from market_research.common import identity


def cfg():
    return validate_config({"brief": "Printed Christmas gifts for students' partners and parents", "as_of_date": "2026-10-30",
        "selling_months": [11, 12], "history_years": [2023, 2024, 2025], "target_year": 2026,
        "niches": [{"name": "Printed practical gifts", "seeds": ["printed t shirt", "tote bag", "wall calendar", "phone case", "hand cream", "electric kettle"]}],
        "llm": {"enabled": False}, "sources": {"web": False, "shopping": False},
        "trends": {"provider": "serpapi", "history_scope": "seasonal", "history_months": [10, 11, 12]},
        "limits": {"candidate_keywords": 4, "monthly_keywords": 4, "top_keywords": 2, "product_details": 0,
                   "serpapi_requests": 20, "trends_serpapi_requests": 10, "serpapi_product_reserve": 8, "retry_attempts": 0}})


def source(calls):
    def send(provider, params):
        calls.append((provider, params))
        assert provider == "serpapi"
        if params["engine"] == "google_trends":
            assert params["data_type"] == "TIMESERIES"
            start, end = [date.fromisoformat(value) for value in params["date"].split()]
            assert start.month == 10 and start.day == 1 and end.month == 12 and end.day == 31
            assert start.year == end.year and start.year in {2023, 2024, 2025}
            rows, day = [], start
            while day <= end:
                rows.append({"timestamp": str(int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp())),
                    "values": [{"query": query, "extracted_value": 20 if query == "gift basket" else 40 + index + day.month - 10}
                               for index, query in enumerate(params["q"].split(","))]})
                day += timedelta(days=1)
            return {"interest_over_time": {"timeline_data": rows}}
        assert params["engine"] == "amazon"
        token = hashlib.sha256(params["k"].encode()).hexdigest()[:7].upper()
        return {"organic_results": [
            {"asin": "B0" + token + "A", "title": params["k"], "extracted_price": 15, "sponsored": False, "bought_last_month": "100+ bought in past month"},
            {"asin": "B0" + token + "B", "title": params["k"] + " gift bundle with hand cream", "extracted_price": 20, "sponsored": False}]}
    return send


def test_only_q4_requests_and_company_products_reach_ideas(tmp_path, monkeypatch):
    calls = []
    run = execute(cfg(), run_id="company-q4", root=tmp_path, transport=source(calls), event=lambda _: None)
    data = run.load_dataset()
    assert data["config"]["business"]["profile"] == "custom_manufacturing"
    assert len([p for _, p in calls if p["engine"] == "google_trends"]) == 3
    assert run.manifest["stages"]["screen"]["status"] == "complete"
    assert data["selection"]["selection_basis"] == "selected_month_observations"
    assert not any(k["text"] in {"hand cream", "electric kettle"} for k in data["keywords"])
    assert data["ideas"] and all(p["business_fit"]["status"] == "allowed" for p in data["products"])
    assert all("hand cream" not in p["title"] for p in data["products"])
    assert any("hand cream" in p["title"] for p in data["search_occurrences"])
    assert any(item.get("kind") == "company_domain" for item in data["exclusions"])
    for history in data["keyword_histories"]:
        assert len(history["monthly"]) == 9
        assert {row["month"] for row in history["monthly"]} == {10, 11, 12}
        assert history["metric_unit"] == "anchor_100"
        assert max(row["value"] for row in history["monthly"]) > 100
        assert {row["month"] for row in history["forecast"]} == {10, 11, 12}
        assert history["validation"]["folds"][0]["months_tested"] == 3
    assert (run.output / "tables/product_exclusions.csv").is_file()
    before = list(run.manifest["usage"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Stored report rebuild cannot call a source")
    monkeypatch.setattr(Client, "request", forbidden)
    rebuilt = rebuild(run.id, root=tmp_path)
    assert rebuilt.manifest["usage"] == before
    assert all(h["analysis_scope"] == "selected_months" and len(h["forecast"]) == 3 for h in rebuilt.load_dataset()["histories"])


def test_seasonal_charts_keep_values_above_100_and_label_the_unit():
    doc = Document()
    months = [{"year": 2025, "month": m, "value": value, "status": "complete"} for m, value in ((10, 200), (11, 250), (12, 220))]
    doc.historical_chart("Q4 tote bag", months, [2025], "anchor_100")
    assert doc.blocks[0]["y_max"] == 250
    _, html = doc.render("Seasonal", "Fixture only")
    assert "anchor = 100" in html and "250" in html
    assert '435,54.00' in html  # Oct200/250, rather than clipping to100


def test_zero_budget_waits_at_season_history_without_any_product_request(tmp_path):
    value=cfg()
    value["limits"].update(serpapi_requests=0,trends_serpapi_requests=0,free_trends_requests=0)
    calls=[]
    run=execute(value,run_id="seasonal-zero",root=tmp_path,transport=source(calls),event=lambda _:None)
    assert calls==[] and run.manifest["status"]=="awaiting_trends"
    assert run.manifest["current_stage"]=="screen"
    assert run.manifest["stages"]["screen"]["status"]=="waiting"


def test_resume_replaces_legacy_skipped_screen_without_resetting_usage_or_refetching(tmp_path):
    calls = []
    first = execute(cfg(), run_id="legacy-season-screen", root=tmp_path, transport=source(calls), event=lambda _: None)
    original_hash, original_usage, before = first.manifest["input_hash"], list(first.manifest["usage"]), len(calls)
    first.checkpoint("screen", {"status": "skipped", "method": "selected_season_history_only", "rows": []})
    first.manifest["stages"]["screen"]["status"] = "skipped"
    first.save()
    resumed = execute(run_id=first.id, root=tmp_path, transport=source(calls), event=lambda _: None)
    assert resumed.manifest["stages"]["screen"]["status"] == "complete"
    assert resumed.stage_data("screen")["method"] == "selected_months_observed_interest_v1"
    assert resumed.manifest["input_hash"] == original_hash
    assert resumed.manifest["usage"] == original_usage and len(calls) == before
    assert "legacy_seasonal_screen_replaced" in (resumed.path / "events.jsonl").read_text(encoding="utf-8")


def test_frozen_legacy_run_keeps_its_original_domain_and_hash(tmp_path):
    value=validate_config({"brief":"Legacy skin care", "niches":[{"name":"Legacy", "seeds":["hand cream"]}],
        "llm":{"enabled":False},"sources":{"trends":False,"amazon":False,"shopping":False,"web":False}})
    value.pop("business")
    run=Run("legacy-domain",tmp_path)
    original_hash=identity("config",value)
    run.manifest.update(input=value,input_hash=original_hash)
    run.save()
    def forbidden(*args,**kwargs):
        raise AssertionError("No source configured")
    result=execute(run_id=run.id,root=tmp_path,transport=forbidden,event=lambda _:None)
    assert result.manifest["input_hash"]==original_hash and "business" not in result.manifest["input"]
    assert result.load_dataset()["config"]["business"]["profile"]=="general"
    assert not result.manifest["usage"]
