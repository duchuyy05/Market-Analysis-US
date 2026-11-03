"""Free JSON model metadata selection; all HTTP access is mocked."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from market_research.common import read_json, write_json
from market_research.llm import models


def client(tmp_path, transport=None):
    logs = []
    obj = SimpleNamespace(run=SimpleNamespace(root=tmp_path, manifest={"usage": []}), transport=transport,
                          config={"limits": {"timeout_seconds": 45}}, log=lambda *args, **kwargs: logs.append((args, kwargs)))
    return obj, logs


def row(model_id="sample/model:free", **changes):
    return {"id": model_id, "architecture": {"output_modalities": ["text"]},
            "pricing": {"prompt": "0", "completion": "0", "request": "0"},
            "supported_parameters": ["response_format"], "reasoning": {"mandatory": False, "default_enabled": False},
            "top_provider": {"max_completion_tokens": 6000}, **changes}


def cache(tmp_path, rows, age=0):
    path = tmp_path / "data/cache/openrouter-models.json"
    write_json(path, {"retrieved_at": (datetime.now(timezone.utc)-timedelta(seconds=age)).isoformat(), "models": rows})
    return path


class Response:
    def __init__(self, body):
        self.body, self.requested_size = body, None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, size):
        self.requested_size = size
        return self.body[:size]


def test_catalog_get_has_fixed_url_no_auth_bounded_body_and_no_completion_usage(tmp_path, monkeypatch):
    obj, logs = client(tmp_path)
    rows = [row(), row("sample/reasoner:free", reasoning={"mandatory": True})]
    response = Response(json.dumps({"data": rows}).encode())
    calls = []
    def fetch(request, timeout):
        calls.append((request, timeout))
        return response
    monkeypatch.setattr(models, "urlopen", fetch)
    assert models.catalog(obj) == rows
    request, timeout = calls[0]
    assert request.full_url == "https://openrouter.ai/api/v1/models"
    assert request.get_method() == "GET"
    assert all(key.lower() != "authorization" for key in request.headers)
    assert request.data is None and 0 < timeout <= 10
    assert response.requested_size == models.MAX_CATALOG_BYTES+1
    assert obj.run.manifest["usage"] == []
    assert read_json(tmp_path / "data/cache/openrouter-models.json")["models"] == rows
    assert any(args[0] == "llm_catalog_received" for args, _ in logs)


def test_fresh_cache_skips_http_and_preserves_reasoning_metadata(tmp_path, monkeypatch):
    obj, _ = client(tmp_path)
    rows = [row(reasoning={"mandatory": True, "default_enabled": True})]
    cache(tmp_path, rows, age=60)
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: pytest.fail("Fresh metadata must not fetch"))
    assert models.catalog(obj) == rows
    assert models.eligible_models(rows, 5000) == []


def test_expired_cache_refreshes_after_six_hours(tmp_path, monkeypatch):
    obj, _ = client(tmp_path)
    cache(tmp_path, [row("old/model:free")], age=models.CATALOG_TTL_SECONDS+1)
    rows = [row("new/model:free")]
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: Response(json.dumps({"data": rows}).encode()))
    assert models.catalog(obj) == rows


@pytest.mark.parametrize("has_cache", [False, True])
def test_fixture_transport_never_fetches_even_for_expired_cache(tmp_path, monkeypatch, has_cache):
    obj, _ = client(tmp_path, transport=lambda *_: None)
    rows = [row()]
    if has_cache:
        cache(tmp_path, rows, age=models.CATALOG_TTL_SECONDS+1)
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: pytest.fail("Fixture must never fetch metadata"))
    assert models.catalog(obj) == (rows if has_cache else [])
    assert obj.run.manifest["usage"] == []


def test_network_outage_uses_stale_cache_with_log_and_never_raises(tmp_path, monkeypatch):
    obj, logs = client(tmp_path)
    rows = [row()]
    cache(tmp_path, rows, age=models.CATALOG_TTL_SECONDS+1)
    def unavailable(*_args, **_kwargs):
        raise URLError("fixture outage")
    monkeypatch.setattr(models, "urlopen", unavailable)
    assert models.catalog(obj) == rows
    assert obj.run.manifest["usage"] == []
    assert any(args[0] == "llm_catalog_unavailable" and fields["stale_cache"] for args, fields in logs)


@pytest.mark.parametrize("body", [b"invalid json", b"{}", b'{"data": [null]}', b"x" * (models.MAX_CATALOG_BYTES+1)],
                         ids=["invalid-json", "missing-data", "invalid-model-row", "over-5mb"])
def test_invalid_or_oversized_catalog_is_optional_without_usage(tmp_path, monkeypatch, body):
    obj, logs = client(tmp_path)
    response = Response(body)
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: response)
    assert models.catalog(obj) == []
    assert obj.run.manifest["usage"] == []
    assert any(args[0] == "llm_catalog_unavailable" for args, _ in logs)


def test_corrupt_cache_and_unwritable_cache_do_not_break_valid_metadata(tmp_path, monkeypatch):
    obj, _ = client(tmp_path)
    path = cache(tmp_path, [])
    path.write_text("broken", encoding="utf-8")
    rows = [row()]
    monkeypatch.setattr(models, "urlopen", lambda *_args, **_kwargs: Response(json.dumps({"data": rows}).encode()))
    def blocked(*_args, **_kwargs):
        raise PermissionError("fixture locked cache")
    monkeypatch.setattr(models, "write_json", blocked)
    assert models.catalog(obj) == rows


@pytest.mark.parametrize("changes", [
    {"id": "sample/paid"},
    {"pricing": {"prompt": "0", "completion": "0.01"}},
    {"pricing": {"request": "-1"}},
    {"pricing": {"prompt": None}},
    {"pricing": {"completion": "NaN"}},
    {"pricing": {"prompt": False}},
    {"architecture": {"output_modalities": ["image"]}},
    {"architecture": {"output_modalities": 5}},
    {"supported_parameters": ["tools"]},
    {"reasoning": {"mandatory": True}},
    {"top_provider": {"max_completion_tokens": 4999}},
    {"top_provider": {"max_completion_tokens": "NaN"}},
    {"top_provider": {"max_completion_tokens": False}},
])
def test_ineligible_models_are_excluded(changes):
    assert models.eligible_models([row(**changes)], 5000) == []


def test_free_json_candidates_are_stable_and_prefer_disabled_reasoning_then_structure():
    rows = [row("a/unknown:free", reasoning={}),
            row("z/plain:free"),
            row("q/structured:free", supported_parameters=["response_format", "structured_outputs"]),
            row("a/structured:free", supported_parameters=["response_format", "structured_outputs"]),
            row("a/structured:free", supported_parameters=["response_format", "structured_outputs"])]
    before = deepcopy(rows)
    assert models.eligible_models(rows, 5000) == ["a/structured:free", "q/structured:free", "z/plain:free", "a/unknown:free"]
    assert rows == before


def test_missing_optional_price_and_completion_cap_are_allowed():
    candidate = row(pricing={}, top_provider={})
    assert models.eligible_models([candidate], 5000) == [candidate["id"]]
    assert models.eligible_models([row(top_provider={"max_completion_tokens": 5000})], 5000)
