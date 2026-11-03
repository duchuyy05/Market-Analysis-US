"""The user's null-content/token-limit failure must recover, not replay forever."""
import copy
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from market_research.common import read_json
from market_research.config import validate_config
from market_research.llm.client import complete, decode_response
from market_research.pipeline import execute
from market_research.providers.client import BudgetExceeded, Client, SourceError
from market_research.storage.run import Run


def config(**updates):
    return validate_config({"brief": "Meaningful year-end gifts for parents and partner", "sources": {"web": False},
        "business": {"profile": "general", "categories": []},
        "limits": {"candidate_keywords": 32, "retry_attempts": 0, "llm_requests": 10, "free_trends_requests": 0, "trends_serpapi_requests": 0, "related_seeds_per_niche": 0}, **updates})


def plan():
    return {"category": "Meaningful year-end gifts", "niches": [{"name": "Parents", "seeds": ["heated throw", "tea sampler"]}], "selling_months": [11, 12]}


def response(value):
    return {"model": "fixture/json:free", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}


def exhausted():
    return {"model": "fixture/reasoning:free", "choices": [{"finish_reason": "length", "message": {"content": None}}],
            "usage": {"completion_tokens": 5000, "completion_tokens_details": {"reasoning_tokens": 5000}}}


def test_two_empty_models_regenerate_distinct_request_and_invalidate_cache(tmp_path):
    cfg = config(llm={"model": "fixture/primary:free"})
    run, calls = Run("two-empty", tmp_path), []
    def transport(provider, params):
        assert provider == "openrouter"
        calls.append(copy.deepcopy(params))
        return exhausted() if len(calls) < 3 else response(plan())
    result = complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert result["category"] == plan()["category"]
    assert len(calls) == len(run.manifest["usage"]) == 3
    assert all(p["reasoning"]["enabled"] is False for p in calls)
    assert calls[1]["messages"] != calls[2]["messages"]
    raw = [read_json(p) for p in (run.path / "raw/openrouter").glob("*.json")]
    assert sum(bool(r.get("validation_error")) for r in raw) >= 2
    events = (run.path / "events.jsonl").read_text(encoding="utf-8")
    assert '"kind": "token_limit"' in events and '"event": "llm_regenerate"' in events


def test_failed_understand_resumes_without_replaying_empty_cache_or_resetting_usage(tmp_path):
    cfg, calls = config(), []
    def bad(provider, params):
        calls.append(provider)
        return exhausted()
    with pytest.raises(RuntimeError, match="token"):
        execute(cfg, root=tmp_path, run_id="resume-llm", transport=bad, event=lambda _: None)
    failed = Run("resume-llm", tmp_path)
    original_hash = failed.manifest["input_hash"]
    original_usage = copy.deepcopy(failed.manifest["usage"])
    count = len(calls)
    def recovered(provider, params):
        assert provider == "openrouter", "No downstream provider before valid understanding"
        calls.append(provider)
        payload = json.loads(params["messages"][1]["content"])
        if "existing_keywords" in payload:
            # Discovery can expand a small pool after understanding succeeds.
            # A valid empty expansion must not exercise schema repair here.
            return response({"candidates": []})
        return response(plan())
    run = execute(root=tmp_path, run_id=failed.id, transport=recovered, event=lambda _: None)
    assert run.manifest["input_hash"] == original_hash
    assert run.manifest["usage"][:len(original_usage)] == original_usage
    resumed_usage = run.manifest["usage"][len(original_usage):]
    assert [item["purpose"] for item in resumed_usage] == ["llm_understand", "llm_expand"]
    assert len(calls) == count + 2
    assert run.manifest["stages"]["understand"]["status"] == "complete"
    assert run.manifest["status"] == "awaiting_trends"
    assert run.stage_data("normalized_config")["niches"][0]["seeds"] == plan()["niches"][0]["seeds"]


def test_json_plan_with_bad_month_is_repaired_before_workflow_accepts_it(tmp_path):
    cfg, calls = config(), []
    run = Run("schema-repair", tmp_path)
    def transport(provider, params):
        calls.append(params)
        return response({**plan(), "selling_months": [13]}) if len(calls) == 1 else response(plan())
    result = complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert result["selling_months"] == [11, 12]
    assert len(calls) == 2 and len(calls[1]["messages"]) == 4
    assert any(r.get("validation_error") for r in [read_json(p) for p in (run.path / "raw/openrouter").glob("*.json")])


def test_budget_exhaustion_during_recovery_keeps_real_error(tmp_path):
    cfg = config(limits={"llm_requests": 1, "retry_attempts": 0})
    run, calls = Run("budget", tmp_path), []
    def transport(provider, params):
        calls.append(provider)
        return exhausted()
    with pytest.raises(BudgetExceeded, match="openrouter"):
        complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert len(calls) == 1


def test_actual_auth_failure_does_not_become_invalid_json(tmp_path):
    cfg = config()
    run = Run("auth", tmp_path)
    def transport(provider, params):
        raise HTTPError("https://openrouter.ai", 401, "Unauthorized", {}, None)
    with pytest.raises(SourceError, match="401"):
        complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert len(run.manifest["usage"]) == 1


def test_provider_rate_limit_explanation_is_preserved_and_secret_scrubbed(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-secret-do-not-print")
    cfg = config()
    run = Run("rate-limit", tmp_path)
    def transport(provider, params):
        body = {"error": {"code": 429, "message": "Daily free limit reached fixture-secret-do-not-print", "metadata": {"provider_name": "Fixture"}}}
        raise HTTPError("https://openrouter.ai", 429, "Limited", {}, BytesIO(json.dumps(body).encode()))
    with pytest.raises(SourceError, match="Daily free limit reached"):
        complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    raw = next((run.path / "raw/openrouter").glob("*.json")).read_text(encoding="utf-8")
    assert "fixture-secret-do-not-print" not in raw and "[REDACTED]" in raw
    assert read_json(next((run.path / "raw/openrouter").glob("*.json")))["provider_error"]["provider_name"] == "Fixture"


def test_visible_text_blocks_are_accepted_without_reading_reasoning():
    result = decode_response("understand", {"response": {"choices": [{"message": {"content": [
        {"type": "reasoning", "text": "not user-visible output"}, {"type": "text", "text": json.dumps(plan())}]}}]}}, {"brief": "Gifts"}, "openrouter/free")
    assert result["category"] == plan()["category"]


def test_mandatory_reasoning_model_is_skipped_and_fallback_varies_vendor(tmp_path, monkeypatch):
    from market_research.llm import models
    from test_llm_models import row
    metadata = [row("fixture/mandatory:free", reasoning={"mandatory": True}), row("a/first:free"), row("a/second:free"), row("b/other:free")]
    monkeypatch.setattr(models, "catalog", lambda _: metadata)
    calls = []
    cfg = config(llm={"model": "fixture/mandatory:free"})
    def transport(provider, params):
        calls.append(params["model"])
        if len(calls) == 1:
            raise HTTPError("https://openrouter.ai", 429, "Upstream limited", {}, None)
        return response(plan())
    run = Run("model-compatibility", tmp_path)
    result = complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert result["category"] == plan()["category"]
    assert calls == ["a/first:free", "b/other:free"]


def test_no_model_catalog_http_when_completion_budget_is_zero(tmp_path, monkeypatch):
    from market_research.llm import models
    def forbidden(_):
        pytest.fail("No metadata network when no completion budget remains")
    monkeypatch.setattr(models, "catalog", forbidden)
    cfg = config(limits={"llm_requests": 0})
    run = Run("zero-llm", tmp_path)
    with pytest.raises(BudgetExceeded):
        complete(Client(run, cfg, lambda *_: pytest.fail("No completion request at zero budget")), "understand", {"brief": cfg["brief"]})


@pytest.mark.parametrize("body", [{"choices": {}}, {"choices": ["bad"]}, {"choices": [{"message": "bad"}]}, []])
def test_invalid_provider_shape_is_a_classified_output_error(body):
    from market_research.llm.client import InvalidOutput
    with pytest.raises(InvalidOutput):
        decode_response("understand", {"response": body}, {"brief": "Gifts"}, "openrouter/free")
