"""A valid plan wrapped in one array must not trigger a rate-limited repair."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from market_research.common import identity, write_json
from market_research.config import validate_config
from market_research.llm import models
from market_research.llm.client import InvalidOutput, complete, decode_response, json_object
from market_research.llm.saved_plan import recover_saved_plan
from market_research.pipeline import recover_understanding
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import understand
from test_llm_models import row


def recorded():
    return json.loads((Path(__file__).parent / "fixtures/understand-singleton-array-plan.json").read_text(encoding="utf-8"))


def config():
    return validate_config({"brief": "Year-end printed gifts: keychains, phone cases, wallets and graphic shirts",
        "as_of_date": "2026-11-03", "llm": {"model": "a/limited:free"},
        "limits": {"llm_requests": 3, "retry_attempts": 0}})


def envelope(payload, value=None):
    return {"provider": "openrouter", "validation_error": "Model trả nội dung chưa đúng JSON",
        "parameters": {"model": "b/working:free", "messages": [{"role": "user", "content": json.dumps(payload)}]},
        "response": {"model": "b/working:free", "choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(recorded() if value is None else value)}}]}}


@pytest.mark.parametrize("template", ["{}", "```json\n{}\n```", "Here is the plan:\n{}"])
def test_complete_singleton_wrapper_is_validated(template):
    cfg = config()
    saved = envelope(understand.plan_payload(cfg))
    saved["response"]["choices"][0]["message"]["content"] = template.format(json.dumps(recorded()))
    result = decode_response("understand", saved, understand.plan_payload(cfg), "b/working:free")
    assert len(result["niches"]) == 3
    assert sum(len(n["seeds"]) for n in result["niches"]) == 22


@pytest.mark.parametrize("body", ['[]', '[{}, {}]', '["plan"]', '[{}', 'Plan: [{},', '[{}] trailing', 'Plan: [{}] trailing'])
def test_ambiguous_or_broken_arrays_are_never_salvaged(body):
    with pytest.raises(ValueError):
        json_object(body, allow_singleton_array=True)


def test_other_tasks_stay_object_only_and_plan_schema_stays_strict():
    with pytest.raises(InvalidOutput) as failure:
        decode_response("expand", envelope({}, [{"candidates": []}]), {}, "b/working:free")
    assert failure.value.kind == "invalid_json"
    invalid = recorded()
    invalid[0]["selling_months"] = [13]
    with pytest.raises(InvalidOutput) as failure:
        decode_response("understand", envelope({}, invalid), understand.plan_payload(config()), "b/working:free")
    assert failure.value.kind == "invalid_schema"


def test_rate_limited_primary_then_wrapped_plan_uses_two_calls_without_repair(tmp_path, monkeypatch):
    cfg = config()
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/working:free")])
    run, calls = Run("wrapped-with-429", tmp_path), []
    def transport(provider, parameters):
        assert provider == "openrouter"
        calls.append(deepcopy(parameters))
        if parameters["model"] == "a/limited:free":
            raise HTTPError("https://openrouter.ai", 429, "Limited", {}, None)
        return envelope(understand.plan_payload(cfg))["response"]
    result = complete(Client(run, cfg, transport), "understand", understand.plan_payload(cfg))
    assert len(result["niches"]) == 3
    assert [p["model"] for p in calls] == ["a/limited:free", "b/working:free"]
    assert all(len(p["messages"]) == 2 for p in calls)
    assert len(run.manifest["usage"]) == 2


def test_saved_wrapper_recovers_offline_without_changing_inputs_usage_or_raw(tmp_path, monkeypatch):
    cfg, run = config(), Run("saved-wrapper", tmp_path)
    usage = [{"provider": "openrouter", "status": state} for state in ["HTTP 429", "received", "HTTP 429"]]
    run.manifest.update(input=deepcopy(cfg), input_hash=identity("config", cfg), usage=deepcopy(usage), status="failed",
        failed_stage="understand", error="HTTP 429", stages={"understand": {"status": "failed", "attempts": 1}})
    run.save()
    raw = run.path / "raw/openrouter/wrapped.invalid-old.json"
    write_json(raw, envelope(understand.plan_payload(cfg)))
    before = raw.read_bytes()
    def forbidden(*_args, **_kwargs):
        pytest.fail("Saved wrapper recovery must not call any provider or catalog")
    monkeypatch.setattr(understand, "complete", forbidden)
    monkeypatch.setattr(models, "catalog", forbidden)
    recovered = recover_understanding(run.id, tmp_path)
    assert recovered.manifest["input"] == cfg
    assert recovered.manifest["input_hash"] == identity("config", cfg)
    assert recovered.manifest["usage"] == usage
    assert raw.read_bytes() == before
    assert recovered.manifest["status"] == "interrupted"
    assert recovered.manifest["stages"]["understand"]["status"] == "complete"
    assert sum(len(n["seeds"]) for n in recovered.stage_data("understand")["niches"]) == 22
    events = (recovered.path / "events.jsonl").read_text(encoding="utf-8")
    assert '"shape_adjustment": "single_object_array"' in events
    assert '"api_requests_added": 0' in events


@pytest.mark.parametrize("kind", ["different_input", "multiple_plans", "invalid_schema", "plain_object"])
def test_saved_recovery_still_rejects_unrelated_or_invalid_output(tmp_path, kind):
    cfg, run = config(), Run("reject-wrapper", tmp_path)
    payload = understand.plan_payload(cfg)
    saved = envelope(payload)
    if kind == "different_input":
        saved["parameters"]["messages"][0]["content"] = json.dumps({"brief": "Another request"})
    elif kind == "multiple_plans":
        saved = envelope(payload, recorded() * 2)
    elif kind == "invalid_schema":
        invalid = recorded()
        invalid[0]["selling_months"] = [13]
        saved = envelope(payload, invalid)
    else:
        saved = envelope(payload, recorded()[0])
    write_json(run.path / "raw/openrouter/reject.json", saved)
    assert recover_saved_plan(run.path, payload) is None
