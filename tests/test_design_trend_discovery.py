"""Exact design discovery, selected dates and evidence stay together; no live sources."""
import json
import pytest

from market_research.config import validate_config
from market_research.providers import trends
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import broad, selection, web_discovery
from market_research.workflow.trend_queries import discovery_period_query, research_period, design_intent, product_context


def config(**changes):
    return validate_config({"brief": "Which singer prints on shirts for November?", "category": "Singer shirt prints",
        "as_of_date": "2026-10-30", "selling_months": [11], "history_years": [2023, 2024, 2025],
        "business": {"profile": "custom_manufacturing", "categories": ["apparel"]},
        "niches": [{"id": "N", "name": "Singer shirts", "seeds": ["graphic t shirt"]}],
        "trends": {"history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        "llm": {"enabled": False}, "sources": {"web": False}, **changes})


def test_related_discovery_uses_the_same_selected_month_and_keeps_design_keyword(tmp_path, monkeypatch):
    cfg=config()
    run=Run("related-design",tmp_path)
    run.manifest["input"]=cfg
    calls=[]
    def related(client,query,cutoff,date_range=None):
        calls.append((query,date_range))
        return {"parameters":{"date":date_range},"retrieved_at":"2026-10-30T00:00:00+00:00","raw_file":"raw/fixture.json",
                "response":{"related_queries":{"rising":[{"query":"Taylor Swift t shirt","value":"Breakout"}]}}}
    monkeypatch.setattr(trends,"related",related)
    result=broad.discover(run,Client(run,cfg),cfg)
    assert calls == [("graphic t shirt","2025-11-01 2025-11-30")]
    candidate=next(k for k in result["keywords"] if k["text"]=="Taylor Swift t shirt")
    assert candidate["evidence_state"]=="source_observed"
    assert candidate["discovery_window"]=="2025-11-01 2025-11-30"


def test_web_discovery_search_and_extraction_include_the_requested_month_and_year(tmp_path):
    cfg=config(llm={"enabled":True},sources={"web":True,"trends":False},discovery={"sites":["etsy"]})
    run=Run("web-design",tmp_path)
    calls=[]
    def send(provider,params):
        calls.append((provider,params))
        if provider=="tavily":
            return {"results":[{"title":"Taylor Swift t shirt","url":"https://etsy.com/listing/singer-shirt",
                                "content":"Taylor Swift t shirt with a concert-inspired print.","published_date":"2025-11-15"}]}
        payload=json.loads(params["messages"][1]["content"])
        assert payload["research_period"]["months"]==[11]
        assert payload["research_period"]["analysis_year"]==2025
        assert payload["research_brief"]==cfg["brief"]
        return {"choices":[{"message":{"content":json.dumps({"candidates":[{"keyword":"Taylor Swift t shirt",
            "quote":"Taylor Swift t shirt with a concert-inspired print.","niche_id":"N","source_id":payload["pages"][0]["id"]}]})}}]}
    found=[]
    contexts,states,excluded=web_discovery.harvest(run,Client(run,cfg,send),cfg,{"N":cfg["niches"][0]},lambda *args:found.append(args) or True)
    assert found[0][0]=="Taylor Swift t shirt" and found[0][2]=="public_web"
    query=next(params["query"] for provider,params in calls if provider=="tavily")
    assert "November" in query and "2025" in query
    assert contexts and not excluded and states[0]["status"]=="available"


def test_related_adapter_accepts_an_exact_window_without_broadening_it():
    class Stub:
        config={"trends":{"provider":"serpapi"}}
        def request(self,provider,params,purpose=None):
            assert params["date"]=="2025-11-01 2025-11-30"
            return {"parameters":params,"response":{"related_queries":{"top":[{"query":"fox wrapping paper"}]}}}
    trends.related(Stub(),"wrapping paper","2026-10-30",date_range="2025-11-01 2025-11-30")


def test_exact_designs_keep_separate_top_slots_and_analysis_evidence():
    cfg=config(limits={"top_keywords":2})
    keywords=[{"id":str(i),"text":name+" t shirt","niche_id":"N","evidence_ids":[]}
              for i,name in enumerate(["Taylor Swift","Sabrina Carpenter"])]
    measured={"method":"selected_months_observed_interest_v1","note":"Observed selected month.",
        "analysis_year":2025,"screening_scope":"selected_months","selection_basis":"selected_month_observation",
        "analysis_windows":[{"year":2025,"months":[11],"start":"2025-11-01","end":"2025-11-30"}],
        "rows":[{"keyword_id":k["id"],"keyword":k["text"],"measurement_query":k["text"],"measurement_scope":"exact_keyword",
                 "rank":i+1,"score":100-i,"evidence_ids":["E"+str(i)],"observed_days":30,
                 "analysis_observations":[{"year":2025,"month":11,"value":40-i}]} for i,k in enumerate(keywords)]}
    result=selection.ranked(cfg,{"keywords":keywords},measured,[])
    assert result["selected_keywords"]==result["trends_verified_keywords"]==2
    assert {d["search_query"] for d in result["directions"]}=={k["text"] for k in keywords}
    assert all(d["analysis_year"]==2025 and d["analysis_windows"][0]["months"]==[11] for d in result["directions"])
    assert all(d["observed_days"]==30 and d["analysis_observations"] for d in result["directions"])


def test_single_selected_month_does_not_become_christmas_or_all_year():
    cfg=config(selling_months=[7],trends={"history_scope":"seasonal","history_months":[7],"analysis_year":2025})
    assert research_period(cfg)["months"]==[7]
    assert discovery_period_query(cfg)=="United States July 2025"


def test_context_seeds_do_not_fill_the_design_candidate_cap_before_expansion(tmp_path):
    cfg=config(sources={"web":False,"trends":False},llm={"enabled":True},
        limits={"candidate_keywords":1,"llm_requests":1,"retry_attempts":0})
    run=Run("expand-after-context",tmp_path)
    run.manifest["input"]=cfg
    calls=[]
    def send(provider,params):
        assert provider=="openrouter"
        payload=json.loads(params["messages"][1]["content"])
        calls.append(payload)
        assert payload["existing_keywords"]==[] and payload["maximum"]==1
        return {"choices":[{"message":{"content":json.dumps({"candidates":[{"keyword":"Taylor Swift t shirt",
            "niche_id":"N","reason":"Giả thuyết hình in cần đo vào tháng đã chọn"}]})}}]}
    result=broad.discover(run,Client(run,cfg,send),cfg)
    assert len(calls)==1
    assert [k["text"] for k in result["keywords"]]==["Taylor Swift t shirt"]
    assert [k["text"] for k in result["product_context_keywords"]]==["graphic t shirt"]
    assert any(row["kind"]=="product_context" and row["keyword"]=="graphic t shirt" for row in result["exclusions"])


@pytest.mark.parametrize("required",[True,False])
def test_bare_product_cannot_win_a_design_top_slot_including_legacy_optional_runs(required):
    cfg=config(limits={"top_keywords":1})
    cfg["trends"]["required"]=required
    keywords=[{"id":str(i),"text":word,"niche_id":"N","evidence_ids":[]}
              for i,word in enumerate(["t shirt","Taylor Swift t shirt"])]
    measured={"method":"test","note":"Source observations.","rows":[{"keyword_id":k["id"],"keyword":k["text"],
        "measurement_query":k["text"],"measurement_scope":"exact_keyword","rank":i+1,"score":100-i,"evidence_ids":[]}
        for i,k in enumerate(keywords)]}
    result=selection.ranked(cfg,{"keywords":keywords},measured,[])
    assert result["selected_keywords"]==result["trends_verified_keywords"]==1
    assert [d["search_query"] for d in result["directions"]]==["Taylor Swift t shirt"]
    generic=next(row for row in result["rows"] if row["keyword"]=="t shirt")
    assert generic["product_context"] and not generic["selected"] and generic["rank"] is None
    assert "chủ đề thiết kế" in generic["reason"]


def test_design_scope_guard_preserves_general_product_research_and_unknown_types():
    assert not design_intent({"brief":"Printed gifts for November"})
    assert not design_intent({"brief":"Practical gifts for artists in November"})
    assert not product_context("custom printed t shirt",{"brief":"Printed gifts for November"})
    cfg={"brief":"Which singer image should we print on a shirt?"}
    assert product_context("custom graphic t-shirt",cfg)
    assert product_context("singer t shirt",cfg)
    assert not product_context("Sabrina Carpenter t shirt",cfg)
    assert not product_context("woodland fox wrapping paper",cfg)
    assert not product_context("cat desk organizer",cfg)
    assert not product_context("cat shoelace aglet",cfg)  # Unknown types are not automatically discarded.
    assert not product_context("phone Taylor Swift case",cfg)
    assert not product_context("galaxy pattern wrapping paper",cfg)


def test_expansion_does_not_reintroduce_product_context_as_a_design(tmp_path):
    cfg=config(sources={"web":False,"trends":False},llm={"enabled":True},
        limits={"candidate_keywords":1,"llm_requests":1,"retry_attempts":0})
    run=Run("reject-expanded-context",tmp_path)
    run.manifest["input"]=cfg
    def send(provider,params):
        return {"choices":[{"message":{"content":json.dumps({"candidates":[{"keyword":"custom t shirt",
            "niche_id":"N","reason":"Giả thuyết mẫu in nhưng chưa có chủ đề cụ thể"}]})}}]}
    result=broad.discover(run,Client(run,cfg,send),cfg)
    assert result["keywords"]==[]
    assert any(row["keyword"]=="custom t shirt" and "thiếu chi tiết mẫu" in row["reason"] for row in result["exclusions"])
