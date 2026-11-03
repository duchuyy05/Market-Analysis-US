"""Forecast only observed seasonal months, on the collection's common anchor scale.

Missing months outside the requested window are never manufactured to satisfy
the full-year model. Comparisons and rolling holdouts use the same month set.
"""
from math import isfinite
from statistics import mean, median, pstdev

from .validation import validate


def _complete(row):
    value = row.get("value")
    return row.get("status") == "complete" and isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) and value >= 0


def forecast(months, history_years, target_year, selling_months, collected_months):
    selected = sorted(set(collected_months))
    if not selected or any(type(m) is not int or not 1 <= m <= 12 for m in selected):
        raise ValueError("Phân tích mùa cần các tháng thuộc 1–12")
    years = sorted(set(y for y in history_years if y < target_year))
    if not years:
        raise ValueError("Cần năm lịch sử trước năm dự báo")
    by_period = {(r["year"], r["month"]): r for r in months}
    complete = [y for y in years if all(_complete(by_period.get((y, m), {})) for m in selected)]

    def signal(year):
        rows = [by_period[year, m] for m in selected]
        positive = any(r["value"] > 0 for r in rows)
        native_month = any((r.get("native_step_days") or 0) >= 27 for r in rows)
        source_positive = sum(r.get("positive_points", 0) for r in rows)
        return positive and (native_month or source_positive >= 3)

    usable = [y for y in complete if signal(y)]
    period_means = [{"year": y, "mean_index": round(mean(by_period[y, m]["value"] for m in selected), 4),
                     "months": selected, "scope": "selected_months"} for y in usable]
    average = mean(r["mean_index"] for r in period_means) if period_means else 0
    cv = pstdev(r["mean_index"] for r in period_means) / average if len(period_means) >= 2 and average > 0 else None
    peaks = [{"year": y, "month": max(selected, key=lambda m: by_period[y, m]["value"]), "scope": "selected_months"} for y in usable]
    peak_months = [r["month"] for r in peaks]
    peak_consistency = max((peak_months.count(m)/len(peak_months) for m in set(peak_months)), default=None)
    verified = validate(months, years, target_year, selling_months, usable, round(cv, 4) if cv is not None else None,
                        peak_consistency, analysis_months=selected, scope="selected_months")
    rows = []
    for month in selected:
        values = [by_period[y, month]["value"] for y in usable]
        prediction = round(median(values), 4) if len(values) >= 2 else None
        observed = by_period.get((target_year, month), {})
        rows.append({"year": target_year, "month": month, "prediction": prediction,
            "historical_min": min(values) if len(values) >= 2 else None, "historical_max": max(values) if len(values) >= 2 else None,
            "observed": observed.get("value") if _complete(observed) else None,
            "observation_status": observed.get("status", "not_collected"),
            "observed_minus_prediction": round(observed["value"] - prediction, 4) if _complete(observed) and prediction is not None else None,
            "selling_month": month in selling_months, "metric_unit": "anchor_100"})
    selected_predictions = [r["prediction"] for r in rows if r["selling_month"] and r["prediction"] is not None]
    all_predictions = [r["prediction"] for r in rows if r["prediction"] is not None]
    fit = round(mean(selected_predictions)/max(all_predictions)*100, 3) if selected_predictions and max(all_predictions, default=0) > 0 else None
    latest = max(usable) if usable else None
    previous = latest - 1 if latest is not None else None
    growth = None
    if previous in usable:
        prior = mean(by_period[previous, m]["value"] for m in selected)
        if prior > 0:
            growth = round((mean(by_period[latest, m]["value"] for m in selected)/prior-1)*100, 3)
    folds = verified["validation"]["folds"]
    last_fold = folds[-1] if folds else {}
    metrics = last_fold.get("metrics", {})
    baseline = last_fold.get("baseline_metrics", {})
    confidence = verified["validation"]["confidence"]
    if any(m not in selected for m in selling_months):
        confidence["reasons"].append("Một số tháng bán nằm ngoài phạm vi thu thập; không có dự báo cho các tháng đó")
    confidence["reasons"].append("Chỉ kiểm chứng các tháng đã chọn; không kết luận mùa vụ hoặc độ ổn định cả năm")
    return {"stability": verified["seasonal_stability"]["status"], "complete_years": complete, "usable_years": usable,
        **verified, "analysis_scope": "selected_months", "history_scope": "seasonal", "history_months": selected,
        "collected_months": selected, "metric_unit": "anchor_100", "period_means": period_means,
        "period_cv": round(cv, 4) if cv is not None else None,
        # Compatibility aliases, explicitly scoped to the period, never full-year means.
        "annual_means": period_means, "annual_cv": round(cv, 4) if cv is not None else None,
        "peak_months": peaks, "peak_scope": "selected_months", "peak_consistency": peak_consistency,
        "growth_pct": growth, "current_growth_pct": None, "current_comparison_months": [],
        "selling_window_fit_pct": fit, "forecast": rows,
        "backtest": {"train_years": last_fold.get("train_years", []), "test_year": last_fold.get("test_year"),
            "mae": metrics.get("mae"), "seasonal_naive_mae": baseline.get("mae"),
            "better_than_baseline": metrics.get("mae") < baseline.get("mae") if metrics.get("mae") is not None and baseline.get("mae") is not None else None,
            "months_tested": last_fold.get("months_tested", 0), "scope": "selected_months"},
        "method": "median_same_selected_month_anchor_ratio_v1",
        "notes": ["Thang so anchor=100 có thể vượt 100; không phải chỉ số Google Trends gốc 0–100, số lượt tìm kiếm hoặc doanh số.",
                  "Cao điểm và độ phù hợp chỉ xét trong các tháng đã thu, không suy ra cao điểm của cả năm.",
                  "Dự báo năm đích chỉ dùng các năm lịch sử; tháng ngoài phạm vi không được nội suy hoặc thay bằng 0.",
                  "Khoảng min–max là độ phân tán quan sát, không phải khoảng tin cậy xác suất."]}
