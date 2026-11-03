"""Recorded ten-niche reply after two429s must not require a fourth request."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from market_research.common import read_json, write_json
from market_research.config import validate_config
from market_research.llm import models
from market_research.llm.client import complete
from market_research.llm.plan import validate_plan
from market_research.llm.saved_plan import recover_saved_plan
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import understand
from test_llm_models import row


def original():
    return read_json(Path(__file__).parent / "fixtures/understand-overflow-plan.json")


def inputs():
    cfg = validate_config({"brief": "Christmas keychains, decor and gift wrapping",
        "as_of_date": "2026-10-30", "history_years": [2023, 2024, 2025],
        "trends": {"history_scope": "seasonal", "history_months": [10, 11, 12]},
        "limits": {"llm_requests": 8, "retry_attempts": 0}})
    payload = {"brief": cfg["brief"], "chosen_niches": [], "explicit_category": "",
        "business": cfg["business"],
        "explicit_constraints": {key: cfg[key] for key in ("selling_months", "price_range", "required_features", "excluded_features", "preferences", "preparation_days")},
        "validation_context": {key: cfg[key] for key in ("as_of_date", "history_years", "target_year", "trends")}}
    return cfg, payload


def envelope(payload, draft=None):
    return {"provider": "openrouter", "parameters": {"model": "c/working:free",
        "messages": [{"role": "system", "content": "Interpret brief"}, {"role": "user", "content": json.dumps(payload)}]},
        "validation_error": "Kế hoạch AI cần 1–5 niche hợp lệ",
        "response": {"model": "c/working:free", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(draft or original())}}]}}


def test_recorded_overflow_is_bounded_auditable_and_does_not_mutate_source():
    _, payload = inputs()
    draft = original(); before = deepcopy(draft)
    result = validate_plan(draft, payload)
    assert len(result["niches"]) == 5
    assert result["niches"] == draft["niches"][:5]
    adjustment = result["plan_adjustments"]
    assert adjustment["proposed_count"] == 10
    assert adjustment["deferred_niches"] == draft["niches"][5:]
    assert adjustment["selection"] == "model_order_not_market_rank"
    assert any("không phải xếp hạng thị trường" in note for note in result["assumptions"])
    assert draft == before


def test_explicit_niches_are_preserved_instead_of_model_first_five():
    _, payload = inputs()
    chosen = deepcopy(original()["niches"][-1:]);payload["chosen_niches"] = chosen
    result = validate_plan(original(), payload)
    assert result["niches"] == chosen
    assert "plan_adjustments" not in result
    payload["chosen_niches"] = deepcopy(original()["niches"][:6])
    with pytest.raises(ValueError, match="1–5"):
        validate_plan(original(), payload)


def test_bad_retained_seed_and_unbounded_overflow_still_require_repair():
    _, payload = inputs(); draft = original()
    draft["niches"][0]["seeds"] = []
    with pytest.raises(ValueError, match="seed"):
        validate_plan(draft, payload)
    draft = original();draft["niches"] *= 3
    with pytest.raises(ValueError, match="30 nhóm"):
        validate_plan(draft, payload)


def test_two429s_then_recorded_plan_succeeds_in_existing_three_attempt_limit(tmp_path, monkeypatch):
    cfg, payload = inputs();cfg["llm"]["model"] = "a/limited:free"
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/limited:free"), row("c/working:free")])
    run, calls = Run("recorded-overflow", tmp_path), []
    def transport(provider, parameters):
        assert provider == "openrouter"
        calls.append(parameters["model"])
        if parameters["model"] != "c/working:free":
            raise HTTPError("https://openrouter.ai", 429, "Limited", {}, None)
        return envelope(payload)["response"]
    result = complete(Client(run, cfg, transport), "understand", payload)
    assert len(result["niches"]) == 5
    assert calls == ["a/limited:free", "b/limited:free", "c/working:free"]
    assert len(run.manifest["usage"]) == 3


def test_resume_revalidates_saved_overflow_without_requests_and_preserves_usage(tmp_path, monkeypatch):
    cfg, payload = inputs(); run = Run("saved-overflow", tmp_path)
    run.manifest["usage"] = [{"provider": "openrouter", "status": value} for value in ["HTTP429", "HTTP429", "received"]]
    run.save(); usage_before = deepcopy(run.manifest["usage"])
    raw = run.path / "raw/openrouter/source.invalid-old.json"
    write_json(raw, envelope(payload)); before = raw.read_bytes()
    def forbidden(*_args, **_kwargs):
        pytest.fail("Revalidated saved plan must not call catalog or inference")
    monkeypatch.setattr(models, "catalog", forbidden)
    result = complete(Client(run, cfg, forbidden), "understand", payload)
    assert len(result["niches"]) == 5
    assert run.manifest["usage"] == usage_before
    assert raw.read_bytes() == before
    events = [json.loads(line) for line in (run.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events[-1]["event"] == "llm_saved_plan_revalidated"


@pytest.mark.parametrize("change", ["different_brief", "different_months", "invalid_seed", "wrong_finish", "no_overflow"])
def test_saved_recovery_requires_same_input_and_valid_current_plan(tmp_path, change):
    _, payload = inputs(); current = deepcopy(payload); saved = envelope(payload)
    if change == "different_brief":
        current["brief"] += " changed"
    elif change == "different_months":
        current["validation_context"]["trends"]["history_months"] = [11, 12]
    elif change == "wrong_finish":
        saved["response"]["choices"][0]["finish_reason"] = "length"
    else:
        draft = original()
        if change == "invalid_seed":
            draft["niches"][0]["seeds"] = []
        else:
            draft["niches"] = draft["niches"][:3]
        saved["response"]["choices"][0]["message"]["content"] = json.dumps(draft)
    write_json(tmp_path / "raw/openrouter/source.json", saved)
    assert recover_saved_plan(tmp_path, current) is None


def test_interpreter_persists_adjustment_and_audit_without_extra_calls(tmp_path, monkeypatch):
    cfg, payload = inputs(); run = Run("normalized-plan", tmp_path)
    monkeypatch.setattr(understand, "complete", lambda *_args: validate_plan(original(), payload))
    result = understand.interpret(run, None, cfg)
    assert len(result["niches"]) == 5
    assert result["plan_adjustments"]["proposed_count"] == 10
    assert run.stage_data("normalized_config")["plan_adjustments"] == result["plan_adjustments"]
    assert run.manifest["usage"] == []
