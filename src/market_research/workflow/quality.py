"""Stage completion is separate from a candidate's market suitability."""


def unavailable(data):
    if isinstance(data, dict):
        return data.get("status") in {"unavailable", "failed"} or any(unavailable(v) for v in data.values())
    if isinstance(data, list):
        return any(unavailable(v) for v in data)
    return False


def has_forecast(history):
    return any(row.get("prediction") is not None for row in history.get("forecast", []))


def has_backtest(history):
    validation = history.get("validation", {})
    return bool(validation.get("folds")) and validation.get("metrics", {}).get("mae") is not None


def outcome(stage, data, config):
    if stage=="search":
        failed=sum(row.get("status") in {"blocked","unavailable","limited"} for row in data.get("source_status",[]))
        return {"status":"partial" if failed or not data.get("products") else "complete","note":f"Có {len(data.get('products',[]))} mẫu và {len(data.get('discussions',[]))} thảo luận; {failed} nhánh bị chặn/thiếu. Thảo luận không phải doanh số hay review đã xác minh."}
    if isinstance(data, dict) and data.get("status") == "skipped":
        return {"status": "skipped", "note": "Bước không áp dụng với cấu hình này."}
    if stage == "commentary" and (config["mode"] == "offline" or not config["llm"]["enabled"] or not config["llm"]["commentary"]):
        return {"status": "skipped", "note": "Nhận định LLM bổ sung đã tắt; báo cáo vẫn được dựng bằng Python."}
    if stage == "screen":
        rows = data.get("rows", [])
        missing = sum(r.get("status") not in {"available", "low_signal"} for r in rows)
        low = sum(r.get("status") == "low_signal" for r in rows)
        if data.get("selection_basis") == "selected_month_observations":
            partial = sum(bool(r.get("partial_period")) for r in rows)
            months = ", ".join(map(str, data.get("selection_months", [])))
            return {"status": "partial" if missing or partial or not rows else "complete",
                    "note": f"Đã đo {len(rows)-missing}/{len(rows)} mẫu/keyword trong tháng {months} năm {data.get('analysis_year')}; {low} ít tín hiệu; {partial} có kỳ quan sát chưa đầy đủ; thiếu phép đo: {missing}."}
        return {"status": "partial" if missing or not rows else "complete",
                "note": f"Đã đo {len(rows)-missing}/{len(rows)} ứng viên; {low} ít tín hiệu được loại hợp lệ. Thiếu phép đo: {missing}."}
    if stage == "monthly":
        coverage = data.get("rankings", {}).get("coverage", {})
        return {"status": "partial" if data.get("status") in {"partial", "unavailable"} else "complete", "note": data.get("note") or str(coverage)}
    if stage == "select":
        selected, requested = data.get("selected_keywords", 0), data.get("requested")
        missing = requested is not None and selected < requested
        return {"status": "partial" if missing else "complete", "note": f"Chọn {selected}/{requested if requested is not None else 'không giới hạn'} keyword. Kết quả loại ở bước sàng lọc không làm bước chọn bị lỗi."}
    if stage == "cluster":
        fallback = sum(d.get("grouping_method") == "seed_rules" for d in data)
        llm = sum(d.get("grouping_method") == "llm" for d in data)
        return {"status": "complete", "note": f"Gom {len(data)} hướng: {fallback} theo seed, {llm} dùng LLM, {len(data)-fallback-llm} chưa ghi phương pháp (lượt cũ)."}
    if stage == "history":
        observed = sum(h.get("status") == "available" and bool(h.get("monthly")) for h in data)
        forecasted = sum(has_forecast(h) for h in data)
        tested = sum(has_backtest(h) for h in data)
        return {"status": "complete" if observed == len(data) and forecasted == len(data) and tested == len(data) and data else "partial",
                "note": f"Có lịch sử {observed}/{len(data)} hướng; có dự báo {forecasted}/{len(data)} hướng; có kiểm chứng hồi cứu {tested}/{len(data)} hướng. Có chuỗi dữ liệu chưa đồng nghĩa đủ tín hiệu để dự báo và kiểm chứng."}
    if stage == "report":
        return {"status": "partial" if data.get("gaps") or data.get("errors") else "complete",
                "note": f"Đã dựng báo cáo; {len(data.get('gaps', []))} khoảng trống dữ liệu và {len(data.get('errors', []))} lỗi kiểm tra."}
    return {"status": "partial" if unavailable(data) else "complete", "note": "Có chỉ tiêu thiếu bằng chứng; xem dữ liệu và log của bước." if unavailable(data) else "Đã xử lý xong bước."}
