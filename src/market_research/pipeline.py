"""Single workflow for CLI/UI. Stage boundaries are durable and inspectable."""
from contextlib import contextmanager
import os
import time

from .common import ROOT, now, read_json, write_json, identity
from .config import validate_config
from .storage.run import Run
from .providers.client import Client
from .control import RunCancelled, check_cancel
from .workflow import understand, discover, products, history, ideas, commentary, selection, broad, screen
from .analysis import reviews, opportunities
from .analysis.product_history import summarize_product_history
from .ranking import engine
from .reporting.render import export
from .workflow.quality import unavailable, outcome
from .workflow.planning import trends_plan
from .workflow import monthly_keywords
from .analysis.keyword_monthly import build as build_keyword_monthly
from .analysis.monthly_priority import prioritize as monthly_priority
from .workflow.trend_queries import product_context

STAGES = [
    ("understand", "Hiểu mô tả"), ("discover", "Khám phá từ khóa đa nguồn"), ("screen", "Sàng lọc Trends US"), ("monthly", "Xếp hạng keyword theo tháng"),
    ("cluster", "Gom hướng sản phẩm"), ("select", "Chọn keyword tìm sản phẩm"),
    ("search", "Tìm mẫu Amazon / Shopping"), ("enrich", "Lấy chi tiết / phản hồi"), ("history", "Lịch sử và dự báo"),
    ("assess", "Đánh giá cơ hội"), ("ideas", "Đề xuất sản phẩm"), ("rank", "Xếp hạng"), ("commentary", "Nhận định bổ sung"), ("report", "Dựng và kiểm tra báo cáo"),
]


def export_tables(run, data):
    """Keep downloadable tables aligned with the saved analysis on rebuilds."""
    for name in ("keywords", "keyword_exclusions", "keyword_selection", "keyword_screening", "web_context", "discovery_sources", "directions", "products", "offers", "product_matches", "search_occurrences", "reviews", "review_themes", "ideas", "source_status"):
        run.table(name, data.get(name, []))
    run.table("all_candidates", data.get("search_occurrences", []))
    run.table("product_exclusions", data.get("exclusions", []))
    run.table("company_product_fit", [{"product_id": p["product_id"], "title": p["title"], **p.get("business_fit", {})} for p in data.get("products", [])])
    run.table("keyword_monthly", data.get("keyword_monthly", {}).get("rows", []))
    run.table("keyword_history_observations", [{"keyword_id": h.get("keyword_id"), "direction_id": h["direction_id"], "measurement_query": h.get("measurement_query"), "metric_unit": h.get("metric_unit", "trends_index_0_100"), **row, "evidence_ids": h.get("evidence_ids", [])} for h in data.get("keyword_histories", []) for row in h.get("monthly", [])])
    run.table("all_ranked_items", data["rankings"]["items"])
    run.table("ranking_definitions", data["rankings"]["definitions"])
    run.table("assessments", data["assessments"]["directions"])
    run.table("product_checks", data["assessments"]["product_checks"])
    histories = data["histories"]
    for table, field in (("trend_observations", "monthly"), ("forecasts", "forecast"), ("history_comparison_periods", "comparison_periods"), ("same_period_years", "same_period")):
        run.table(table, [{"direction_id": h["direction_id"], "metric_unit": h.get("metric_unit", "trends_index_0_100"), **row, "evidence_ids": h.get("evidence_ids", [])} for h in histories for row in h.get(field, [])])
    run.table("historical_validation", [{"direction_id": h["direction_id"], **fold} for h in histories for fold in h.get("validation", {}).get("folds", [])])
    run.table("product_capture_history", [{"product_id": item["product_id"], "asin": item.get("asin"), **row} for item in data.get("product_history", {}).get("items", []) for row in item["observations"]])


def process_alive(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Invalid PID -> dead; access denied -> assume alive.
        code = wintypes.DWORD()
        try:
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def exclusive(run):
    path = run.path / ".running.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        # Recover only a provably dead process, never based on elapsed time.
        record = read_json(path, {})
        pid = record.get("pid")
        if pid:
            if process_alive(pid):
                raise RuntimeError("Lượt nghiên cứu đang chạy trong tiến trình khác")
            path.unlink()
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        else:
            raise RuntimeError("Khóa lượt chạy không hợp lệ; kiểm tra tiến trình trước khi gỡ khóa")
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        import json
        json.dump({"pid": os.getpid(), "started_at": now()}, stream)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def interleave(directions, niches):
    queues = [[d for d in directions if d["niche_id"] == n["id"]] for n in niches]
    return [queue[index] for index in range(max(map(len, queues), default=0)) for queue in queues if len(queue) > index]


@contextmanager
def cancellation_state(run, event):
    try:
        yield
    except RunCancelled as error:
        run.manifest.update(status="cancelled", stopped_at=now(), stop_message=str(error))
        run.manifest.pop("failed_stage", None)
        run.save()
        event(str(error))


def recover_understanding(run_id, root=ROOT):
    """Repair only a failed understand checkpoint from saved output, with no provider calls."""
    from copy import deepcopy
    from .llm.saved_plan import recover_saved_plan
    run = Run(run_id, root)
    with exclusive(run):
        if run.manifest.get("stages", {}).get("understand", {}).get("status") != "failed":
            raise ValueError("Chỉ khôi phục offline khi bước Hiểu mô tả đang lỗi")
        config = run.manifest.get("input")
        if not isinstance(config, dict):
            raise ValueError("Lượt chạy chưa có input đã khóa")
        saved = recover_saved_plan(run.path, understand.plan_payload(config))
        if not saved:
            raise ValueError("Chưa có phản hồi đã lưu phù hợp input và hợp lệ sau kiểm tra; không gọi thêm API")
        original_input, original_usage = deepcopy(config), deepcopy(run.manifest.get("usage", []))
        original_hash = run.manifest.get("input_hash")
        result = understand.interpret(run, None, config, validated_draft=saved["result"])
        run.checkpoint("understand", result)
        state = run.manifest["stages"]["understand"]
        state.pop("error", None)
        state.update(status="complete", note="Đã khôi phục từ phản hồi đã lưu, loại riêng seed chưa phù hợp; không gọi API.",
                     finished_at=now(), recovered_from_saved=True)
        run.manifest.pop("error", None)
        run.manifest.pop("failed_stage", None)
        run.manifest.update(status="interrupted", current_stage="understand",
            recovery={"kind": "saved_understanding", "can_resume": True,
                      "message": "Bước Hiểu mô tả đã phục hồi offline; bấm Chạy tiếp phần thiếu để chạy các nguồn còn lại trong ngân sách đã đặt."})
        if config != original_input or run.manifest.get("usage", []) != original_usage or run.manifest.get("input_hash") != original_hash:
            raise RuntimeError("Khôi phục không được thay input hoặc usage")
        run.log("understand", "saved_plan_recovered", "Khôi phục riêng bước Hiểu mô tả từ dữ liệu đã lưu; chờ người dùng chạy tiếp", raw_file=saved["raw_file"],
                retained_keywords=sum(len(n["seeds"]) for n in result["niches"]), api_requests_added=0)
        run.save()
    return run


def execute(config=None, *, run_id=None, root=ROOT, event=None, transport=None, cancel_event=None):
    run = Run(run_id, root)
    event = event or (lambda message: print(message, flush=True))
    with exclusive(run), cancellation_state(run, event):
        if "input" not in run.manifest:
            if config is None:
                raise ValueError("Lượt chạy mới cần cấu hình")
            run.manifest["input"] = validate_config(config)
            run.manifest["input_hash"] = identity("config", run.manifest["input"])
        elif config is not None and identity("config", validate_config(config)) != run.manifest["input_hash"]:
            raise ValueError("Cấu hình đã khóa; tạo lượt mới khi thay đổi phạm vi/ngân sách")
        config = run.manifest["input"]
        # Frozen runs created before broad discovery keep their original sources.
        if "discovery" not in config:
            config = {**config, "discovery": {"enabled": False, "sites": []}, "trends": {"provider": "serpapi", "anchor": "gift basket", "screen_days": 90, "cache_hours": 0}}
        if "business" not in config:
            # Frozen earlier inputs retain their original domain on resume.
            config = {**config, "business": {"profile": "general", "categories": []}}
        run.manifest.pop("error", None)
        run.manifest.pop("stop_message", None)
        run.manifest.pop("waiting_reason", None)
        run.manifest.pop("recovery", None)
        run.manifest.pop("screening_diagnostics", None)
        run.manifest["warnings"] = []
        run.manifest.update(status="running", mode=config["mode"], stage_count=len(STAGES))
        run.save()
        client = Client(run, config, transport, cancel_event)
        run.log("workflow", "run_started", "Bắt đầu / chạy tiếp nghiên cứu", mode=config["mode"], limits=config["limits"], trends=config.get("trends"))
        def stage(name, function):
            check_cancel(cancel_event)
            saved = run.stage_data(name)
            state = run.manifest["stages"].get(name, {})
            obsolete_seasonal_skip = (name == "screen" and config.get("trends", {}).get("history_scope") == "seasonal"
                                      and isinstance(saved, dict) and saved.get("status") == "skipped")
            obsolete_proxy_screen = (name == "screen" and isinstance(saved, dict) and any(
                row.get("measurement_scope") == "broader_product_type" for row in saved.get("rows", [])))
            obsolete_design_discovery = (name == "discover" and isinstance(saved, dict) and any(
                product_context(row.get("text", ""), config) for row in saved.get("keywords", [])))
            if obsolete_seasonal_skip:
                run.log(name, "legacy_seasonal_screen_replaced", "Thay checkpoint từng bỏ sàng lọc theo mùa bằng phép đo trong kỳ đã chọn; giữ nguyên dữ liệu nguồn và bộ đếm API")
            if obsolete_proxy_screen:
                run.log(name, "legacy_proxy_screen_replaced", "Đo lại đúng mẫu/keyword thay cho phép đo loại hàng rộng; giữ nguyên bộ đếm API và dữ liệu nguồn")
            if obsolete_design_discovery:
                run.log(name, "legacy_design_discovery_replaced", "Khám phá lại mẫu có hình in/họa tiết cụ thể; keyword loại hàng chung chỉ dùng dò nguồn, giữ nguyên bộ đếm API")
            if saved is not None and state.get("status") in {"complete", "skipped"} and not (obsolete_seasonal_skip or obsolete_proxy_screen or obsolete_design_discovery):
                for warning in state.get("warnings", []):
                    run.warn(warning)
                event("Đã lưu: " + name)
                run.log(name, "checkpoint_reused", "Dùng lại bước đã lưu, không gọi nguồn cho bước này")
                return saved
            # Changed upstream data invalidates every dependent checkpoint status.
            after = False
            for next_name, _ in STAGES:
                if after:
                    run.manifest["stages"].pop(next_name, None)
                if next_name == name:
                    after = True
            state = {"status": "running", "started_at": now(), "attempts": state.get("attempts", 0)+1}
            run.manifest["stages"][name] = state
            run.manifest["current_stage"] = name
            run.save()
            run.log(name, "stage_started", dict(STAGES)[name], attempt=state["attempts"])
            event(dict(STAGES)[name])
            before = time.monotonic()
            previous_warnings = set(run.manifest["warnings"])
            try:
                data = function()
                run.checkpoint(name, data)
                state.update(**outcome(name, data, config), finished_at=now(), elapsed_seconds=round(time.monotonic()-before, 3), warnings=[w for w in run.manifest["warnings"] if w not in previous_warnings])
                summary = {k: len(v) for k, v in data.items() if isinstance(v, list)} if isinstance(data, dict) else {"rows": len(data)} if isinstance(data, list) else {}
                message = "Không áp dụng với cấu hình này" if state["status"] == "skipped" else "Hoàn tất bước" if state["status"] == "complete" else "Bước có dữ liệu thiếu; xem kết quả và hướng xử lý"
                run.log(name, "stage_finished", message, status=state["status"], note=state.get("note"), elapsed_seconds=state["elapsed_seconds"], counts=summary)
                check_cancel(cancel_event)
                return data
            except RunCancelled:
                if state.get("status") == "running":
                    state.update(status="cancelled", finished_at=now())
                run.log(name, "stage_cancelled", "Đã lưu phần nhận được trước khi dừng")
                raise
            except Exception as error:
                import traceback
                from .providers.client import scrub
                log = run.path / "logs" / (name + "-error.txt")
                log.parent.mkdir(parents=True, exist_ok=True)
                log.write_text(scrub(traceback.format_exc(), [v for k, v in client.env.items() if k.endswith("KEY")]), encoding="utf-8")
                message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__ + ": xem bước lỗi và dữ liệu đã lưu"
                state.update(status="failed", error=message, trace_file=str(log.relative_to(run.path)), finished_at=now())
                run.log(name, "stage_failed", message, error_type=type(error).__name__)
                run.manifest.update(status="failed", failed_stage=name)
                run.manifest["errors"].append({"stage": name, "message": message, "at": now()})
                raise RuntimeError(f"Bước {name}: {message}. Resume: python run.py resume --run-id {run.id}") from error
            finally:
                run.save()
        config = stage("understand", lambda: understand.interpret(run, client, config))
        client.config = config
        if config["mode"] == "live" and config.get("discovery", {}).get("enabled") and config["sources"]["trends"]:
            plan = trends_plan(config)
            run.log("screen", "budget_plan", "Dự trù sàng lọc và lịch sử trong cùng trần Trends; không tăng ngân sách", **plan)
        discovery = stage("discover", lambda: broad.discover(run, client, config))
        screening = stage("screen", lambda: screen.analyze(run, client, config, discovery))
        use_screening = config["mode"] == "live" and (config.get("discovery", {}).get("enabled") or config.get("trends", {}).get("history_scope") == "seasonal")
        missing_selected_period = (screening.get("screening_scope") == "selected_months" and config["sources"]["trends"]
                                   and config.get("trends", {}).get("required", False)
                                   and not any(row.get("rank") is not None and not product_context(row.get("keyword", ""), config) for row in screening["rows"]))
        if missing_selected_period:
            month_data = {}
            run.manifest["stages"]["monthly"] = {"status": "waiting", "reason": "Chờ phép đo trong kỳ tháng/năm đã chọn"}
        else:
            month_data = stage("monthly", lambda: monthly_keywords.analyze(run, client, config, discovery, screening))
        effective_screening = (screening if screening.get("screening_scope") == "selected_months" else
                               monthly_priority(config, discovery, screening, month_data.get("rankings", {})) if config.get("trends", {}).get("monthly_rankings", False) else screening)
        measured = {r["keyword"].casefold() for r in effective_screening["rows"] if r.get("rank") is not None
                    and not product_context(r["keyword"], config)
                    and r.get("measurement_scope", "exact_keyword") == "exact_keyword"
                    and " ".join((r.get("measurement_query") or r["keyword"]).casefold().split()) == " ".join(r["keyword"].casefold().split())}
        if use_screening and config["sources"]["trends"] and config.get("trends", {}).get("required", False) and not measured:
            seasonal_scope = config.get("trends", {}).get("history_scope") == "seasonal"
            waiting_stage = "screen"
            from .reporting.screening_diagnostic import export_screening_diagnostic
            diagnostic = export_screening_diagnostic(run.output, config, screening, run.manifest.get("usage", []))
            reason = (diagnostic["summary"] + " " + diagnostic["action"]) if diagnostic else ("Chưa có phép đo Trends hợp lệ trong đúng tháng/năm phân tích đã chọn." if seasonal_scope else "Chưa lấy được phép đo Trends hợp lệ sau các hướng khôi phục trong ngân sách.")
            run.manifest["stages"][waiting_stage].update(status="waiting", error=reason)
            for next_name, _ in STAGES[4:]:
                run.manifest["stages"][next_name] = {"status": "waiting", "reason": "Chờ sàng lọc Trends hợp lệ"}
            run.manifest.update(status="awaiting_trends", current_stage=waiting_stage, waiting_reason=reason,
                recovery={"kind": "trends_required", "can_resume": True, "message": "Xem log lỗi/key/quota rồi Chạy tiếp. Muốn đổi nguồn hoặc trần ngân sách, tạo nghiên cứu mới; bộ đếm lượt cũ không đặt lại."},
                summary={"category": config["category"], "niches": len(config["niches"]), "keywords": len(discovery["keywords"]), "selected_keywords": 0, "trends_verified_keywords": 0, "products": 0})
            run.manifest["screening_diagnostics"] = diagnostic
            run.checkpoint("waiting_trends", {"reason": reason, "screening": screening, "candidate_count": len(discovery["keywords"])})
            run.table("keyword_screening", screening["rows"])
            run.table("keywords", discovery["keywords"])
            run.log(waiting_stage, "recovery_waiting", reason, action=run.manifest["recovery"])
            run.save()
            event(reason)
            return run
        directions = stage("cluster", lambda: discover.cluster(run, client, config, discovery))
        balanced = interleave(directions, config["niches"])
        selected = stage("select", lambda: selection.ranked(config, discovery, effective_screening, directions) if use_screening else selection.select(config, balanced))
        run.log("select", "keywords_selected", selected["note"], selected=[{"keyword": r["keyword"], "rank": r.get("rank"), "search_order": r.get("search_order")} for r in selected["rows"] if r["selected"]])
        selected_ids = {direction["id"] for direction in selected["directions"]}
        directions = selected["directions"] if use_screening else [direction for direction in directions if direction["id"] in selected_ids]
        balanced = selected["directions"]
        if config.get("trends", {}).get("monthly_rankings", False):
            from math import ceil
            missing_queries = {d.get("measurement_query") or d["keyword"] for d in balanced if run.stage_data("history-" + d["id"]) is None}
            used_history = sum(u["provider"] == "serpapi" and u.get("purpose") == "trends_history" for u in run.manifest["usage"])
            from .workflow.planning import seasonal_windows
            remaining_history = ceil(len(missing_queries) / 4) * len(seasonal_windows(config)) if config.get("trends", {}).get("history_scope") == "seasonal" else ceil(len(missing_queries) / 5)
            client.history_reserve_target = used_history + remaining_history
            run.log("select", "history_reserve_updated", "Dùng lại lịch sử đã lấy cho ứng viên; chỉ giữ lượt cho keyword chọn còn thiếu", missing_keywords=len(missing_queries), remaining_history_reserve=remaining_history)
        collected = stage("search", lambda: products.collect(run, client, config, balanced, public_pages=discovery.get("web_context", [])))
        collected = stage("enrich", lambda: products.enrich(run, client, config, collected, balanced))
        histories = stage("history", lambda: history.analyze(run, client, config, balanced))
        assessed = stage("assess", lambda: opportunities.assess(config, directions, collected, histories))
        proposals = stage("ideas", lambda: ideas.generate(config, directions, collected, assessed, histories))
        ranked = stage("rank", lambda: engine.build(config, directions, collected, assessed, histories, proposals))
        data = {"schema_version": 2, "run_id": run.id, "config": config, "keywords": discovery["keywords"], "keyword_exclusions": discovery["exclusions"],
            "web_context": discovery["web_context"], "directions": directions, "keyword_selection": selected["rows"],
            "keyword_screening": screening["rows"], "screening": {k: v for k, v in screening.items() if k not in {"rows", "month_data"}}, "discovery_sources": discovery.get("discovery_sources", []),
            "selection": {k: v for k, v in selected.items() if k not in {"directions", "rows"}}, **collected, "histories": histories, "assessments": assessed,
            "ideas": proposals, "rankings": ranked, "review_themes": reviews.themes(collected["reviews"])}
        data["discovery_summary"] = discovery.get("summary", {})
        data["research_focus"] = discovery.get("research_focus", {})
        data["keyword_histories"] = month_data.get("histories") or histories
        candidate_metadata = [{**k, **{field: metric.get(field) for field in ("measurement_query", "measurement_scope") if metric.get(field)}} for k in data["keywords"] for metric in [next((m for m in screening["rows"] if m["keyword_id"] == k["id"]), {})]]
        data["keyword_monthly"] = month_data.get("rankings") if month_data.get("rankings", {}).get("rows") else build_keyword_monthly(config, candidate_metadata, histories)
        data["commentary"] = stage("commentary", lambda: commentary.generate(run, client, config, data))
        data["product_history"] = summarize_product_history(run.db, data["products"], config["history_years"], config["as_of_date"])
        run.save_dataset(data)
        export_tables(run, data)
        # Re-render after every resume, including when only a source observation changed.
        run.manifest["stages"].pop("report", None)
        validation = stage("report", lambda: export(run, data))
        run.manifest.update(status="failed" if validation["errors"] else "partial" if validation["gaps"] or run.manifest["warnings"] or any(s["status"] == "partial" for s in run.manifest["stages"].values()) else "complete",
            finished_at=now(), output=str(run.output.relative_to(run.root)).replace("\\", "/"), summary={"category": config["category"], "niches": len(config["niches"]), "keywords": len(data["keywords"]), "selected_keywords": selected["selected_keywords"], "trends_verified_keywords": selected.get("trends_verified_keywords", 0), "directions": len(directions), "products": len(data["products"]), "ideas": len(proposals)})
        run.manifest.pop("failed_stage", None)
        run.save()
        event(f"{run.manifest['status']}: {run.output / 'report.html'}")
        return run
    return run


def rebuild(run_id, root=ROOT):
    run = Run(run_id, root)
    with exclusive(run):
        data = run.load_dataset()
        if data is None:
            raise ValueError("Chưa có dataset; dùng resume để chạy tiếp")
        # Pure reanalysis of already observed months; never fetch older years or
        # manufacture product prices merely because the report layout changed.
        from .forecasting.assess import forecast
        from .forecasting.seasonal import forecast as seasonal_forecast
        from .forecasting.periods import summarize
        config = data["config"]
        from .storage.database import merged_histories
        for item in merged_histories(data):
            if item.get("status") == "available" and item.get("monthly"):
                if item.get("history_scope") == "seasonal" or config.get("trends", {}).get("history_scope") == "seasonal":
                    item.update(seasonal_forecast(item["monthly"], config["history_years"], config["target_year"], config["selling_months"], config.get("trends", {}).get("history_months", item.get("collected_months", [10,11,12]))))
                else:
                    item.update(forecast(item["monthly"], config["history_years"], config["target_year"], config["selling_months"]))
                item["comparison_periods"] = summarize(item["monthly"], config.get("comparison_periods", []), item.get("evidence_ids", []))
        revised_histories = {item["direction_id"]: item for item in merged_histories(data)}
        for field in ("histories", "keyword_histories"):
            if field in data:
                data[field] = [revised_histories[item["direction_id"]] for item in data[field]]
        data["assessments"] = opportunities.assess(config, data["directions"], data, data["histories"])
        data["ideas"] = ideas.generate(config, data["directions"], data, data["assessments"], data["histories"])
        data["rankings"] = engine.build(config, data["directions"], data, data["assessments"], data["histories"], data["ideas"])
        screening = {r["keyword_id"]: r for r in data.get("keyword_screening", [])}
        candidates = [{**k, **{field: screening.get(k["id"], {}).get(field) for field in ("measurement_query", "measurement_scope") if screening.get(k["id"], {}).get(field)}} for k in data["keywords"]]
        data["keyword_monthly"] = build_keyword_monthly(config, candidates, data.get("keyword_histories") or data["histories"])
        data.setdefault("keyword_histories", data["histories"])
        data["product_history"] = summarize_product_history(run.db, data["products"], config["history_years"], config["as_of_date"])
        data["analysis_revision"] = {"at": now(), "kind": "stored_observations_reanalysis", "provider_requests": 0}
        for name, value in (("history", data["histories"]), ("assess", data["assessments"]), ("ideas", data["ideas"]), ("rank", data["rankings"])):
            run.checkpoint(name, value)
        run.save_dataset(data)
        export_tables(run, data)
        validation = export(run, data)
        monthly_data = {"status": data["keyword_monthly"]["status"], "histories": data["keyword_histories"], "rankings": data["keyword_monthly"],
                        "note": "Tính bảng tháng từ chuỗi đã lưu; không mở rộng ứng viên hoặc gửi API nghiên cứu mới."}
        run.checkpoint("monthly", monthly_data)
        for name, value in (("monthly", monthly_data), ("history", data["histories"]), ("assess", data["assessments"]), ("rank", data["rankings"]), ("report", validation)):
            run.manifest["stages"].setdefault(name, {}).update(outcome(name, value, config))
        run.manifest["status"] = "failed" if validation["errors"] else "partial" if validation["gaps"] or any(s.get("status") == "partial" for s in run.manifest["stages"].values()) or run.manifest.get("warnings") else "complete"
        run.manifest.setdefault("summary", {})["ideas"] = len(data["ideas"])
        run.manifest["report_rebuilt_at"] = now()
        run.save()
    return run
