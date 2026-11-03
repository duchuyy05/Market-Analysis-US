"""Explain source failure, sparse observations and budget limits separately."""
from .planning import trends_plan


def screening_diagnostics(config, screening, usage=()):
    screening = screening or {}
    rows = screening.get("rows", [])
    if not rows or "limits" not in config:
        return {}
    measured = sum(row.get("status") in {"available", "low_signal"} for row in rows)
    valid = sum(row.get("status") == "available" and row.get("rank") is not None for row in rows)
    low = sum(row.get("status") == "low_signal" for row in rows)
    missing = len(rows) - measured
    plan = trends_plan(config)
    paid_used = sum(item.get("provider") == "serpapi" and item.get("engine") == "google_trends" for item in usage)
    paid_remaining = max(0, min(plan["trends_cap"] - paid_used,
        config["limits"]["serpapi_requests"] - sum(item.get("provider") == "serpapi" for item in usage)))
    free_used = sum(item.get("provider") == "google_trends_free" for item in usage)
    free_attempts = [item for item in usage if item.get("provider") == "google_trends_free"]
    free_limited = bool(free_attempts) and "429" in str(free_attempts[-1].get("status", ""))
    free_allowed = (config.get("sources", {}).get("trends", True)
        and config.get("trends", {}).get("provider", "serpapi") in {"auto", "free"}
        and free_used < config["limits"].get("free_trends_requests", 0))
    months = screening.get("selection_months") or screening.get("history_months") or []
    year = screening.get("analysis_year")
    period = ("Tháng " + ", ".join(map(str, months)) + ("/" + str(year) if year else "")) if months else screening.get("date_range", "Kỳ đã chọn")
    blocked = not valid
    cause = "sparse_queries" if blocked and low else "source_unavailable" if blocked else "partial_measurement" if missing else "measured"
    summary = f"{period}: đã đo {measured}/{len(rows)} mẫu; {low} ít tín hiệu, {missing} chưa đo, {valid} đủ điều kiện xếp hạng."
    if free_limited:
        summary += " Trends miễn phí bị giới hạn (429)."
    summary += f" Trends trả phí đã dùng {paid_used}/{plan['trends_cap']} lượt."
    if cause == "sparse_queries":
        explanation = "Các truy vấn đã nhận dữ liệu nhưng chưa có tín hiệu đủ vững. Cụm quá dài hoặc giống mô tả kỹ thuật cần đổi thành cụm tìm kiếm tự nhiên; số 0 chuẩn hóa không chứng minh không có nhu cầu."
    elif blocked:
        explanation = "Chưa nhận đủ dữ liệu nguồn để đánh giá mẫu; xem lỗi nguồn và phần ngân sách còn lại."
    else:
        explanation = "Chỉ những tháng và mẫu đủ tín hiệu mới được xếp hạng; phần thiếu được giữ riêng."
    can_retry = blocked and missing > 0 and (paid_remaining > 0 or free_allowed)
    retry_kind = "free_only" if can_retry and paid_remaining == 0 else "sources" if can_retry else "none"
    action = ("Tạo lượt mới để sửa keyword hoặc điều chỉnh số ứng viên/ngân sách; lượt cũ giữ nguyên dữ liệu và bộ đếm."
              if cause == "sparse_queries" else "Kiểm tra nguồn, kết nối và ngân sách rồi thử lại phần chưa đo." if blocked else "Xem kết quả từng tháng trong chi tiết bước Trends.")
    return {"period": period, "candidates": len(rows), "measured": measured, "low_signal": low, "unavailable": missing,
            "valid": valid, "cause": cause, "blocked": blocked, "summary": summary, "explanation": explanation, "action": action,
            "paid_used": paid_used, "paid_cap": plan["trends_cap"], "paid_remaining": paid_remaining,
            "free_rate_limited": free_limited, "free_remaining": max(0, config["limits"].get("free_trends_requests", 0) - free_used),
            "can_retry": can_retry, "retry_kind": retry_kind,
            "retry_hint": "Chỉ thử phần chưa đo bằng nguồn miễn phí; trần trả phí đã hết và không được tăng." if retry_kind == "free_only" else
                          "Các query đã đo không được gọi lại chỉ vì ít tín hiệu; thử lại giữ nguyên bộ đếm."}
