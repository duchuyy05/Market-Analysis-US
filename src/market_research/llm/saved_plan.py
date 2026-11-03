"""Revalidate recoverable saved plans without another provider request."""
import json
from pathlib import Path


def recover_saved_plan(run_path, payload):
    # This is not a general bypass for invalid caches: input must match exactly,
    # current validation must pass, with an auditable niche-count/seed-quality
    # adjustment. Invalid JSON, structural fields and empty niches still fail.
    run_path = Path(run_path).resolve()
    boundary = (run_path / "raw/openrouter").resolve()
    if not boundary.is_relative_to(run_path) or not boundary.is_dir():
        return None
    try:
        paths = sorted(boundary.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[:100]
    except OSError:
        return None
    from .client import decode_response
    for path in paths:
        try:
            if not path.resolve().is_relative_to(boundary) or path.stat().st_size > 1_000_000:
                continue
            envelope = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(envelope, dict) or envelope.get("provider") != "openrouter":
                continue
            previous_error = str(envelope.get("validation_error", ""))
            if not any(marker in previous_error for marker in ("niche", "catalog", "chuỗi mô tả")):
                continue
            parameters = envelope.get("parameters") or {}
            if not isinstance(parameters, dict) or not isinstance(parameters.get("messages"), list):
                continue
            user = next((message for message in parameters["messages"] if isinstance(message, dict) and message.get("role") == "user"), {})
            if json.loads(user.get("content", "")) != payload:
                continue
            result = decode_response("understand", envelope, payload, parameters.get("model"))
            if ((result.get("plan_adjustments") or {}).get("kind") != "niche_overflow"
                    and not (result.get("seed_quality_adjustments") or {}).get("excluded")):
                continue
            return {"result": result, "model": (envelope.get("response") or {}).get("model") or parameters.get("model"),
                    "raw_file": str(path.relative_to(run_path)).replace("\\", "/")}
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return None
