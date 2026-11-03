"""Python-generated ideas: concrete sample + explicit inference + next test."""
import re
from ..common import identity, text
from ..analysis.reviews import IMPROVEMENTS
from ..business.domain import active, classify_product
from .selection import verified_months, selected_month_reason

MODEL_FIELDS = ("shape", "style", "format", "layout", "binding", "finish", "print_method", "structure", "material", "dimensions", "size", "special_feature", "color", "unit_count", "weight", "brand")


def market_evidence(product, samples, reviews, all_reviews, history, config, direction=None):
    """Observed listing signals and their coverage, separate from an idea."""
    product_ids = {p["product_id"] for p in samples}
    direction_reviews = [r for r in all_reviews if r["product_id"] in product_ids]
    priced = [p["price"] for p in samples if p.get("price") is not None and p.get("currency") == "USD"]
    folds = history.get("validation", {}).get("folds", [])
    direction = direction or {}
    keyword = direction.get("keyword") or direction.get("name")
    measured_query = direction.get("measurement_query") or history.get("measurement_query") or keyword
    return {"sample_product_id": product["product_id"], "sample_scope": product.get("detail_status", "search_only"),
        "candidate_keyword": keyword, "measurement_query": measured_query,
        "measurement_scope": direction.get("measurement_scope") or history.get("measurement_scope", "exact_keyword"),
        "analysis_months": list(config.get("selling_months") or []),
        "requested_months": list(direction.get("selection_months") or config.get("selling_months") or []),
        "verified_months": verified_months(direction),
        "qualifying_months": verified_months(direction),
        "monthly_metrics": direction.get("monthly_metrics", []),
        "peak_month": direction.get("peak_month"), "peak_relative_interest": direction.get("peak_relative_interest"),
        "analysis_year": direction.get("analysis_year") or config.get("trends", {}).get("analysis_year"),
        "selection_basis": direction.get("selection_basis"),
        **{key: direction[key] for key in ("content_focus", "design_subject_terms", "design_content_status", "source_design") if key in direction},
        "sample_image_url": product.get("thumbnail"),
        "analysis_windows": direction.get("analysis_windows", []),
        "selected_month_observations": direction.get("analysis_observations", []),
        "historical_analysis_years": list(config.get("history_years") or []),
        "historical_measurement_query": history.get("measurement_query"),
        "observed_model_features": {field: product["attributes"][field] for field in MODEL_FIELDS
            if product.get("attributes", {}).get(field, {}).get("status") == "observed"},
        "price": product.get("price"), "currency": product.get("currency"), "observed_at": product.get("observed_at"),
        "purchase_badge": product.get("purchase_badge"), "purchase_lower_bound": product.get("purchase_lower_bound"),
        "listing_rating": product.get("rating"), "listing_review_count": product.get("review_count"),
        "sample_reviews_collected": len(reviews), "direction_sample_count": len(samples),
        "direction_detail_count": sum(p.get("detail_status") == "available" for p in samples),
        "direction_reviews_collected": len(direction_reviews), "direction_products_with_reviews": len({r["product_id"] for r in direction_reviews}),
        "observed_usd_price_range": [min(priced), max(priced)] if priced else None,
        "price_scope": "listing_prices_not_equivalent_unit_costs_shipping_or_tax",
        "usable_history_years": history.get("usable_years", []), "backtest_years": [f["test_year"] for f in folds],
        "historical_growth_pct": history.get("growth_pct"), "current_yoy_growth_pct": history.get("current_growth_pct"),
        "selling_window_fit_pct": history.get("selling_window_fit_pct"),
        "selling_month_forecasts": [{k: row.get(k) for k in ("year", "month", "prediction", "historical_min", "historical_max")}
            for row in history.get("forecast", []) if row.get("month") in config.get("selling_months", []) and row.get("prediction") is not None],
        "evidence_ids": sorted(set(product["evidence_ids"] + history.get("evidence_ids", []) + direction.get("evidence_ids", []))),
        "limitation": "Nhãn mua/sao là tín hiệu listing tại thời điểm lấy, không phải doanh số của tháng lịch sử đã chọn. Trends đo mức quan tâm tìm kiếm của truy vấn ghi rõ; không suy nhu cầu một kiểu dáng, kết cấu, chất liệu, hoàn thiện hoặc họa tiết cụ thể từ phép đo loại hàng rộng. Chưa có doanh số hoặc lợi nhuận đã xác minh."}


def generate(config, directions, collected, assessment, histories):
    ideas = []
    checks = {r["product_id"]: r for r in assessment["product_checks"]}
    by_assessment = {r["direction_id"]: r for r in assessment["directions"]}
    by_history = {r["direction_id"]: r for r in histories}
    for d in directions:
        a = by_assessment[d["id"]]
        samples = [p for p in collected["products"] if d["id"] in p["direction_ids"] and checks[p["product_id"]]["status"] != "excluded"
                   and (not active(config) or classify_product(p, config)["status"] == "allowed")]
        if not samples:
            continue
        samples.sort(key=lambda p: (checks[p["product_id"]]["status"] != "eligible", p["purchase_lower_bound"] is None, -(p["purchase_lower_bound"] or 0), p["product_id"]))
        product = samples[0]
        reviews = [r for r in collected["reviews"] if r["product_id"] == product["product_id"]]
        improvement, test, quoted = None, None, None
        for r in reviews:
            for pattern, proposed, action in IMPROVEMENTS:
                match = re.search(pattern, r["text"], re.I)
                if match:
                    improvement, test = proposed, action
                    quoted = {"review_id": r["id"], "text": r["text"][max(0, match.start()-35):match.end()+100], "evidence_ids": r["evidence_ids"]}
                    break
            if quoted:
                break
        attrs = [f"{field}: {text(product['attributes'][field]['value'])}" for field in MODEL_FIELDS
                 if product.get("attributes", {}).get(field, {}).get("status") == "observed"][:3]
        specification = "; ".join(attrs) or "quy cách mẫu cần kiểm tra thêm trên listing"
        history = by_history.get(d["id"], {})
        peaks = history.get("peak_months", [])
        peak_label = "Cao điểm trong các tháng đã thu: " if history.get("analysis_scope") == "selected_months" else "Cao điểm lịch sử: "
        timing = peak_label + "; ".join(str(p["year"]) + " tháng " + str(p["month"]) for p in peaks) + ". Đây là căn cứ tham khảo cho kỳ bán." if peaks else "Chưa đủ lịch sử để xác định thời điểm chắc chắn; cần kiểm chứng nhu cầu hiện tại."
        if d.get("selection_basis") == "selected_month_observations":
            selection_label = "Mẫu được chọn bằng quan sát Trends của đúng keyword. " if verified_months(d) else "Mẫu đang khảo sát; chưa xác minh tháng có tín hiệu Trends. "
            timing = (selection_label + selected_month_reason(d) + " " +
                      "Kết quả quan tâm trong kỳ độc lập với dự báo mùa vụ nhiều năm. " + timing)
        basis = "Có nhãn mua hiện tại trên mẫu đối chiếu; nhãn này không phải doanh số dự báo." if product["purchase_lower_bound"] is not None else "Đã tìm thấy mẫu tương ứng; chưa có nhãn mua để xác nhận tín hiệu mua."
        target = d.get("customer_hypothesis") or "Giả thuyết người mua/người nhận từ mô tả cần được kiểm chứng"
        target_status = "hypothesis_from_brief_not_demographic_research"
        listing_audience = None
        listing = product["title"] + " " + product.get("description", "")
        for word, label in (("kids|children", "trẻ em"), ("adults", "người lớn"), ("women", "phụ nữ"), ("men", "nam giới"), ("families|family", "gia đình"), ("teachers", "giáo viên")):
            if re.search(r"\bfor\s+(?:the\s+)?(?:" + word + r")\b", listing, re.I):
                listing_audience = label
                break
        alternatives = [{k: p.get(k) for k in ("product_id", "title", "price", "currency", "url", "detail_status", "evidence_ids")}
                        | {"constraint_status": checks[p["product_id"]]["status"]} for p in samples[1:4]]
        gaps = list(checks[product["product_id"]]["pending"])
        if not reviews:
            gaps.append("Chưa thu thập phản hồi của đúng mẫu được chọn; không mượn phản hồi từ mẫu khác.")
        if product.get("detail_status") != "available":
            gaps.append("Mẫu mới có dữ liệu thẻ tìm kiếm; chưa xác minh trang chi tiết.")
        if product.get("price") is None or product.get("currency") != "USD":
            gaps.append("Chưa có giá USD đủ rõ cho mẫu được chọn.")
        if not history.get("monthly"):
            gaps.append("Chưa có chuỗi lịch sử của truy vấn đo để đối chiếu các năm.")
        if not history.get("validation", {}).get("folds"):
            gaps.append("Chưa có kiểm chứng hồi cứu để đánh giá sai số dự báo.")
        if not quoted:
            gaps.append("Chưa có phản hồi hỗ trợ một điểm cải tiến cụ thể; chưa xác lập khác biệt so với mẫu đối chiếu.")
        if any(v.get("status") == "conflicting" for v in product.get("attributes", {}).values()):
            gaps.append("Thông số listing có giá trị khác nhau giữa các mục; cần kiểm tra đúng biến thể.")
        gaps.extend(product.get("suitability_notes") or ["Khớp keyword chỉ là bước lọc sơ bộ; cần kiểm tra công dụng, người nhận và quy cách thực tế."])
        gaps.append("Các giá listing chưa được xác nhận tương đương về quy cách/biến thể, phí vận chuyển và thuế.")
        evidence = market_evidence(product, samples, reviews, collected["reviews"], history, config, d)
        keyword = d.get("keyword") or d["name"]
        model_label = d["name"] if d["name"].casefold() == keyword.casefold() else d["name"] + " (" + keyword + ")"
        subject = (d.get("source_design") or {}).get("subject") or d.get("design_subject_terms")
        content_label = "Nội dung mẫu: " + subject + "; keyword: " + keyword if subject and d.get("content_focus") == "designs" else model_label
        ideas.append({"id": identity("I", d["id"], product["product_id"]), "direction_id": d["id"], "niche_id": d["niche_id"],
            "title": "Khảo sát dòng " + model_label, "sell_what": content_label + ("; " + improvement if improvement else "; đối chiếu quy cách và thông tin sản phẩm trước khi chọn mẫu thử"),
            **{key: evidence[key] for key in ("content_focus", "design_subject_terms", "design_content_status", "source_design", "sample_image_url") if key in evidence},
            "candidate_keyword": keyword, "measurement_query": evidence["measurement_query"],
            "measurement_scope": evidence["measurement_scope"], "analysis_months": evidence["analysis_months"],
            "analysis_year": evidence["analysis_year"], "selection_basis": evidence["selection_basis"],
            "requested_months": evidence["requested_months"], "verified_months": evidence["verified_months"],
            "qualifying_months": evidence["qualifying_months"], "monthly_metrics": evidence["monthly_metrics"],
            "peak_month": evidence["peak_month"], "peak_relative_interest": evidence["peak_relative_interest"],
            "customer": target, "customer_status": target_status, "why_now": timing + " " + basis,
            "listing_audience": listing_audience, "listing_audience_status": "seller_stated_not_verified_buyers" if listing_audience else "not_observed",
            "sample_product_id": product["product_id"], "sample_url": product["url"], "observed_specification": specification,
            "alternatives": alternatives, "market_evidence": evidence, "evidence_gaps": list(dict.fromkeys(gaps)),
            "business_fit": classify_product(product, config),
            "differentiation_evidence": {"status": "review_grounded_hypothesis" if quoted else "not_established", "observed_issue": quoted["text"] if quoted else None,
                "proposed_change": improvement, "evidence_ids": quoted["evidence_ids"] if quoted else [], "note": "Phản hồi dẫn tới giả thuyết thử cải tiến; chưa chứng minh sản phẩm đề xuất có khác biệt đã thành công."},
            "improvement": improvement, "improvement_evidence_ids": quoted["evidence_ids"] if quoted else [], "review_quote": quoted,
            "next_test": test or "Xác minh quy cách, nhu cầu người nhận, giá vốn và thời gian chuẩn bị trước khi thử bán",
            "status": a["status"], "generation_method": "python_rules_v3_evidence", "evidence_ids": sorted(set(evidence["evidence_ids"] + [e for p in alternatives for e in p.get("evidence_ids", [])] + (quoted["evidence_ids"] if quoted else []))),
            "limitations": list(dict.fromkeys(gaps + ["Chưa có giá vốn, phí sàn và thử nghiệm bán để kết luận lợi nhuận.", "Idea là giả thuyết cần kiểm chứng; một review không đại diện toàn bộ khách hàng."]))})
    return ideas
