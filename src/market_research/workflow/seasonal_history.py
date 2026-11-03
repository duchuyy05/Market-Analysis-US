"""Collect only selected months, with a common anchor across separate windows.

Google Trends normalizes each source request independently. Source indices from
different years are therefore retained as raw_value, while analysis uses the
query/anchor ratio times100 (anchor=100, not a bounded Google Trends index).
"""
import calendar
from datetime import date, timedelta

from ..common import identity
from ..control import check_cancel
from ..forecasting.periods import summarize
from ..forecasting.series import monthly, parse_timeline
from ..providers import trends
from ..providers.client import SourceError
from .planning import ANCHORED_HISTORY_BATCH_SIZE, seasonal_windows


def _key(query):
    return " ".join(query.casefold().split())


def _blank(year, month, reason):
    return {"year": year, "month": month, "value": None, "raw_value": None,
            "anchor_raw_value": None, "relative_to_anchor": None, "status": "unavailable",
            "observed_days": 0, "calendar_days": calendar.monthrange(year, month)[1],
            "positive_points": 0, "native_step_days": None, "reason": reason}


def _clip(series, window):
    """Weekly source points may straddle an edge; never import outside months."""
    lower, upper = date.fromisoformat(window["start"]), date.fromisoformat(window["end"]) + timedelta(days=1)
    clipped = []
    for point in series:
        start, end = max(lower, date.fromisoformat(point["start"])), min(upper, date.fromisoformat(point["end"]))
        if end > start:
            clipped.append({**point, "start": start.isoformat(), "end": end.isoformat()})
    return clipped


def _window_months(envelope, query, window):
    series = _clip(parse_timeline(envelope, query), window)
    return [row for row in monthly(series, [window["year"]], window["end"]) if row["month"] in window["months"]]


def _normalize(raw_rows, anchors):
    by_month = {(row["year"], row["month"]): row for row in anchors}
    output = []
    for raw in raw_rows:
        anchor = by_month.get((raw["year"], raw["month"]), {})
        usable = raw.get("value") is not None and anchor.get("value") is not None and anchor["value"] >= 1
        ratio = raw["value"] / anchor["value"] if usable else None
        status = "complete" if usable and raw["status"] == anchor.get("status") == "complete" else "partial" if usable else "unavailable"
        output.append({**raw, "raw_value": raw.get("value"), "anchor_raw_value": anchor.get("value"),
                       "value": round(ratio * 100, 6) if ratio is not None else None,
                       "relative_to_anchor": round(ratio, 8) if ratio is not None else None,
                       "status": status, "observed_days": min(raw.get("observed_days", 0), anchor.get("observed_days", 0)) if usable else 0,
                       "reason": None if usable else "Anchor thiếu dữ liệu hoặc dưới 1; không tạo tỷ lệ và không điền 0"})
    return output


def analyze(run, client, config, directions, *, anchor=None):
    from ..forecasting.seasonal import forecast

    anchor = anchor or config["trends"]["anchor"]
    windows = seasonal_windows(config)
    collected_months = sorted(set(config["trends"].get("history_months", [10, 11, 12])))
    output, pending = {}, {}
    stage = run.manifest.get("current_stage") or "history"
    for direction in directions:
        query = direction.get("measurement_query") or direction["keyword"]
        signature = identity("SC", _key(query), _key(anchor), config.get("market", "US"), windows)
        saved = run.stage_data("history-" + direction["id"])
        if saved and saved.get("collection_signature") == signature and (saved.get("collection_complete") or run.manifest.get("current_stage") == "history"):
            saved.update(forecast(saved.get("monthly", []), config["history_years"], config["target_year"], config["selling_months"], collected_months))
            saved["comparison_periods"] = summarize(saved.get("monthly", []), config.get("comparison_periods", []), saved.get("evidence_ids", []))
            output[direction["id"]] = saved
            continue
        item = pending.setdefault(_key(query), {"query": query, "directions": []})
        item["directions"].append((direction, signature))
    queries = list(pending)
    for offset in range(0, len(queries), ANCHORED_HISTORY_BATCH_SIZE):
        batch = queries[offset:offset + ANCHORED_HISTORY_BATCH_SIZE]
        observations = {query: [] for query in batch}
        errors = {query: [] for query in batch}
        for window in windows:
            check_cancel(getattr(client, "cancel_event", None))
            pending_windows = []
            for key in batch:
                token = identity("SW", key, _key(anchor), config.get("market", "US"), window)
                saved = run.stage_data("seasonal-" + token)
                if saved and saved.get("window") == window and saved.get("anchor") == anchor:
                    observations[key].append(saved)
                else:
                    pending_windows.append((key, token))
            if not pending_windows:
                continue
            request_queries = list(dict.fromkeys([anchor] + [pending[key]["query"] for key, _ in pending_windows]))
            date_range = window["start"] + " " + window["end"]
            try:
                if not config["sources"]["trends"]:
                    raise SourceError("Nguồn Trends đã tắt")
                def quality(envelope):
                    return any(row.get("value") is not None and row["value"] >= 1 and row.get("observed_days", 0) > 0
                               for row in _window_months(envelope, anchor, window))
                envelope = trends.history_range(client, request_queries, config, date_range, quality=quality)
                anchors = _window_months(envelope, anchor, window)
                for key, token in pending_windows:
                    query = pending[key]["query"]
                    raw_rows = _window_months(envelope, query, window)
                    if not any(row.get("observed_days", 0) for row in raw_rows):
                        errors[key].append(date_range + ": Nguồn chưa trả quan sát trong đúng kỳ thu thập")
                        continue
                    normalized = _normalize(raw_rows, anchors)
                    eid = run.add_evidence("trends_history", trends.public_url(",".join(request_queries), envelope["parameters"]),
                        envelope["retrieved_at"], envelope["raw_file"], query=query, measurement_scope="seasonal_window",
                        anchor=anchor, history_scope="seasonal", requested_window=window, filters=envelope["parameters"],
                        analysis_unit="query_to_anchor_times_100", note="Nguồn 0–100 giữ ở raw_value; phân tích tỷ lệ so cùng anchor, không nối trực tiếp chỉ số nguồn của hai yêu cầu khác nhau.")
                    record = {"window": window, "anchor": anchor, "monthly": normalized, "anchor_raw_monthly": anchors,
                              "evidence_ids": [eid], "raw_file": envelope["raw_file"], "parameters": envelope["parameters"], "provider": envelope.get("provider")}
                    run.checkpoint("seasonal-" + token, record)
                    observations[key].append(record)
                run.log(stage, "seasonal_window_received", "Đã lấy đúng kỳ lịch sử và quy về anchor chung", queries=request_queries, date_range=date_range, provider=envelope.get("provider"), raw_file=envelope["raw_file"])
            except (SourceError, ValueError, KeyError, TypeError) as error:
                for key, _ in pending_windows:
                    errors[key].append(date_range + ": " + str(error))
                run.log(stage, "seasonal_window_unavailable", str(error), queries=request_queries, date_range=date_range)
        for key in batch:
            windows_received = observations[key]
            known = {(row["year"], row["month"]): row for record in windows_received for row in record["monthly"]}
            months = [known.get((year, month), _blank(year, month, "Chưa có quan sát cho kỳ đã chọn")) for year in config["history_years"] for month in collected_months]
            raw_anchors = {(row["year"], row["month"]): row for record in windows_received for row in record["anchor_raw_monthly"]}
            anchor_rows = [{**row, "raw_value": row.get("value"), "value": 100.0 if row.get("value") is not None and row["value"] >= 1 else None,
                            "status": row.get("status", "unavailable") if row.get("value") is not None and row["value"] >= 1 else "unavailable"} for _, row in sorted(raw_anchors.items())]
            evidence_ids = sorted({eid for record in windows_received for eid in record["evidence_ids"]})
            context = {"scale": "anchor_ratio_100", "history_scope": "seasonal", "history_months": collected_months,
                "collected_months": collected_months, "anchor": anchor, "market": config.get("market", "US"),
                "requested_windows": windows, "date_range": "; ".join(w["start"] + " " + w["end"] for w in windows),
                "anchor_monthly": anchor_rows,
                "demand_monthly": [{**row, "value": row.get("relative_to_anchor")} for row in months],
                "note": "Đơn vị phân tích: anchor=100, có thể vượt 100. Chỉ thu kỳ đã chọn; không có dữ liệu các tháng còn lại, không kết luận mùa vụ cả năm."}
            observed = any(row.get("value") is not None for row in months)
            for direction, signature in pending[key]["directions"]:
                row = {"direction_id": direction["id"], "keyword_id": direction["keyword_id"], "measurement_query": pending[key]["query"],
                    "measurement_scope": direction.get("measurement_scope", "exact_keyword"), "history_scope": "seasonal",
                    "collection_signature": signature, "collection_complete": len(windows_received) == len(windows),
                    "normalization_context": context, "status": "available" if observed else "unavailable", "monthly": months,
                    "evidence_ids": evidence_ids, "source_windows": [{k: record[k] for k in ("window", "raw_file", "parameters", "provider", "evidence_ids")} for record in windows_received],
                    **forecast(months, config["history_years"], config["target_year"], config["selling_months"], collected_months)}
                if errors[key]:
                    row["reason"] = "; ".join(dict.fromkeys(errors[key]))[:1500]
                elif not observed:
                    row["reason"] = "Chưa có tỷ lệ so anchor hợp lệ cho các kỳ đã chọn"
                row["comparison_periods"] = summarize(months, config.get("comparison_periods", []), evidence_ids)
                run.checkpoint("history-" + direction["id"], row)
                output[direction["id"]] = row
                if errors[key] or not observed:
                    run.warn(f"Lịch sử theo mùa / {direction['keyword']}: " + row["reason"])
    return [output[direction["id"]] for direction in directions]
