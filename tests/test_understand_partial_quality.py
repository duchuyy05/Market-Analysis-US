"""One weak generated seed must not discard a valid saved research plan."""
from copy import deepcopy
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from market_research.common import identity, write_json
from market_research.config import validate_config
from market_research.llm import models
from market_research.llm.client import complete
from market_research.llm.plan import validate_plan
from market_research.pipeline import recover_understanding
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import understand
from test_llm_models import row


def recorded_plan():
    return json.loads((Path(__file__).parent / "fixtures/understand-mixed-quality-plan.json").read_text(encoding="utf-8"))


def config():
    return validate_config({"brief": "Sản phẩm nhỏ gọn như móc khóa hay ví tiền, hoặc áo thun in hình, hoặc các sản phẩm khác phù hợp vào dịp cuối năm",
        "as_of_date": "2026-11-02", "history_years": [2023, 2024, 2025],
        "trends": {"history_scope": "seasonal", "history_months": [11, 12], "analysis_year": 2025},
        "limits": {"llm_requests": 8, "retry_attempts": 0}})


def source(payload, draft=None):
    return {"provider": "openrouter", "validation_error": "Keyword là chuỗi mô tả catalog: acrylic keychain custom shape",
        "parameters": {"model": "c/working:free", "messages": [{"role": "system", "content": "Interpret brief"},
            {"role": "user", "content": json.dumps(payload)}]},
        "response": {"model": "c/working:free", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(draft or recorded_plan())}}]}}


def test_recorded_plan_keeps_all_requested_families_and_drops_only_the_bad_seed():
    cfg, draft = config(), recorded_plan()
    original = deepcopy(draft)
    result = validate_plan(draft, understand.plan_payload(cfg))
    assert len(result["niches"]) == 5
    assert sum(len(n["seeds"]) for n in result["niches"]) == 49
    assert result["niches"][0]["seeds"][0] == "snowflake keychain"
    assert any("wallet" in seed for n in result["niches"] for seed in n["seeds"])
    assert any("t-shirt" in seed or "tee" in seed for n in result["niches"] for seed in n["seeds"])
    assert [item["keyword"] for item in result["seed_quality_adjustments"]["excluded"]] == ["acrylic keychain custom shape"]
    assert result["required_features"] == result["excluded_features"] == []
    assert len(result["business_rule_adjustments"]["removed_duplicate_rules"]) == 8
    assert draft == original


def test_company_rule_deduplication_preserves_real_and_explicit_user_constraints():
    cfg, draft = config(), recorded_plan()
    draft["required_features"] += ["washable", "must be a physical product with washable cotton", "có thể gia công bằng vải cotton"]
    draft["excluded_features"] += ["latex"]
    inputs = understand.plan_payload(cfg)
    result = validate_plan(draft, inputs)
    assert result["required_features"] == ["washable", "must be a physical product with washable cotton", "có thể gia công bằng vải cotton"]
    assert result["excluded_features"] == ["latex"]
    inputs["explicit_constraints"]["required_features"] = ["can be printed"]
    inputs["explicit_constraints"]["excluded_features"] = ["cosmetics"]
    explicit = validate_plan(draft, inputs)
    assert explicit["required_features"] == ["can be printed"]
    assert explicit["excluded_features"] == ["cosmetics"]


def test_two_limited_models_then_a_mixed_plan_succeeds_with_three_requests(tmp_path, monkeypatch):
    cfg = config()
    cfg["llm"]["model"] = "a/limited:free"
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/limited:free"), row("c/working:free")])
    run, calls = Run("partial-quality-three", tmp_path), []
    def transport(provider, parameters):
        assert provider == "openrouter"
        calls.append(parameters["model"])
        if parameters["model"] != "c/working:free":
            raise HTTPError("https://openrouter.ai", 429, "Limited", {}, None)
        return source(understand.plan_payload(cfg))["response"]
    result = complete(Client(run, cfg, transport), "understand", understand.plan_payload(cfg))
    assert sum(len(n["seeds"]) for n in result["niches"]) == 49
    assert calls == ["a/limited:free", "b/limited:free", "c/working:free"]
    assert len(run.manifest["usage"]) == 3


def test_saved_failed_plan_is_restored_without_any_provider_or_budget_change(tmp_path, monkeypatch):
    cfg = config()
    cfg["limits"]["llm_requests"] = 3
    run = Run("saved-partial-quality", tmp_path)
    usage = [{"provider": "openrouter", "status": state} for state in ["HTTP 429", "HTTP 429", "received"]]
    original_hash = identity("config", cfg)
    run.manifest.update(input=cfg, input_hash=original_hash, status="failed", failed_stage="understand", error="old failure",
        usage=deepcopy(usage), stages={"understand": {"status": "failed", "attempts": 1, "error": "catalog seed"}})
    run.save()
    raw = run.path / "raw/openrouter/source.invalid-old.json"
    write_json(raw, source(understand.plan_payload(cfg)))
    raw_before = raw.read_bytes()
    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline checkpoint recovery must never call a provider or model catalog")
    monkeypatch.setattr(understand, "complete", forbidden)
    monkeypatch.setattr(models, "catalog", forbidden)
    restored = recover_understanding(run.id, tmp_path)
    assert restored.manifest["status"] == "interrupted"
    assert restored.manifest["stages"]["understand"]["status"] == "complete"
    assert restored.manifest["input"] == cfg and restored.manifest["input_hash"] == original_hash
    assert restored.manifest["usage"] == usage and raw.read_bytes() == raw_before
    assert sum(len(n["seeds"]) for n in restored.stage_data("understand")["niches"]) == 49
    assert not (restored.path / "dataset.json").exists()
    assert "error" not in restored.manifest and "failed_stage" not in restored.manifest
    with pytest.raises(ValueError, match="đang lỗi"):
        recover_understanding(run.id, tmp_path)


def test_unrecoverable_plan_stays_failed_without_provider_calls(tmp_path):
    run = Run("no-saved-plan", tmp_path)
    run.manifest.update(input=config(), status="failed", stages={"understand": {"status": "failed"}}, usage=[])
    run.save()
    with pytest.raises(ValueError, match="không gọi thêm API"):
        recover_understanding(run.id, tmp_path)
    assert Run(run.id, tmp_path).manifest["status"] == "failed"
