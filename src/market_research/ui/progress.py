"""Bounded, sanitized stage inspection; never expose arbitrary run files."""
import json
from pathlib import Path

from ..common import read_json
from ..pipeline import STAGES
from ..providers.client import environment, scrub
from ..storage.database import Database
from .workspace import run_path
from ..workflow.quality import outcome

LABELS = dict(STAGES)
HIDDEN = {"api_key", "x-api-key", "authorization", "token", "reasoning", "reasoning_details", "trace_file", "traceback", "access_token", "secret"}


def bounded(value, depth=0):
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        return {str(k): bounded(v, depth + 1) for k, v in list(value.items())[:40]
                if str(k).lower() not in HIDDEN and not str(k).lower().endswith("_api_key")}
    if isinstance(value, list):
        return [bounded(v, depth + 1) for v in value[:100]]
    return value[:2000] + ("…" if len(value) > 2000 else "") if isinstance(value, str) else value


def rows(values, fields, limit=100):
    return [{k: row.get(k) for k in fields if k in row} for row in values[:limit] if isinstance(row, dict)] if isinstance(values, list) else []


def checkpoint_summary(stage, data):
    if data is None:
        return {"message": "Chưa có kết quả checkpoint; xem nhật ký khi bước đang chạy."}
    if stage == "understand" and isinstance(data, dict):
        return {k: data.get(k) for k in ("category", "interpretation", "business", "selling_months", "comparison_periods", "trends", "price_range", "required_features", "excluded_features", "assumptions")} | {
            "niches": rows(data.get("niches", []), ("id", "name", "name_en", "seeds", "customer_hypothesis"))}
    if stage == "discover" and isinstance(data, dict):
        return {"keyword_count": len(data.get("keywords", [])), "coverage": data.get("summary", {}), "research_focus": data.get("research_focus", {}), "keywords": rows(data.get("keywords", []), ("id", "text", "niche_id", "candidate_level", "content_focus", "design_subject_terms", "source_design", "origin", "evidence_state", "fit_reason", "seed", "evidence_ids")),
                "sources": data.get("discovery_sources", []), "excluded": data.get("exclusions", [])[:30],
                "pages": rows(data.get("web_context", []), ("platform", "title", "url", "published_at"), 30)}
    if stage == "monthly" and isinstance(data, dict):
        ranking = data.get("rankings", {})
        return {"note": data.get("note"), "status": data.get("status"), "coverage": ranking.get("coverage", {}), "method": ranking.get("method"),
                "months": [{"month": item["month"], "ranked_keywords": item.get("ranked_keywords"), "comparison_groups": item.get("comparison_groups"), "keywords": rows(item.get("rankings", []), ("keyword", "measurement_query", "seasonal_score", "seasonality_rank", "demand_rank", "comparison_label", "usable_years", "latest_yoy_pct", "evidence_ids"), 10)} for item in ranking.get("months", [])]}
    if stage in {"screen", "select"} and isinstance(data, dict):
        return {k: data.get(k) for k in ("status", "note", "method", "anchor", "date_range", "analysis_year", "analysis_windows", "selection_basis", "selection_months", "measured_keywords", "requested", "selected_keywords", "trends_verified_keywords")} | {
            "keywords": rows(data.get("rows", []), ("keyword", "measurement_query", "measurement_scope", "status", "positive_points", "observed_points", "observed_days", "partial_period", "analysis_year", "selection_months", "qualifying_months", "peak_month", "monthly_metrics", "analysis_observations", "relative_interest", "growth_pct", "score", "rank", "selected", "search_order", "reason", "provider", "evidence_ids"))}
    if stage in {"search", "enrich"} and isinstance(data, dict):
        return {"product_count": len(data.get("products", [])), "products": rows(data.get("products", []), ("product_id", "title", "source", "price", "currency", "rating", "detail_status", "business_fit", "url"), 30),
                "excluded_products": data.get("exclusions", [])[:50], "source_status": data.get("source_status", []), "review_count": len(data.get("reviews", []))}
    if stage == "history" and isinstance(data, list):
        return {"directions": rows(data, ("direction_id", "measurement_query", "normalization_context", "status", "stability", "growth_pct", "usable_years", "comparison_periods", "validation", "same_period", "seasonal_stability", "reason", "evidence_ids"))}
    if isinstance(data, list):
        return {"count": len(data), "items": bounded(data[:30])}
    if isinstance(data, dict):
        return bounded(data)
    return bounded(data)


def stage_detail(root, run_id, stage):
    if stage not in LABELS:
        raise ValueError("Không có bước tiến trình này")
    path = run_path(root, run_id)
    db = Database(root)
    manifest = db.get_manifest(run_id)
    if manifest is None:
        manifest = read_json(path / "manifest.json", {})
    state = manifest.get("stages", {}).get(stage, {})
    checkpoint = path / "checkpoints" / (stage + ".json")
    data = db.get_checkpoint(run_id, stage)
    too_large = data is None and checkpoint.is_file() and checkpoint.stat().st_size > 10_485_760
    if data is None and not too_large:
        data = read_json(checkpoint)
    if data is not None and state.get("status") in {"complete", "partial", "skipped"} and stage in {"screen", "select", "cluster", "history", "commentary"}:
        state = {**state, **outcome(stage, data, manifest["input"])}
    # Read at most the final MiB; ignore an incomplete JSONL line while a writer appends.
    log_path = path / "events.jsonl"
    logs, skipped_prefix = db.list_events(run_id, stage=stage, limit=101), False
    if not logs and log_path.is_file():
        with log_path.open("rb") as stream:
            size = stream.seek(0, 2)
            offset = max(0, size - 1_048_576)
            stream.seek(offset)
            body = stream.read(1_048_576).decode("utf-8", errors="replace")
        lines = body.splitlines()
        if offset:
            lines = lines[1:]
            skipped_prefix = True
        for line in lines:
            try:
                entry = json.loads(line)
            except (ValueError, TypeError):
                continue
            if isinstance(entry, dict) and entry.get("stage") == stage:
                logs.append({k: entry.get(k) for k in ("at", "stage", "event", "message", "details")})
    for warning in state.get("warnings", []):
        if not any(log.get("message") == warning for log in logs):
            logs.append({"at": state.get("finished_at"), "event": "warning", "message": warning})
    if state.get("error") and not any(log.get("message") == state["error"] for log in logs):
        logs.append({"at": state.get("finished_at"), "event": "error", "message": state["error"]})
    secrets = [value for key, value in environment(root).items() if key.endswith("KEY")]
    result = {"stage": stage, "label": LABELS[stage], "status": state.get("status", "pending"),
              "note": state.get("note"), "reason": state.get("error") or state.get("reason"),
              "timing": {k: state.get(k) for k in ("started_at", "finished_at", "elapsed_seconds", "attempts")},
              "summary": {"message": "Checkpoint lớn; tải bảng kết quả để xem đầy đủ."} if too_large else checkpoint_summary(stage, data), "logs": logs[-100:], "log_count": len(logs),
              "truncated": skipped_prefix or len(logs) > 100}
    return bounded(scrub(result, secrets))
