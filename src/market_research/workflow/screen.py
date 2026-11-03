"""Rank a bounded keyword pool using comparison batches with a shared anchor."""
from datetime import date, timedelta

from ..providers import trends
from ..providers.client import SourceError
from ..forecasting.series import parse_timeline
from .trend_queries import measurement_query, signal


def window_mean(series, start, end):
    total, days = 0, 0
    for row in series:
        if row.get("partial") or row.get("value") is None:
            continue
        left, right = max(start, date.fromisoformat(row["start"])), min(end, date.fromisoformat(row["end"]))
        overlap = max(0, (right - left).days)
        total += overlap * row["value"]
        days += overlap
    return (total / days if days >= 21 else None), days


def percentile(values, value):
    if len(values) < 2:
        return 0.5
    return (sum(v < value for v in values) + (sum(v == value for v in values) - 1) / 2) / (len(values) - 1)


def analyze(run, client, config, discovery, _recovery=False):
    if config["mode"] == "live" and config.get("trends", {}).get("history_scope") == "seasonal":
        return selected_months(run, client, config, discovery)
    if config["mode"] == "offline" or not config.get("discovery", {}).get("enabled"):
        return {"status": "skipped", "rows": [], "method": "not_screened"}
    if not discovery["keywords"]:
        return {"status": "unavailable", "rows": [], "measured_keywords": 0, "method": "shared_anchor_28d_percentile_v1",
                "anchor": config["trends"]["anchor"], "note": "Chưa khám phá được mẫu/keyword phù hợp để đo; không gọi Trends chỉ cho anchor."}
    rows = [{"keyword_id": k["id"], "keyword": k["text"], "measurement_query": measurement_query(k["text"]),
             "measurement_scope": "exact_keyword" if measurement_query(k["text"]).casefold() == k["text"].casefold() else "broader_product_type",
             "niche_id": k["niche_id"], "status": "unavailable",
             "relative_interest": None, "growth_pct": None, "score": None, "rank": None, "evidence_ids": [], "reason": "Chưa đo Trends"} for k in discovery["keywords"]]
    anchor = config["trends"]["anchor"]
    end = date.fromisoformat(config["as_of_date"]) + timedelta(days=1)
    recent, previous = end - timedelta(days=28), end - timedelta(days=56)
    date_range = f"{(end-timedelta(days=config['trends']['screen_days'])).isoformat()} {config['as_of_date']}"
    # Alternate niches so a tight screening budget does not only measure the
    # first niche in the LLM response. Rankings still use a common anchor.
    queues = [[r["measurement_query"] for r in rows if r["niche_id"] == niche]
              for niche in dict.fromkeys(r["niche_id"] for r in rows)]
    balanced = [queue[i] for i in range(max(map(len, queues), default=0)) for queue in queues if i < len(queue)]
    unique = list({q.casefold(): q for q in balanced if q.casefold() != anchor.casefold()}.values())
    batches = [unique[i:i+4] for i in range(0, len(unique), 4)] or [[anchor]]
    measured = {}
    errors = set()
    for batch in batches:
        queries = [anchor] + [q for q in batch if q.casefold() != anchor.casefold()]
        try:
            if not config["sources"]["trends"]:
                raise SourceError("Nguồn Trends đã tắt")
            def quality(envelope):
                anchor_value, _ = window_mean(parse_timeline(envelope, anchor), recent, end)
                if anchor_value is None or anchor_value < 1:
                    return False
                for query in [q for q in queries if q.casefold() != anchor.casefold()] or [anchor]:
                    current_value, _ = window_mean(parse_timeline(envelope, query), recent, end)
                    previous_value, _ = window_mean(parse_timeline(envelope, query), previous, recent)
                    if current_value is not None and previous_value is not None:
                        return True
                return False
            # A schema-valid but unusable free series should trigger auto recovery
            # before accepting the batch, using the very same queries and window.
            envelope = trends.compare(client, queries, config, date_range,
                                      quality=quality if config.get("trends", {}).get("required", False) else None)
            eid = run.add_evidence("trends_screen", trends.public_url(",".join(queries), envelope["parameters"]), envelope["retrieved_at"], envelope["raw_file"], anchor=anchor, queries=queries, date_range=date_range, market="US")
            anchor_mean, anchor_days = window_mean(parse_timeline(envelope, anchor), recent, end)
            for query in queries:
                series = parse_timeline(envelope, query)
                current, current_days = window_mean(series, recent, end)
                baseline, baseline_days = window_mean(series, previous, recent)
                coverage = anchor_mean is not None and anchor_mean >= 1 and current is not None and baseline is not None
                robustness = signal(series, recent, end)
                valid = coverage and current > 0 and robustness["has_signal"]
                measured.setdefault(query.casefold(), {"status": "available" if valid else "low_signal" if coverage else "unavailable", "recent_mean": current,
                    "provider": envelope.get("provider"),
                    "previous_mean": baseline, "anchor_mean": anchor_mean, "anchor_days": anchor_days,
                    "recent_days": current_days, "previous_days": baseline_days,
                    "relative_interest": round(current / anchor_mean, 6) if valid else None,
                    "growth_pct": round((current / baseline - 1) * 100, 3) if valid and baseline > 0 else None,
                    "reason": "Đo cùng anchor, đủ mốc có tín hiệu" if valid else "Có đủ ngày nhưng tín hiệu quá thấp/ít mốc dương; không phải lỗi thiếu dữ liệu" if coverage else "Thiếu độ phủ hoặc anchor quá thấp",
                    **robustness,
                    "anchor": anchor, "date_range": date_range, "evidence_ids": [eid]})
            run.log("screen", "batch_measured", "Đã nhận phép so sánh Trends", keywords=batch, provider=envelope.get("provider"), anchor=anchor,
                    anchor_mean=anchor_mean, date_range=date_range)
        except (SourceError, ValueError, KeyError, TypeError) as error:
            message = str(error)
            if message not in errors:
                run.warn(f"Sàng lọc Trends: {message}")
                errors.add(message)
            run.log("screen", "batch_unavailable", message, keywords=batch, date_range=date_range)
            for query in batch:
                measured.setdefault(query.casefold(), {"reason": str(error)})
    for row in rows:
        row.update(measured.get(row["measurement_query"].casefold(), {}))
    valid_queries = {r["measurement_query"].casefold(): r for r in rows if r["status"] == "available"}
    active_niches = {r["niche_id"] for r in rows if r["status"] == "available"}
    needs_recovery = not valid_queries or len(active_niches) < len({r["niche_id"] for r in rows})
    if needs_recovery and not _recovery and config["sources"]["trends"] and config.get("trends", {}).get("required", False) and config["trends"]["screen_days"] < 365:
        usage = run.manifest.get("usage", [])
        limits = config["limits"]
        free_left = limits.get("free_trends_requests", 0) - sum(u["provider"] == "google_trends_free" for u in usage)
        paid_left = client.trends_budget("trends_screen")["remaining"]
        provider = config["trends"]["provider"]
        free_possible = provider in {"auto", "free"} and free_left >= 2 and not client.free_trends_error
        paid_possible = provider in {"auto", "serpapi"} and paid_left > 0
        if free_possible or paid_possible:
            run.log("screen", "window_recovery", "Còn nhóm chưa có keyword đủ tín hiệu: thử cửa sổ 365 ngày trong ngân sách, không trộn chỉ số của hai cửa sổ", original_range=date_range, niches_with_signal=len(active_niches))
            recovery_config = {**config, "trends": {**config["trends"], "screen_days": 365}}
            recovered = analyze(run, client, recovery_config, discovery, _recovery=True)
            recovered_niches = {r["niche_id"] for r in recovered["rows"] if r["status"] == "available"}
            if (len(recovered_niches), recovered["measured_keywords"]) > (len(active_niches), len(valid_queries)):
                recovered["recovery"] = {"strategy": "365_day_window_once", "original_date_range": date_range, "chosen": True}
                recovered["note"] += " Đã chọn toàn bộ kết quả cửa sổ 365 ngày vì độ phủ nhóm tốt hơn; không trộn chỉ số hai cửa sổ."
                return recovered
            run.log("screen", "window_recovery_kept_original", "Cửa sổ mở rộng không tăng độ phủ nhóm; giữ toàn bộ phép đo ban đầu")
    interests = [r["relative_interest"] for r in valid_queries.values()]
    growths = [r["growth_pct"] for r in valid_queries.values() if r["growth_pct"] is not None]
    for row in rows:
        if row["status"] == "available":
            interest_score = percentile(interests, row["relative_interest"])
            row["score"] = round(100 * (0.7 * interest_score + 0.3 * percentile(growths, row["growth_pct"])) if row["growth_pct"] is not None else 100 * interest_score, 3)
    ordered = sorted([r for r in rows if r["status"] == "available"], key=lambda r: (-r["score"], -r["relative_interest"], r["keyword"].casefold()))
    ranks = {}
    for row in ordered:
        ranks.setdefault(row["measurement_query"].casefold(), len(ranks) + 1)
        row["rank"] = ranks[row["measurement_query"].casefold()]
    return {"status": "available" if valid_queries else "unavailable", "rows": rows, "measured_keywords": len(valid_queries),
            "query_normalization_version": "exact_design_query_v2", "signal_rule": "multi_positive_points_v1",
            "method": "shared_anchor_28d_percentile_v1", "anchor": anchor, "date_range": date_range,
            "note": "Chỉ xếp trong tập ứng viên US: 70% phân vị mức quan tâm 28 ngày / anchor + 30% phân vị tăng trưởng so 28 ngày trước. Giữ nguyên tên nhân vật, ca sĩ, họa tiết và ngữ cảnh của từng mẫu trong truy vấn đo; không dùng độ hot của loại hàng chung để thay cho mẫu cụ thể. Cần nhiều mốc dương, không nhận một đỉnh đơn lẻ. Thiếu tăng trưởng thì chỉ dùng mức quan tâm. Không phải lượng tìm kiếm tuyệt đối, doanh số hay Top toàn thị trường; sai số lấy mẫu và anchor có thể ảnh hưởng thứ tự."}


def _selected_month_metric(sample, month, year, cutoff):
    """Retain observed interest while qualifying independent points per month."""
    covered = (sample.get("value") is not None and sample.get("observed_days", 0) > 0
               and sample.get("status") in {"complete", "partial"})
    days = sample.get("observed_days", 0)
    native = sample.get("native_step_days")
    required = 1 if native is not None and native >= 27 else 2 if native is not None and native > 1 else 3
    current_partial = year == cutoff.year and month == cutoff.month and sample.get("status") == "partial"
    if current_partial:
        required = min(3, max(1, days))
    positive = sample.get("positive_points", 0)
    robust = covered and sample["value"] > 0 and positive >= required
    status = "available" if robust else "low_signal" if covered else "unavailable"
    reason = (f"Có {positive} mốc dương độc lập; cần {required} theo độ phân giải/kỳ quan sát." if covered else
              "Chưa có quan sát so cùng anchor trong tháng/năm đã chọn.")
    return {"year": year, "month": month, "status": status,
            "relative_interest": sample["value"] / 100 if covered else None,
            "rank": None, "score": None, "observed_days": days, "positive_points": positive,
            "required_positive_points": required, "native_step_days": native,
            "partial_period": sample.get("status") == "partial", "reason": reason}


def selected_months(run, client, config, discovery):
    """Screen exact design queries in an observed month, independent of forecast.

    One observed month can compare a new motif. Recurrence and forecasts remain
    a separate multi-year analysis; they must not erase a newly emerging design.
    Per-window source checkpoints are shared with history when periods overlap,
    while analysis direction IDs protect the training-series checkpoints.
    """
    from ..common import identity
    from . import seasonal_history
    from .planning import analysis_windows

    windows = analysis_windows(config)
    months = sorted(set(config["trends"]["history_months"]))
    year = windows[0]["year"] if windows else config["trends"].get("analysis_year")
    directions = [{"id": "analysis-" + identity("D", k["niche_id"], k["id"]),
                   "keyword_id": k["id"], "keyword": k["text"],
                   "measurement_query": measurement_query(k["text"]), "measurement_scope": "exact_keyword"}
                  for k in discovery["keywords"]]
    observed = []
    if windows:
        analysis_config = {**config, "history_years": [year], "target_year": max(config["target_year"], year + 1)}
        observed = seasonal_history.analyze(run, client, analysis_config, directions, anchor=config["trends"]["anchor"])
    by_id = {item["keyword_id"]: item for item in observed}
    rows = []
    cutoff = date.fromisoformat(config["as_of_date"])
    for keyword in discovery["keywords"]:
        history = by_id.get(keyword["id"], {})
        samples = {row["month"]: row for row in history.get("monthly", [])}
        metrics = [_selected_month_metric(samples.get(month, {}), month, year, cutoff) for month in months]
        qualifying = [metric for metric in metrics if metric["status"] == "available"]
        peak = max(qualifying, key=lambda metric: (metric["relative_interest"], -metric["month"])) if qualifying else None
        missing = [metric["month"] for metric in metrics if metric["status"] == "unavailable"]
        status = "available" if qualifying else "unavailable" if missing else "low_signal"
        reason = ("Đủ tín hiệu riêng ở tháng " + ", ".join(str(metric["month"]) for metric in qualifying) +
                  f"; ưu tiên mức quan tâm mạnh nhất ở tháng {peak['month']}. Các tháng khác giữ nguyên kết quả đo." if qualifying else
                  "Đã đo nhưng chưa tháng nào đủ mốc dương độc lập; không coi đỉnh đơn lẻ là trend." if not missing else
                  "Chưa có tháng đủ tín hiệu và còn thiếu phép đo trong kỳ đã chọn; không thay bằng kỳ khác.")
        rows.append({"keyword_id": keyword["id"], "keyword": keyword["text"], "niche_id": keyword["niche_id"],
                     "measurement_query": measurement_query(keyword["text"]), "measurement_scope": "exact_keyword",
                     "status": status, "rank": None, "score": None,
                     "relative_interest": peak["relative_interest"] if peak else None,
                     "peak_relative_interest": peak["relative_interest"] if peak else None,
                     "peak_month": peak["month"] if peak else None,
                     "qualifying_months": [metric["month"] for metric in qualifying], "missing_months": missing,
                     "monthly_metrics": metrics, "aggregation": "peak_qualifying_month_v1",
                     "growth_pct": None, "anchor": config["trends"]["anchor"], "analysis_year": year,
                     "selection_basis": "selected_month_observations", "selection_months": months,
                     "observed_days": sum(metric["observed_days"] for metric in metrics),
                     "analysis_observations": history.get("monthly", []),
                     "partial_period": bool(missing) or any(metric["partial_period"] for metric in metrics),
                     "provider": ", ".join(sorted({window.get("provider", "") for window in history.get("source_windows", [])})),
                     "evidence_ids": history.get("evidence_ids", []), "reason": reason})
    for month in months:
        per_query = {row["measurement_query"].casefold(): metric for row in rows for metric in row["monthly_metrics"]
                     if metric["month"] == month and metric["status"] == "available"}
        interests = [metric["relative_interest"] for metric in per_query.values()]
        values = sorted(set(interests), reverse=True)
        for row in rows:
            for metric in row["monthly_metrics"]:
                if metric["month"] == month and metric["status"] == "available":
                    metric.update(score=round(100 * percentile(interests, metric["relative_interest"]), 3),
                                  rank=values.index(metric["relative_interest"]) + 1)
    measured = {row["measurement_query"].casefold(): row for row in rows if row["status"] == "available"}
    interests = [row["relative_interest"] for row in measured.values()]
    values = sorted(set(interests), reverse=True)
    for row in rows:
        if row["status"] == "available":
            row.update(score=round(100 * percentile(interests, row["relative_interest"]), 3),
                       rank=values.index(row["relative_interest"]) + 1)
    note = ("Sàng lọc mẫu thiết kế/keyword trong tháng " + ", ".join(map(str, months)) +
            (f" năm {year}. " if year else "; kỳ này chưa bắt đầu theo ngày chốt. ") +
            "Đo nguyên truy vấn của từng mẫu, so mức quan tâm với cùng anchor trong cùng cửa sổ. "
            "Xét tín hiệu độc lập từng tháng; một mẫu có thể phù hợp tháng 12 dù tháng 10–11 bằng 0. "
            "Hạng tổng hợp ưu tiên tỷ lệ so anchor ở tháng đủ tín hiệu mạnh nhất; không khẳng định mẫu hot trong toàn kỳ. "
            "Tháng có dữ liệu ngày cần ít nhất 3 mốc dương, dữ liệu tuần cần 2, dữ liệu tháng cần 1; không nâng đỉnh đơn lẻ thành trend. "
            "Tháng đang diễn ra chỉ tính phần đã có quan sát; nếu mới có dưới 3 ngày thì cần tín hiệu ở đủ các ngày đó. Phép đo một kỳ không đòi hai chu kỳ lịch sử; "
            "dự báo và đánh giá mùa vụ được kiểm tra riêng. Đây là tín hiệu quan tâm tìm kiếm, chưa phải doanh số.")
    result = {"status": "available" if measured else "unavailable", "method": "selected_months_observed_interest_v1",
              "query_normalization_version": "exact_design_query_v2", "signal_rule": "robust_per_month_native_points_v2",
              "aggregation": "peak_qualifying_month_v1",
              "screening_scope": "selected_months", "selection_basis": "selected_month_observations",
              "anchor": config["trends"]["anchor"], "rows": rows, "measured_keywords": len(measured),
              "history_scope": "seasonal", "history_months": months, "selection_months": months, "analysis_year": year,
              "analysis_windows": windows, "date_range": "; ".join(w["start"] + " " + w["end"] for w in windows),
              "note": note}
    run.log("screen", "selected_months_screened", "Đã sàng lọc mẫu/keyword trong đúng kỳ tháng được chọn",
            measured_keywords=len(measured), candidate_keywords=len(rows), history_months=months,
            analysis_year=year, analysis_windows=windows, status=result["status"])
    return result
