"""Recorded 429 -> usable but Vietnamese plan must not repair on the 429 model."""
import copy
from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from market_research.common import read_json
from market_research.llm import models
from market_research.llm.client import complete
from market_research.providers.client import Client, SourceError
from market_research.storage.run import Run
from test_llm_models import row
from test_llm_recovery import config, plan, response


def limited():
    return HTTPError("https://openrouter.ai", 429, "Limited", {}, None)


def vietnamese_plan():
    draft = plan()
    draft["niches"][0]["seeds"] = ["bình giữ nhiệt"]
    return draft


def test_repair_uses_model_that_returned_plan_not_rate_limited_primary(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/working:free")])
    run, calls = Run("repair-working-model", tmp_path), []
    def transport(provider, params):
        calls.append(copy.deepcopy(params))
        if params["model"] == "a/limited:free":
            raise limited()
        return response(vietnamese_plan() if len(params["messages"]) == 2 else plan())
    cfg = config(llm={"model": "a/limited:free"}, limits={"retry_attempts": 1})
    result = complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert result["niches"][0]["seeds"] == plan()["niches"][0]["seeds"]
    assert [p["model"] for p in calls] == ["a/limited:free", "b/working:free", "b/working:free"]
    assert "Translate Vietnamese product seeds to English" in calls[-1]["messages"][-1]["content"]
    assert len(run.manifest["usage"]) == 3


def test_two_rate_limited_models_use_final_slot_for_third_vendor(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/limited:free"), row("c/working:free")])
    run, calls = Run("third-vendor", tmp_path), []
    def transport(provider, params):
        calls.append(params["model"])
        if params["model"] != "c/working:free":
            raise limited()
        return response(plan())
    cfg = config(llm={"model": "a/limited:free"}, limits={"retry_attempts": 1})
    assert complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})["category"] == plan()["category"]
    assert calls == ["a/limited:free", "b/limited:free", "c/working:free"]
    assert len(run.manifest["usage"]) == 3


def test_final_model_invalid_plan_does_not_start_fourth_completion(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/limited:free"), row("c/working:free")])
    run, calls = Run("no-fourth-call", tmp_path), []
    def transport(provider, params):
        calls.append(params["model"])
        if params["model"] != "c/working:free":
            raise limited()
        return response(vietnamese_plan())
    cfg = config(llm={"model": "a/limited:free"})
    with pytest.raises(SourceError, match="Seed"):
        complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert len(calls) == 3


def test_known_catalog_does_not_send_generic_router_back_to_limited_models(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "catalog", lambda _: [row("a/limited:free"), row("b/limited:free")])
    run, calls = Run("no-random-router", tmp_path), []
    def transport(provider, params):
        calls.append(params["model"])
        raise limited()
    cfg = config(llm={"model": "a/limited:free"})
    with pytest.raises(SourceError, match="429"):
        complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert calls == ["a/limited:free", "b/limited:free"]


@pytest.mark.parametrize("architecture", [{"output_modalities": ["audio"]}, {"output_modalities": ["embeddings"]}])
def test_audio_or_embedding_configuration_is_not_sent_to_chat(tmp_path, monkeypatch, architecture):
    monkeypatch.setattr(models, "catalog", lambda _: [row("bad/wrong-endpoint:free", architecture=architecture), row("good/chat:free")])
    run, calls = Run("non-chat", tmp_path), []
    def transport(provider, params):
        calls.append(params["model"])
        return response(plan())
    cfg = config(llm={"model": "bad/wrong-endpoint:free"})
    complete(Client(run, cfg, transport), "understand", {"brief": cfg["brief"]})
    assert calls == ["good/chat:free"]
    events = [json.loads(line) for line in (run.path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    task = next(e for e in events if e["event"] == "llm_task")["details"]
    assert task["model"] == "good/chat:free" and task["configured_model"] == "bad/wrong-endpoint:free"


def test_configured_model_missing_from_available_catalog_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "catalog", lambda _: [row("good/chat:free")])
    calls = []
    cfg = config(llm={"model": "unknown/voice:free"})
    run = Run("unknown-type", tmp_path)
    complete(Client(run, cfg, lambda _, p: calls.append(p["model"]) or response(plan())), "understand", {"brief": cfg["brief"]})
    assert calls == ["good/chat:free"]


def test_openrouter_429_preserves_upstream_details_and_skips_immediate_retry(tmp_path, monkeypatch):
    secret = "secret-provider-key-for-test"
    monkeypatch.setenv("OPENROUTER_API_KEY", secret)
    run, calls = Run("rate-detail", tmp_path), []
    def transport(provider, params):
        calls.append(provider)
        body = {"error": {"code": 429, "message": "Provider returned error", "metadata": {"provider_name": "Phala",
            "raw": json.dumps({"error": {"message": "Upstream model limited " + secret}})}}}
        raise HTTPError("https://openrouter.ai", 429, "Limited", {"Retry-After": "20"}, BytesIO(json.dumps(body).encode()))
    cfg = config(limits={"retry_attempts": 1})
    with pytest.raises(SourceError, match="Upstream model limited") as caught:
        Client(run, cfg, transport).request("openrouter", {"model": "sample/model:free"})
    assert calls == ["openrouter"]
    assert caught.value.status_code == 429
    assert caught.value.details["provider_name"] == "Phala"
    assert caught.value.details["retry_after_seconds"] == 20
    assert secret not in str(caught.value)
    raw = next((run.path / "raw/openrouter").glob("*.json"))
    assert secret not in raw.read_text(encoding="utf-8")
    assert run.manifest["usage"][0]["requested_model"] == "sample/model:free"


def test_serpapi_transient_retry_policy_remains_separate(tmp_path, monkeypatch):
    from market_research.providers import client as provider_client
    monkeypatch.setattr(provider_client.time, "sleep", lambda _: None)
    run, calls = Run("serp-retry", tmp_path), []
    def transport(provider, params):
        calls.append(provider)
        raise limited()
    cfg = config(limits={"retry_attempts": 1})
    with pytest.raises(SourceError):
        Client(run, cfg, transport).request("serpapi", {"engine": "amazon", "k": "gift"})
    assert calls == ["serpapi", "serpapi"]
