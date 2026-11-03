"""History supports a report; it never gates discovery of a new product."""
from statistics import mean, median, pstdev
from .validation import validate


def forecast(months, history_years, target_year, selling_months):
    history_years = sorted(set(y for y in history_years if y < target_year))
    if not history_years:
        raise ValueError("Cần năm lịch sử trước năm dự báo")
    by_period = {(r["year"], r["month"]): r for r in months}
    complete_years = [y for y in history_years if all(by_period.get((y, m), {}).get("status") == "complete" for m in range(1, 13))]
    def enough_signal(year):
        rows = [by_period[year, m] for m in range(1, 13)]
        monthly_resolution = any((r.get("native_step_days") or 0) >= 27 for r in rows)
        positives = sum(r["value"] > 0 for r in rows)
        return positives >= 2 and max(r["value"] for r in rows) >= 5 and (monthly_resolution or sum(r["positive_points"] for r in rows) >= 8)
    usable = [y for y in complete_years if enough_signal(y)]
    peaks = [{"year": y, "month": max(range(1, 13), key=lambda m: by_period[y, m]["value"])} for y in usable]
    annual = [{"year": y, "mean_index": round(mean(by_period[y, m]["value"] for m in range(1, 13)), 3)} for y in usable]
    cv = pstdev(r["mean_index"] for r in annual) / mean(r["mean_index"] for r in annual) if len(annual) >= 2 and mean(r["mean_index"] for r in annual) > 0 else None
    stability = "insufficient" if len(usable) < 2 else "stable" if cv is not None and cv <= .25 else "variable"
    peak_months = [r["month"] for r in peaks]
    peak_consistency = max((peak_months.count(m)/len(peak_months) for m in set(peak_months)), default=None)
    rows, errors = [], []
    # Fixed holdout: earliest years -> final history year. No target-year fitting.
    holdout = max(history_years)
    train = [y for y in usable if y < holdout]
    for m in range(1, 13):
        if train and holdout in usable:
            actual = by_period[holdout, m]["value"]
            pred = median(by_period[y, m]["value"] for y in train)
            baseline = by_period[max(train), m]["value"]
            errors.append({"month": m, "actual": actual, "prediction": pred, "baseline": baseline})
        values = [by_period[y, m]["value"] for y in usable]
        prediction = round(median(values), 3) if len(values) >= 2 else None
        observed = by_period.get((target_year, m), {})
        rows.append({"year": target_year, "month": m, "prediction": prediction,
            "historical_min": min(values) if len(values) >= 2 else None, "historical_max": max(values) if len(values) >= 2 else None,
            "observed": observed.get("value"), "observation_status": observed.get("status", "unavailable"),
            "observed_minus_prediction": round(observed["value"]-prediction, 3) if observed.get("status") == "complete" and prediction is not None else None,
            "selling_month": m in selling_months})
    mae = round(mean(abs(r["actual"]-r["prediction"]) for r in errors), 3) if errors else None
    baseline_mae = round(mean(abs(r["actual"]-r["baseline"]) for r in errors), 3) if errors else None
    last, previous = (annual[-1]["mean_index"], annual[-2]["mean_index"]) if len(annual) >= 2 else (None, None)
    growth = round((last/previous-1)*100, 2) if previous is not None and previous >= 2 else None
    selected = [r["prediction"] for r in rows if r["selling_month"] and r["prediction"] is not None]
    all_values = [r["prediction"] for r in rows if r["prediction"] is not None]
    fit = round(mean(selected)/max(all_values)*100, 2) if selected and max(all_values, default=0) > 0 else None
    comparable = [m for m in range(1, 13) if by_period.get((target_year, m), {}).get("status") == "complete" and by_period.get((target_year-1, m), {}).get("status") == "complete"]
    previous_current = mean(by_period[target_year-1, m]["value"] for m in comparable) if comparable else None
    current_growth = round((mean(by_period[target_year, m]["value"] for m in comparable)/previous_current-1)*100, 2) if previous_current is not None and previous_current >= 2 and len(comparable) >= 2 else None
    verified = validate(months, history_years, target_year, selling_months, usable, round(cv, 4) if cv is not None else None, peak_consistency)
    return {"stability": stability, "complete_years": complete_years, "usable_years": usable,
        **verified,
        "annual_means": annual, "annual_cv": round(cv, 4) if cv is not None else None, "peak_months": peaks, "peak_consistency": peak_consistency,
        "growth_pct": growth, "current_growth_pct": current_growth, "current_comparison_months": comparable, "selling_window_fit_pct": fit, "forecast": rows,
        "backtest": {"train_years": train, "test_year": holdout, "mae": mae, "seasonal_naive_mae": baseline_mae,
            "better_than_baseline": mae < baseline_mae if mae is not None else None, "months_tested": len(errors)},
        "method": "median_same_calendar_month_v1", "thresholds": {"stable_annual_cv_max": .25, "min_annual_positive_points": 8, "min_positive_months": 2, "monthly_native_step_min_days": 27, "min_year_peak": 5},
        "notes": ["Chỉ số tương đối trên cùng chuỗi/thang; không phải lượng tìm kiếm hay doanh số.",
            "Khoảng min–max là độ phân tán lịch sử, không phải khoảng tin cậy xác suất.",
            "Từ khóa được chọn hiện tại; kiểm chứng hồi cứu không chứng minh đã khám phá cơ hội trong quá khứ.",
            "Độ tin cậy là mức bằng chứng theo số năm, độ phủ và sai số hồi cứu; không phải phần trăm xác suất đúng.",
            "Chuỗi native tháng cần tín hiệu ở ít nhất hai tháng, không áp ngưỡng tám điểm tuần cho dữ liệu tháng."]}
