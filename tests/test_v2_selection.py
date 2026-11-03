import pytest

from market_research.common import read_json
from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.workflow.selection import select
from test_v2_workflow import fixture_transport


def direction(niche, keyword):
    return {"id": niche + "-" + keyword, "niche_id": niche, "keyword_id": "K-" + keyword, "keyword": keyword, "search_query": keyword}


def test_selection_caps_unique_queries_and_preserves_shared_niche_contexts():
    rows = [direction("A", "desk organizer"), direction("B", "desk organizer"), direction("C", "kitchen organizer"), direction("A", "desk tray")]
    result = select({"limits": {"top_keywords": 2}}, rows)
    assert result["selected_keywords"] == 2
    assert result["available_keywords"] == 3
    assert len(result["directions"]) == 3
    assert {row["niche_id"] for row in result["directions"]} == {"A", "B", "C"}
    assert result["rows"][0]["search_order"] == result["rows"][1]["search_order"] == 1
    assert result["rows"][-1]["selected"] is False
    assert result["is_trends_hot_ranking"] is False


def test_legacy_selection_without_cap_preserves_all_queries():
    rows = [direction("A", "desk organizer"), direction("B", "kitchen organizer")]
    assert select({"limits": {}}, rows)["directions"] == rows
    assert select({"limits": {"top_keywords": 10}}, rows)["selected_keywords"] == 2


@pytest.mark.parametrize("value", [0, 101, True, 1.5, "5"])
def test_invalid_top_keyword_limits_are_rejected(value):
    with pytest.raises(ValueError):
        validate_config({"brief": "Gifts", "limits": {"top_keywords": value}})


def test_top_keyword_limit_reduces_real_product_query_attempts(tmp_path):
    calls = []
    config = validate_config({"brief": "Organizers", "business": {"profile": "general", "categories": []}, "discovery": {"enabled": False}, "trends": {"provider": "serpapi"}, "sources": {"web": False, "shopping": True}, "limits": {"top_keywords": 1}})
    run = execute(config, root=tmp_path, run_id="top-one", transport=fixture_transport(calls), event=lambda _: None)
    data = read_json(run.path / "dataset.json")
    assert data["config"]["limits"]["top_keywords"] == 1
    assert data["selection"]["selected_keywords"] == 1
    assert len(data["directions"]) == 1
    assert sum(row["selected"] for row in data["keyword_selection"]) == 1
    for engine in ("amazon", "google_shopping"):
        assert sum(provider == "serpapi" and params.get("engine") == engine for provider, params in calls) == 1
    assert sum(params.get("data_type") == "TIMESERIES" for _, params in calls) == 1
    assert (run.output / "tables/keyword_selection.csv").exists()
    assert "chưa phải Top độ hot" in (run.output / "report.md").read_text(encoding="utf-8")
