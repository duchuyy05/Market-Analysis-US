"""A December model may qualify without claiming demand throughout Q4."""
from market_research.workflow.selection import ranked, selected_month_reason
from market_research.workflow.ideas import generate
from market_research.reporting.document import Document
from market_research.reporting.keywords import screening_details
from market_research.reporting.summary import selection_reason


def december_model():
    config = {"brief": "So sánh mẫu móc khóa acrylic", "selling_months": [10, 11, 12], "history_years": [2023, 2024],
        "business": {"profile": "general"}, "sources": {"trends": True}, "trends": {"required": True, "history_scope": "seasonal", "history_months": [10, 11, 12]},
        "limits": {"top_keywords": 1}, "niches": [{"id": "N", "name": "Móc khóa", "customer_hypothesis": "Người mua quà"}]}
    keyword = {"id": "K", "text": "snowflake acrylic keychain", "niche_id": "N", "evidence_ids": ["E-discovery"]}
    monthly = [{"year": 2025, "month": month, "status": status, "relative_interest": ratio, "rank": rank, "score": 50 if rank else None,
        "observed_days": days, "positive_points": positive, "required_positive_points": 3, "reason": status}
        for month, status, ratio, rank, days, positive in [(10, "low_signal", 0, None, 31, 0), (11, "unavailable", None, None, 0, 0), (12, "available", .2, 1, 31, 5)]]
    row = {"keyword_id": "K", "keyword": keyword["text"], "niche_id": "N", "measurement_query": keyword["text"], "measurement_scope": "exact_keyword",
        "status": "available", "relative_interest": .2, "score": 50, "rank": 1, "evidence_ids": ["E-screen"],
        "analysis_year": 2025, "selection_basis": "selected_month_observations", "selection_months": [10, 11, 12],
        "monthly_metrics": monthly, "qualifying_months": [12], "missing_months": [11], "peak_month": 12, "peak_relative_interest": .2, "observed_days": 62}
    screening = {"method": "selected_months_observed_interest_v1", "selection_basis": "selected_month_observations", "selection_months": [10, 11, 12],
        "analysis_year": 2025, "aggregation": "peak_qualifying_month_v1", "note": "So sánh riêng từng tháng.", "rows": [row]}
    discovery = {"keywords": [keyword]}
    selection = ranked(config, discovery, screening, [])
    return config, discovery, screening, selection


def test_december_proof_survives_selection_and_idea_without_upgrading_october():
    config, _, screening, selection = december_model()
    chosen = selection["rows"][0]
    direction = selection["directions"][0]
    assert selection["requested_months"] == [10, 11, 12] and selection["verified_months"] == [12]
    assert direction["selection_months"] == [10, 11, 12] and direction["verified_months"] == [12]
    assert direction["monthly_metrics"] == screening["rows"][0]["monthly_metrics"]
    assert "Đủ tín hiệu tháng 12 năm 2025" in chosen["reason"]
    assert "Đủ tín hiệu tháng 10" not in chosen["reason"]
    assert "31 ngày ở tháng này" in selection_reason(chosen) and "62 ngày" not in selection_reason(chosen)
    product = {"product_id": "P", "title": direction["keyword"], "direction_ids": [direction["id"]], "price": 15, "currency": "USD",
        "url": "https://www.amazon.com/dp/B012345678", "purchase_lower_bound": 100, "detail_status": "available", "description": "", "attributes": {}, "evidence_ids": ["E-listing"]}
    assessed = {"directions": [{"direction_id": direction["id"], "status": "watchlist"}], "product_checks": [{"product_id": "P", "status": "eligible", "pending": []}]}
    idea = generate(config, [direction], {"products": [product], "reviews": []}, assessed, [])[0]
    assert idea["requested_months"] == [10, 11, 12] and idea["verified_months"] == [12]
    assert idea["peak_month"] == 12 and idea["peak_relative_interest"] == .2
    assert "Đủ tín hiệu tháng 12 năm 2025" in idea["why_now"] and "Đủ tín hiệu tháng 10" not in idea["why_now"]


def test_report_keeps_october_zero_and_november_missing_separate_from_december_rank():
    config, discovery, screening, selection = december_model()
    data = {"config": config, "screening": screening, "selection": selection, "keyword_selection": selection["rows"], "keyword_screening": screening["rows"], "keywords": discovery["keywords"]}
    doc = Document()
    screening_details(doc, data)
    evidence = next(block for block in doc.blocks if block["type"] == "table" and block["headers"][1] == "Tháng/năm")
    october, november, december = evidence["rows"]
    assert october[1:5] == ["10/2025", "Ít tín hiệu", "0", "Chưa có"]
    assert november[1:5] == ["11/2025", "Chưa đủ dữ liệu", "Chưa có", "Chưa có"]
    assert december[1:5] == ["12/2025", "Đủ tín hiệu", "0.20", "1"]


def test_fully_measured_but_sparse_months_are_not_described_as_missing_legacy_fields():
    config, discovery, screening, _ = december_model()
    row = screening["rows"][0]
    row.update(qualifying_months=[], peak_month=None, rank=None, score=None, status="low_signal")
    for metric in row["monthly_metrics"]:
        metric.update(status="low_signal", rank=None, score=None)
    result = ranked(config, discovery, screening, [])
    assert result["selected_keywords"] == 0 and result["verified_months"] == []
    assert "Chưa có tháng đủ tín hiệu" in selected_month_reason(row)
    assert "lượt lưu chưa ghi" not in selected_month_reason(row)
