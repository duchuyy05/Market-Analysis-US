"""Versioned rubric; missing facts remain unknown, never numerical zero."""
import re
import calendar
from datetime import date, timedelta

from ..common import text
from .reviews import IMPROVEMENTS
from ..business.domain import classify_product


def constraints(product, config):
    body = " ".join((product["title"], product.get("description", ""), " ".join(text(a.get("value")) for a in product.get("attributes", {}).values() if a.get("status") == "observed")))
    failed, pending = [], []
    company_fit = classify_product(product, config)
    if company_fit["status"] == "excluded":
        failed.append(company_fit["reason"])
    elif company_fit["status"] == "pending_verification":
        pending.append(company_fit["reason"])
    if config["price_range"]:
        if product["price"] is None or product["currency"] != "USD":
            pending.append("Chưa có giá USD để xác minh khoảng giá")
        elif not config["price_range"][0] <= product["price"] <= config["price_range"][1]:
            failed.append("Giá mẫu ngoài khoảng yêu cầu")
    for feature in config["required_features"]:
        if re.search(r"\b(?:not|non|no)\s+" + re.escape(feature) + r"\b", body, re.I):
            failed.append("Nguồn phủ định đặc tính bắt buộc: " + feature)
        elif not re.search(re.escape(feature), body, re.I):
            pending.append("Chưa xác minh đặc tính bắt buộc: " + feature)
    for feature in config["excluded_features"]:
        if re.search(re.escape(feature), body, re.I):
            failed.append("Nguồn đề cập đặc tính loại trừ: " + feature)
        else:
            pending.append("Chưa có xác nhận loại trừ: " + feature)
    if re.search(r"currently unavailable|out of stock", product.get("availability", ""), re.I):
        failed.append("Listing công bố hết hàng/không khả dụng")
    return {"status": "excluded" if failed else "pending_verification" if pending else "eligible", "failed": failed, "pending": pending, "business_fit": company_fit}


def assess(config, directions, collected, histories):
    by_history = {h["direction_id"]: h for h in histories}
    products = collected["products"]
    product_checks = [{"product_id": p["product_id"], **constraints(p, config), "evidence_ids": p["evidence_ids"]} for p in products]
    checks = {p["product_id"]: p for p in product_checks}
    output = []
    for direction in directions:
        examples = [p for p in products if direction["id"] in p["direction_ids"]]
        eligible = [p for p in examples if checks[p["product_id"]]["status"] == "eligible"]
        history = by_history.get(direction["id"], {})
        growth = history.get("current_growth_pct") if history.get("current_growth_pct") is not None else history.get("growth_pct")
        demand = "unknown" if growth is None else "positive" if growth >= 10 else "negative" if growth <= -10 else "neutral"
        purchase = "positive" if any(p["purchase_lower_bound"] is not None for p in eligible) else "unknown"
        fit = history.get("selling_window_fit_pct")
        season = "unknown" if fit is None else "positive" if fit >= 60 else "neutral" if fit >= 30 else "negative"
        lead_time = "unknown"
        if config["preparation_days"] is not None:
            ready = date.fromisoformat(config["as_of_date"]) + timedelta(days=config["preparation_days"])
            ends = [date(config["target_year"], m, calendar.monthrange(config["target_year"], m)[1]) for m in config["selling_months"]]
            lead_time = "negative" if ready > max(ends) else "positive"
            if lead_time == "negative":
                season = "negative"
            forecast_rows = history.get("forecast", [])
            feasible = [r["prediction"] for r in forecast_rows if r["month"] in config["selling_months"] and r["prediction"] is not None and date(config["target_year"], r["month"], calendar.monthrange(config["target_year"], r["month"])[1]) >= ready]
            peak = max((r["prediction"] for r in forecast_rows if r["prediction"] is not None), default=0)
            if feasible and peak > 0:
                fit = round(sum(feasible)/len(feasible)/peak*100, 2)
                season = "positive" if fit >= 60 else "neutral" if fit >= 30 else "negative"
        review_ids = [r["id"] for r in collected["reviews"] if r["product_id"] in {p["product_id"] for p in examples}]
        # Review presence alone does not prove a differentiation opportunity.
        improvement_reviews = [r for r in collected["reviews"] if r["product_id"] in {p["product_id"] for p in examples} and any(re.search(pattern, r["text"], re.I) for pattern, _, _ in IMPROVEMENTS)]
        differentiation = "positive" if improvement_reviews else "unknown"
        evidence_ids = sorted(set(history.get("evidence_ids", []) + [e for p in examples for e in p["evidence_ids"]] + [e for r in improvement_reviews for e in r["evidence_ids"]]))
        status = "shortlist" if eligible and (purchase == "positive" or demand in {"positive", "neutral"}) and season != "negative" else "watchlist" if eligible else "pending_verification" if examples and any(checks[p["product_id"]]["status"] == "pending_verification" for p in examples) else "unavailable"
        output.append({"direction_id": direction["id"], "niche_id": direction["niche_id"], "status": status,
            "demand": demand, "season": season, "purchase": purchase, "differentiation": differentiation,
            "business_fit": "positive" if eligible else "unknown", "lead_time": lead_time, "growth_pct": growth,
            "growth_scope": "selected_period_anchor_relative" if history.get("analysis_scope") == "selected_months" else "current_complete_months_yoy" if history.get("current_growth_pct") is not None else "last_two_complete_history_years",
            "metric_unit": history.get("metric_unit", "google_trends_0_100"),
            "analysis_scope": history.get("analysis_scope", "full_year"), "history_months": history.get("history_months", list(range(1, 13))),
            "stability": history.get("seasonal_stability", {}).get("status", history.get("stability", "insufficient")), "season_fit_pct": fit, "product_ids": [p["product_id"] for p in eligible],
            "all_product_ids": [p["product_id"] for p in examples], "review_ids": review_ids, "evidence_ids": evidence_ids,
            "rubric_version": "opportunity_v2", "scope": "Ưu tiên nghiên cứu trong mẫu; chưa có chi phí để kết luận lợi nhuận"})
    return {"directions": output, "product_checks": product_checks}
