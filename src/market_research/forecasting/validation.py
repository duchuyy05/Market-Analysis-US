"""Leakage-free historical validation and transparent stability measures."""
from math import sqrt
import calendar
from statistics import mean, median


def metrics(rows, field="prediction"):
    usable = [r for r in rows if r.get("actual") is not None and r.get(field) is not None]
    if not usable:
        return {"mae": None, "rmse": None, "wape_pct": None, "smape_pct": None, "n": 0}
    errors = [abs(r["actual"] - r[field]) for r in usable]
    denominator = sum(abs(r["actual"]) for r in usable)
    smape = [2 * abs(r["actual"] - r[field]) / (abs(r["actual"]) + abs(r[field])) if abs(r["actual"]) + abs(r[field]) else 0 for r in usable]
    return {"mae": round(mean(errors), 4), "rmse": round(sqrt(mean(e*e for e in errors)), 4),
            "wape_pct": round(sum(errors)/denominator*100, 3) if denominator > 0 else None,
            "smape_pct": round(mean(smape)*100, 3), "n": len(usable)}


def skill(model, baseline):
    if model["mae"] is None or baseline["mae"] is None or model["n"] != baseline["n"]:
        return None
    if baseline["mae"] == 0:
        return 0.0 if model["mae"] == 0 else None
    return round((baseline["mae"] - model["mae"]) / baseline["mae"] * 100, 3)


def correlation(left, right):
    lm, rm = mean(left), mean(right)
    covariance = sum((l-lm)*(r-rm) for l, r in zip(left, right))
    denominator = sqrt(sum((l-lm)**2 for l in left) * sum((r-rm)**2 for r in right))
    return max(-1.0, min(1.0, covariance/denominator)) if denominator else 1.0 if left == right else None


def validate(months, history_years, target_year, selling_months, usable_years, annual_cv, peak_consistency, *, analysis_months=None, scope="full_year"):
    analysis_months = sorted(set(analysis_months if analysis_months is not None else range(1, 13)))
    if not analysis_months or any(type(m) is not int or not 1 <= m <= 12 for m in analysis_months):
        raise ValueError("Tháng kiểm chứng phải thuộc 1–12")
    selected = sorted(set(y for y in history_years if y < target_year))
    usable = sorted(set(y for y in usable_years if y in selected))
    by_period = {(r["year"], r["month"]): r for r in months}
    folds, out_of_fold = [], []
    # At least two earlier cycles are needed for a model comparison distinct
    # from copying one previous year. Target-year observations are never fitted.
    # A complete zero/low-interest year is still a valid test outcome: excluding
    # those holdouts would hide failures to anticipate a demand decline.
    test_years = [y for y in selected if all(by_period.get((y, m), {}).get("status") == "complete" for m in analysis_months)]
    for holdout in test_years:
        train = [y for y in usable if y < holdout]
        if len(train) < 2:
            continue
        rows = []
        baseline_year = holdout - 1
        for month in analysis_months:
            actual = by_period[holdout, month]["value"]
            baseline_row = by_period.get((baseline_year, month), {})
            baseline = baseline_row.get("value") if baseline_row.get("status") == "complete" and baseline_year in selected else None
            rows.append({"year": holdout, "month": month, "actual": actual,
                         "prediction": round(median(by_period[y, month]["value"] for y in train), 4),
                         "baseline": baseline, "selling_month": month in selling_months})
        model, baseline = metrics(rows), metrics(rows, "baseline")
        folds.append({"train_years": train, "test_year": holdout, "baseline_year": baseline_year,
                      "months_tested": len(rows), "metrics": model, "baseline_metrics": baseline,
                      "skill_pct": skill(model, baseline), "rows": rows})
        out_of_fold.extend(rows)
    model, baseline = metrics(out_of_fold), metrics(out_of_fold, "baseline")
    selling_rows = [r for r in out_of_fold if r["selling_month"]]
    covered = sum(min(max(0, by_period.get((year, month), {}).get("observed_days", 0)), calendar.monthrange(year, month)[1])
                  for year in selected for month in analysis_months)
    requested = sum(calendar.monthrange(year, month)[1] for year in selected for month in analysis_months)
    coverage = round(covered/requested*100, 2) if requested else 0.0
    reasons = []
    improvement = skill(model, baseline)
    if len(folds) < 2:
        reasons.append("Có dưới hai năm kiểm chứng độc lập; chưa đủ căn cứ đánh giá độ ổn định sai số")
    if coverage < 95:
        reasons.append("Lịch sử thiếu ngày/tháng; độ phủ dưới 95%")
    if len(usable) < len(selected):
        reasons.append("Một số năm được chọn chưa đủ tín hiệu hoặc chưa đủ chuỗi")
    if baseline["n"] < model["n"]:
        reasons.append("Thiếu năm liền trước để tính mốc cơ sở cho một số phép kiểm chứng")
    if improvement is None:
        reasons.append("Chưa tính được mức cải thiện so với mốc cơ sở trên cùng mẫu")
    elif improvement < 0:
        reasons.append("Sai số lớn hơn cách dùng cùng tháng năm trước trong mẫu kiểm chứng")
    elif baseline["mae"] == 0:
        reasons.append("Mốc cơ sở đã có sai số bằng 0 trong mẫu; chưa chứng minh lợi thế mô hình")
    level = "insufficient" if not folds else "limited"
    if len(folds) >= 2 and coverage >= 95 and model["wape_pct"] is not None and model["wape_pct"] <= 35 and improvement is not None and improvement >= 0:
        level = "moderate"
    if len(folds) >= 3 and coverage >= 95 and len(usable) == len(selected) and model["wape_pct"] is not None and model["wape_pct"] <= 20 and improvement is not None and improvement > 0:
        level = "stronger_evidence"
    if not reasons:
        reasons.append("Có nhiều năm kiểm chứng và sai số so được với mốc cơ sở; vẫn là bằng chứng trong mẫu lịch sử")
    periods = []
    for year in selected:
        chosen = [by_period.get((year, m), {}) for m in selling_months]
        valid = [r for r in chosen if r.get("status") == "complete" and r.get("value") is not None]
        record = {"year": year, "selling_months": list(selling_months), "mean_index": round(mean(r["value"] for r in valid), 4) if len(valid) == len(selling_months) else None,
                  "coverage_pct": round(len(valid)/len(selling_months)*100, 2), "yoy_pct": None,
                  "peak_month": max(valid, key=lambda r: r["value"])["month"] if valid and max(r["value"] for r in valid) > 0 else None,
                  "status": "complete" if len(valid) == len(selling_months) else "partial" if valid else "unavailable"}
        previous = next((r for r in periods if r["year"] == year-1), None)
        if previous and previous["mean_index"] is not None and previous["mean_index"] > 0 and record["mean_index"] is not None:
            record["yoy_pct"] = round((record["mean_index"]/previous["mean_index"]-1)*100, 3)
        periods.append(record)
    correlations = [correlation([by_period[a, m]["value"] for m in analysis_months], [by_period[b, m]["value"] for m in analysis_months]) for a, b in zip(usable, usable[1:])] if len(analysis_months) >= 2 else []
    correlations = [r for r in correlations if r is not None]
    profile = round(mean(correlations), 4) if correlations else None
    stability = "insufficient" if len(usable) < 2 else "stable" if annual_cv is not None and annual_cv <= .25 and (len(analysis_months) == 1 or profile is not None and profile >= .6) else "variable"
    return {"validation": {"folds": folds, "metrics": model, "baseline_metrics": baseline,
                "selling_metrics": metrics(selling_rows), "selling_baseline_metrics": metrics(selling_rows, "baseline"), "skill_pct": improvement,
                "confidence": {"level": level, "reasons": reasons, "coverage_pct": coverage, "fold_count": len(folds)},
                "method": "rolling_origin_median_same_month_v1", "analysis_months": analysis_months, "scope": scope,
                "limitation": "Sai số của chỉ số Trends trên dữ liệu tải hồi cứu; mức bằng chứng định tính không phải xác suất chính xác hay kiểm chứng doanh số sản phẩm." if scope == "full_year" else "Sai số chỉ trong các tháng đã thu trên thang anchor=100; không đánh giá các tháng ngoài phạm vi, lượng tìm kiếm tuyệt đối hoặc doanh số."},
            "same_period": periods,
            "seasonal_stability": {"status": stability, "annual_cv": annual_cv, "profile_correlation": profile,
                "peak_consistency": peak_consistency, "years_compared": usable,
                "scope": scope, "analysis_months": analysis_months,
                "thresholds": {"stable_cv_max": .25, "profile_correlation_min": .6}}}
