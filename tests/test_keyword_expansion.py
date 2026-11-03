"""Broad recall stays bounded and proposals never masquerade as market data."""
import json

from market_research.config import validate_config, DEFAULT_LIMITS
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import broad
from market_research.workflow.keyword_expansion import product_key


PRODUCTS = "candle warmer|weighted blanket|neck massager|electric kettle|tea sampler|coffee grinder|milk frother|travel tumbler|water bottle|desk lamp|book light|reading pillow|lap desk|laptop stand|phone stand|cable organizer|charging dock|wireless earbuds|bluetooth speaker|portable charger|tablet sleeve|pencil case|fountain pen|planner notebook|journal notebook|photo album|photo printer|picture ledge|memory box|jewelry box|ring dish|watch case|makeup organizer|pocket mirror|hair brush|beard comb|shaving kit|hand cream|body lotion|bath salts|bathrobe|house slippers|wool scarf|knitted gloves|beanie hat|thermal socks|heating pad|foot warmer|eye mask|lumbar cushion|seat cushion|bedside organizer|night light|alarm clock|kitchen timer|oven mitts|baking mat|measuring spoons|spice rack|food container|lunch bag|cutting board|serving tray|cheese board|coaster set|plant pot|watering can|bird feeder|garden gloves|pruning shears|yoga mat|resistance band|massage ball|insulated lunchbox|picnic blanket|card game|jigsaw puzzle|chess set|scrapbook kit|embroidery kit".split("|")


def cfg(**changes):
    return validate_config({"brief": "Practical Christmas gifts for a partner and parents, bought by students",
        "business": {"profile": "general", "categories": []},
        "category": "Practical Christmas gifts", "as_of_date": "2026-10-30", "selling_months": [11, 12],
        "sources": {"trends": False, "web": False}, "limits": {"candidate_keywords": 64, "retry_attempts": 0},
        "niches": [{"id": "N1", "name": "Daily use", "seeds": ["coffee mug"]},
                   {"id": "N2", "name": "Memories", "seeds": ["photo frame"]},
                   {"id": "N3", "name": "Comfort", "seeds": ["tea infuser"]}], **changes})


def prepare(tmp_path, config, transport):
    run = Run("broad-test", tmp_path)
    run.manifest.update(input=config, current_stage="discover")
    return run, Client(run, config, transport)


def envelope(candidates):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"candidates": candidates})}}]}


def test_default_breadth_increases_without_increasing_paid_caps():
    assert DEFAULT_LIMITS["candidate_keywords"] == 64
    assert DEFAULT_LIMITS["serpapi_requests"] == 20
    assert DEFAULT_LIMITS["trends_serpapi_requests"] == 8
    assert DEFAULT_LIMITS["llm_requests"] == 8


def test_expansion_reaches_64_with_two_bounded_calls_and_clear_hypothesis_origin(tmp_path):
    config = cfg(limits={"candidate_keywords": 64, "llm_requests": 2, "retry_attempts": 0})
    calls, cursor = [], [0]
    def send(provider, params):
        assert provider == "openrouter"
        payload = json.loads(params["messages"][1]["content"])
        calls.append(payload)
        words = PRODUCTS[cursor[0]:cursor[0] + payload["maximum"]]
        cursor[0] += len(words)
        return envelope([{"keyword": word, "niche_id": "N" + str(i % 3 + 1),
                          "reason": "Giả thuyết quà thiết thực, cần kiểm chứng bằng Trends và mẫu hàng"} for i, word in enumerate(words)])
    run, client = prepare(tmp_path, config, send)
    data = broad.discover(run, client, config)
    assert len(calls) == 2
    assert len(data["keywords"]) == 64
    assert data["summary"]["unique_product_types"] == 64
    assert data["summary"]["expanded_candidates"] == 61
    assert data["summary"]["source_backed_candidates"] == 0
    assert all(k["evidence_state"] == "hypothesis" and not k["evidence_ids"] for k in data["keywords"])
    assert all(k.get("proposal_reason") for k in data["keywords"] if k["origin"] == "llm_expansion")
    assert all(u["provider"] == "openrouter" for u in run.manifest["usage"])
    assert config["limits"]["serpapi_requests"] == 20
    replay = broad.discover(run, client, config)
    assert len(replay["keywords"]) == 64 and len(calls) == 2
    expansion = next(s for s in replay["discovery_sources"] if s["branch"] == "llm_expansion")
    assert expansion["cache_reused"] == 2


def test_expansion_rejects_variant_padding_unknown_niches_and_invented_popularity(tmp_path):
    config = cfg()
    calls = []
    rows = [{"keyword": word, "niche_id": niche, "reason": "Giả thuyết phù hợp người nhận"} for word, niche in [
        ("personalized coffee mugs", "N1"), ("coffee mug", "N1"), ("viral speaker", "N1"),
        ("gift article", "N2"), ("máy massage", "N3"), ("neck massager", "outside"), ("book light", "N1")]]
    def send(provider, params):
        calls.append(params)
        return envelope(rows)
    run, client = prepare(tmp_path, config, send)
    data = broad.discover(run, client, config)
    assert len(calls) == 2
    assert [k["text"] for k in data["keywords"] if k["origin"] == "llm_expansion"] == ["book light"]
    assert len(data["exclusions"]) >= 6
    assert data["summary"]["actual_candidates"] == 4
    assert any("4/64" in w for w in run.manifest["warnings"])


def test_small_scope_still_expands_distinct_designs_within_one_product_family(tmp_path):
    config = cfg(brief="Compare singer shirt designs for November", selling_months=[11],
        trends={"history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        niches=[{"id": "N1", "name": "Singer shirt prints", "seeds": ["graphic t shirt"]}],
        limits={"candidate_keywords": 4, "llm_requests": 1, "retry_attempts": 0})
    calls=[]
    def send(provider, params):
        assert provider == "openrouter"
        payload=json.loads(params["messages"][1]["content"])
        calls.append(payload)
        return envelope([{"keyword": name + " t shirt", "niche_id": "N1", "reason": "Chủ đề in giả thuyết cần đo đúng tháng đã chọn"}
                         for name in ["Taylor Swift", "Sabrina Carpenter", "Olivia Rodrigo"]])
    run, client = prepare(tmp_path, config, send)
    result = broad.discover(run, client, config)
    assert len(calls)==1 and calls[0]["research_period"]["months"] == [11]
    assert calls[0]["research_period"]["analysis_year"] == 2025
    assert len(result["keywords"]) == 3
    assert {k["text"] for k in result["keywords"]} >= {"Taylor Swift t shirt", "Sabrina Carpenter t shirt"}
    assert all(k["evidence_state"] == "hypothesis" for k in result["keywords"])
    assert result["product_context_keywords"][0]["text"] == "graphic t shirt"


def test_zero_model_budget_keeps_real_count_and_never_fills_with_fake_keywords(tmp_path):
    config = cfg(limits={"candidate_keywords": 64, "llm_requests": 0})
    def unexpected(*_):
        raise AssertionError("No request is allowed with a zero cap")
    run, client = prepare(tmp_path, config, unexpected)
    result = broad.discover(run, client, config)
    assert len(result["keywords"]) == 3
    assert result["summary"]["actual_candidates"] == 3
    expansion = next(s for s in result["discovery_sources"] if s["branch"] == "llm_expansion")
    assert expansion["status"] == "limited" and expansion["rounds"] == 0
    assert not run.manifest["usage"]


def test_product_key_collapses_cosmetic_and_plural_variants():
    assert product_key("personalized coffee mugs") == product_key("coffee mug")
    assert product_key("engraved jewelry boxes") != product_key("jewelry box")
    assert product_key("monogrammed jewelry boxes") != product_key("jewelry box")
    assert product_key("spiral bound calendar") != product_key("flip desk calendar")
    assert product_key("travel mug") != product_key("coffee mug")
    assert product_key("Taylor Swift t shirt") != product_key("Sabrina Carpenter t shirt")
    assert product_key("woodland fox wrapping paper") != product_key("floral wrapping paper")
