"""Candidate-history orchestration has no implicit API expansion or fake ranks."""
from types import SimpleNamespace

import pytest

from market_research.common import identity
from market_research.workflow.monthly_keywords import analyze


def config(**changes):
    return {"mode": "live", "sources": {"trends": True}, "market": "US", "as_of_date": "2026-10-30", "target_year": 2026,
            "history_years": [2023, 2024, 2025], "selling_months": [11, 12],
            "trends": {"monthly_rankings": True, "anchor": "gift basket"},
            "limits": {"monthly_keywords": 64, "candidate_keywords": 64}, **changes}


def discovery():
    return {"keywords": [{"id": "A", "niche_id": "N1", "text": "gift a"}, {"id": "B", "niche_id": "N1", "text": "gift b"},
                         {"id": "C", "niche_id": "N2", "text": "gift c"}, {"id": "D", "niche_id": "N2", "text": "gift d"}]}


def run():
    return SimpleNamespace(log=lambda *_args, **_kwargs: None)


def response(directions, years=(2023, 2024, 2025)):
    return [{"direction_id": d["id"], "keyword_id": d["keyword_id"], "measurement_query": d["measurement_query"],
             "status": "available", "monthly": [{"year": year, "month": month, "status": "complete", "value": 20 + month, "positive_points": 4}
                 for year in years for month in range(1, 13)], "evidence_ids": ["E-" + d["keyword_id"]]} for d in directions]


@pytest.mark.parametrize("change", [{"trends": {"monthly_rankings": False}}, {"mode": "offline"}, {"sources": {"trends": False}}])
def test_disabled_offline_or_source_off_does_not_fetch(monkeypatch, change):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Monthly branch must not fetch while disabled")
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", unexpected)
    result = analyze(run(), None, config(**change), discovery(), {})
    assert result["status"] == "skipped" and result["histories"] == []
    assert result["rankings"]["rows"] == [] and result["requested_keywords"] == 0


def test_screen_leaders_are_requested_before_alternating_unranked_niches(monkeypatch):
    requested = []
    def collect(_run, _client, _config, directions, *, anchor):
        requested.extend(directions)
        assert anchor == "gift basket"
        return response(directions)
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", collect)
    cfg = config(limits={"monthly_keywords": 3, "candidate_keywords": 64})
    result = analyze(run(), None, cfg, discovery(), {"rows": [{"keyword_id": "B", "rank": 1}]})
    assert [d["keyword_id"] for d in requested] == ["B", "A", "C"]
    assert all(d["id"] == identity("D", d["niche_id"], d["keyword_id"]) for d in requested)
    assert result["requested_keywords"] == result["observed_keywords"] == 3
    assert result["rankings"]["coverage"]["candidate_keywords"] == 4
    assert result["status"] == "partial"  # fourth candidate is still explicitly unobserved


def test_shared_query_keeps_all_contexts_without_consuming_two_query_slots(monkeypatch):
    requested = []
    def collect(_run, _client, _config, directions, *, anchor):
        requested.extend(directions)
        return response(directions)
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", collect)
    pool = discovery()
    pool["keywords"][2]["text"] = "gift a"
    cfg = config(limits={"monthly_keywords": 2, "candidate_keywords": 64})
    result = analyze(run(), None, cfg, pool, {})
    assert len(requested) == 3  # A and C share one query, B is the second query.
    assert result["requested_keywords"] == result["observed_keywords"] == 2
    a = next(r for r in result["rankings"]["rows"] if r["measurement_query"] == "gift a")
    assert a["niche_ids"] == ["N1", "N2"]


def test_candidate_cap_is_respected_even_when_monthly_cap_is_larger(monkeypatch):
    def collect(_run, _client, _config, directions, *, anchor):
        assert len(directions) == 2
        return response(directions)
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", collect)
    cfg = config(limits={"monthly_keywords": 64, "candidate_keywords": 2})
    result = analyze(run(), None, cfg, discovery(), {})
    assert result["requested_keywords"] == result["target_keywords"] == 2


def test_screen_query_metadata_is_used_for_history_and_rankings(monkeypatch):
    def collect(_run, _client, _config, directions, *, anchor):
        assert directions[0]["measurement_query"] == "photo album"
        assert directions[0]["measurement_scope"] == "broader_product_type"
        return response(directions)
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", collect)
    pool = {"keywords": [{"id": "A", "text": "custom photo album for parents", "niche_id": "N"}]}
    result = analyze(run(), None, config(), pool, {"rows": [{"keyword_id": "A", "rank": 1, "measurement_query": "photo album", "measurement_scope": "broader_product_type"}]})
    assert result["rankings"]["rows"][0]["measurement_query"] == "photo album"


def test_observed_source_does_not_mean_enough_historical_cycles(monkeypatch):
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", lambda _r, _c, _cfg, ds, **_kw: response(ds, years=(2025,)))
    result = analyze(run(), None, config(), discovery(), {})
    assert result["observed_keywords"] == 4 and result["status"] == "partial"
    assert all(not m["rankings"] for m in result["rankings"]["months"])


def test_source_failures_do_not_become_empty_success(monkeypatch):
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", lambda _r, _c, _cfg, ds, **_kw: [
        {"direction_id": d["id"], "status": "unavailable", "monthly": [], "reason": "budget"} for d in ds])
    result = analyze(run(), None, config(), discovery(), {})
    assert result["status"] == "unavailable" and result["observed_keywords"] == 0
    assert all(r["seasonality_rank"] is None for r in result["rankings"]["rows"])


def test_tight_history_capacity_first_observes_a_screen_leader_not_the_first_niche(monkeypatch):
    def collect(_run, _client, _config, directions, *, anchor):
        assert directions[0]["keyword_id"] == "D"
        return response(directions[:1]) + [{"direction_id": d["id"], "status": "unavailable", "monthly": [], "reason": "budget"} for d in directions[1:]]
    monkeypatch.setattr("market_research.workflow.monthly_keywords.history.analyze", collect)
    result = analyze(run(), None, config(), discovery(), {"rows": [{"keyword_id": "D", "rank": 1}]})
    assert result["observed_keywords"] == 1 and result["status"] == "partial"
    available = [r for r in result["rankings"]["rows"] if r["seasonality_rank"] is not None]
    assert {r["keyword_id"] for r in available} == {"D"}
