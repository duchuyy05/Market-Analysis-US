"""History branch: optional evidence, isolated failures per direction."""
from ..common import ROOT, read_json
from ..providers import trends
from ..providers.client import SourceError
from ..forecasting.series import parse_timeline, monthly
from ..forecasting.assess import forecast
from ..forecasting.periods import summarize, years_for
from .planning import HISTORY_BATCH_SIZE


def analyze(run, client, config, directions, *, anchor=None):
    if config.get("trends", {}).get("history_scope", "full") == "seasonal" and config["mode"] != "offline":
        from .seasonal_history import analyze as analyze_seasonal
        return analyze_seasonal(run, client, config, directions, anchor=anchor)
    output, pending = {}, {}
    archive = read_json(ROOT / "data/seasonal-gifts-us/collection.json", {}) if config["mode"] == "offline" else {}
    for direction in directions:
        query = direction.get("measurement_query") or direction["keyword"]
        saved = run.stage_data("history-" + direction["id"])
        if saved is not None and saved.get("normalization_context", {}).get("history_scope") != "seasonal":
            if saved.get("monthly"):
                saved.update(forecast(saved["monthly"], config["history_years"], config["target_year"], config["selling_months"]))
            saved["comparison_periods"] = summarize(saved.get("monthly", []), config.get("comparison_periods", []), saved.get("evidence_ids", []))
            output[direction["id"]] = saved
            continue
        pending.setdefault(query, []).append(direction)
    queries = list(pending)
    batch_size = HISTORY_BATCH_SIZE if config["mode"] == "live" and config.get("discovery", {}).get("enabled", False) else 1
    if anchor and batch_size > 1:
        batch_size -= 1
    for offset in range(0, len(queries), batch_size):
        batch = queries[offset:offset + batch_size]
        request_queries = list(dict.fromkeys(([anchor] if anchor else []) + batch))
        failure = None
        try:
            if not config["sources"]["trends"]:
                raise SourceError("Nguồn Trends đã tắt")
            if config["mode"] == "offline":
                direction = pending[batch[0]][0]
                family = next((f for f in archive.get("config", {}).get("families", []) if f["keyword"] == direction["keyword"]), None)
                raw = archive.get("sources", {}).get("trends_" + family["id"]) if family else None
                if not raw:
                    raise SourceError("Không có chuỗi từ khóa trong bộ lưu trữ")
                original = read_json(ROOT / "data/seasonal-gifts-us" / raw)
                envelope = {**original, "retrieved_at": original["fetched_at_utc"], "raw_file": "archive:" + raw}
            else:
                fetch_config = {**config, "history_years": sorted(set(config["history_years"] + years_for(config.get("comparison_periods", []))))}
                envelope = trends.history(client, request_queries[0], fetch_config) if len(request_queries) == 1 else trends.history_many(client, request_queries, fetch_config)
            run.log("monthly" if anchor else "history", "history_batch_received", "Đã lấy lịch sử; tách đúng chuỗi cho từng keyword", queries=request_queries, provider=envelope.get("provider"), raw_file=envelope.get("raw_file"))
        except (SourceError, ValueError, KeyError, TypeError) as error:
            failure = error
        for query in batch:
            for direction in pending[query]:
                try:
                    if failure:
                        raise failure
                    series = parse_timeline(envelope, query)
                    if not series:
                        raise SourceError("Trends không trả chuỗi hợp lệ")
                    context = {"queries": request_queries, "scale": "shared_anchor" if anchor else "shared_0_100" if len(batch) > 1 else "single_query_0_100",
                               "date_range": envelope["parameters"]["date"], "market": config.get("market", "US"),
                               "note": "Chỉ số chuẩn hóa trong yêu cầu này; không so điểm tuyệt đối giữa các batch. Tín hiệu quá thấp có thể không đủ để dự báo."}
                    if anchor:
                        context.update(anchor=anchor, anchor_monthly=monthly(parse_timeline(envelope, anchor), sorted(set(config["history_years"] + [config["target_year"]] + years_for(config.get("comparison_periods", [])))), config["as_of_date"]))
                    eid = run.add_evidence("trends_history", trends.public_url(",".join(request_queries), envelope["parameters"]), envelope["retrieved_at"], envelope["raw_file"], query=query, measurement_scope=direction.get("measurement_scope", "exact_keyword"), filters=envelope["parameters"], normalization_context=context)
                    months = monthly(series, sorted(set(config["history_years"] + [config["target_year"]] + years_for(config.get("comparison_periods", [])))), config["as_of_date"])
                    row = {"direction_id": direction["id"], "keyword_id": direction["keyword_id"], "measurement_query": query, "measurement_scope": direction.get("measurement_scope", "exact_keyword"), "normalization_context": context, "status": "available", "monthly": months, "evidence_ids": [eid], **forecast(months, config["history_years"], config["target_year"], config["selling_months"])}
                    row["comparison_periods"] = summarize(months, config.get("comparison_periods", []), [eid])
                    run.checkpoint("history-" + direction["id"], row)
                except (SourceError, ValueError, KeyError, TypeError) as error:
                    run.warn(f"Lịch sử / {direction['keyword']}: {error}")
                    row = {"direction_id": direction["id"], "measurement_query": query, "status": "unavailable", "reason": str(error), "stability": "insufficient", "evidence_ids": [], "monthly": [], "forecast": []}
                    row["comparison_periods"] = summarize([], config.get("comparison_periods", []))
                output[direction["id"]] = row
    return [output[d["id"]] for d in directions]
