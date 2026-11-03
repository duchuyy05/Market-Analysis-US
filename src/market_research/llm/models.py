"""Keyless model metadata for bounded free JSON fallback selection.

The catalogue GET is not a completion request and never uses Client.request or
changes a run's completion usage. Keep raw metadata (including mandatory
reasoning flags) so callers can also inspect an explicitly configured model.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
from urllib.request import Request, urlopen

from ..common import now, read_json, write_json

CATALOG_URL = "https://openrouter.ai/api/v1/models"
CATALOG_TTL_SECONDS = 6 * 60 * 60
MAX_CATALOG_BYTES = 5_000_000


def _log(client, event, message, **details):
    logger = getattr(client, "log", None)
    if callable(logger):
        try:
            logger(event, message, **details)
        except Exception:
            # Metadata/log availability must not turn an optional fallback
            # catalogue into a failed research stage.
            pass


def _rows(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError("Model catalogue needs a list of metadata objects")
    return value


def catalog(client):
    """Return public raw model rows, using six-hour cache and stale fallback.

    Fixture transports never make a remote metadata request. A stale cache is
    allowed for offline fixtures or during an outage, with an explicit log;
    cached metadata is never a guarantee that a completion provider is online.
    """
    path = Path(client.run.root) / "data/cache/openrouter-models.json"
    cached, fresh = None, False
    try:
        if path.exists():
            if path.stat().st_size > MAX_CATALOG_BYTES:
                raise ValueError("Cached model catalogue exceeds 5 MB")
            envelope = read_json(path)
            if not isinstance(envelope, dict):
                raise ValueError("Cached model catalogue has invalid envelope")
            cached = _rows(envelope.get("models"))
            stamp = datetime.fromisoformat(str(envelope.get("retrieved_at", "")).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Cached model catalogue needs a timezone")
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            fresh = 0 <= age < CATALOG_TTL_SECONDS
    except (OSError, ValueError, TypeError) as error:
        _log(client, "llm_catalog_cache_issue", "Model metadata cache is unavailable or stale", reason=str(error)[:200])
    if fresh:
        _log(client, "llm_catalog_cache", "Using cached public model metadata", models=len(cached))
        return cached
    if getattr(client, "transport", None) is not None:
        _log(client, "llm_catalog_offline", "Fixture transport: no remote model metadata request", stale_cache=cached is not None)
        return cached or []
    try:
        configured_timeout = client.config.get("limits", {}).get("timeout_seconds", 10)
        timeout = min(10, max(1, float(configured_timeout)))
        request = Request(CATALOG_URL, headers={"Accept": "application/json", "User-Agent": "MarketResearch/2.0"}, method="GET")
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_CATALOG_BYTES + 1)
        if len(body) > MAX_CATALOG_BYTES:
            raise ValueError("Public model catalogue exceeds 5 MB")
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Public model catalogue has invalid envelope")
        rows = _rows(payload.get("data"))
    except (OSError, ValueError, TypeError) as error:
        _log(client, "llm_catalog_unavailable", "Public model metadata is unavailable; keeping bounded fallback behavior", reason=str(error)[:200], stale_cache=cached is not None)
        return cached or []
    try:
        write_json(path, {"retrieved_at": now(), "models": rows})
    except (OSError, ValueError, TypeError) as error:
        _log(client, "llm_catalog_cache_issue", "Received public model metadata but could not cache it", reason=str(error)[:200])
    _log(client, "llm_catalog_received", "Received keyless public model metadata; no completion quota used", models=len(rows))
    return rows


def _zero_price(value):
    if isinstance(value, bool) or value is None:
        return False
    try:
        number = Decimal(str(value))
        return number.is_finite() and number == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def eligible_models(rows, max_tokens):
    """Return stable ordered free text model IDs suitable for JSON output.

    Models with unknown mandatory-reasoning behavior remain after models that
    explicitly disable reasoning by default. Mandatory reasoning is excluded.
    This only selects candidates; the caller must still validate every reply.
    """
    if not isinstance(rows, list) or type(max_tokens) is not int or max_tokens < 1:
        return []
    eligible = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        architecture, pricing = row.get("architecture") or {}, row.get("pricing") or {}
        reasoning = row.get("reasoning") or {}
        parameters = row.get("supported_parameters")
        if not isinstance(model_id, str) or not model_id.endswith(":free"):
            continue
        modalities = architecture.get("output_modalities") if isinstance(architecture, dict) else None
        if not isinstance(modalities, list) or "text" not in modalities:
            continue
        if not isinstance(pricing, dict) or any(not _zero_price(pricing[key]) for key in ("prompt", "completion", "request") if key in pricing):
            continue
        if not isinstance(parameters, list) or "response_format" not in parameters:
            continue
        if not isinstance(reasoning, dict) or reasoning.get("mandatory") is True:
            continue
        top_provider = row.get("top_provider") or {}
        if not isinstance(top_provider, dict):
            continue
        maximum = top_provider.get("max_completion_tokens")
        if maximum is not None:
            if isinstance(maximum, bool):
                continue
            try:
                maximum = Decimal(str(maximum))
                if not maximum.is_finite() or maximum < max_tokens:
                    continue
            except (InvalidOperation, TypeError, ValueError):
                continue
        priority = (reasoning.get("default_enabled") is not False, "structured_outputs" not in parameters, model_id)
        eligible[model_id] = min(eligible.get(model_id, priority), priority)
    return sorted(eligible, key=eligible.get)
