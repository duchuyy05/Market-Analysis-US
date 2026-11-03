"""Model identity and selected-month source context survive the reader exports."""
import pytest

from market_research.analysis.products import relevant
from market_research.reporting.document import Document
from market_research.reporting.keywords import build, screening_details
from market_research.workflow.ideas import generate


@pytest.mark.parametrize("title,query,expected", [
    ("Plain cotton t-shirt", "Taylor Swift t shirt", False),
    ("Taylor fan shirt", "Taylor Swift t shirt", False),
    ("Taylor Swift poster", "Taylor Swift t shirt", False),
    ("Taylor Swift cotton graphic tee", "Taylor Swift t shirt", True),
    ("Sabrina Carpenter concert T-Shirt", "Sabrina Carpenter shirt", True),
    ("Floral wrapping paper gift rolls", "black cat gift wrap", False),
    ("Black Cat wrapping paper", "black cat gift wrap", True),
    ("Desk organizer with drawer", "desk organizer", True),
    ("Spiral Tabletop Calendar", "spiral desk calendar", True),
    ("Wire-bound Tabletop Calendar", "spiral desk calendar", True),
    ("Spiral Wall Calendar", "spiral desk calendar", False),
    ("Tear-away Tabletop Calendar", "tear off desk calendar", True),
    ("Tear-off desk calendar", "spiral desk calendar", False),
    ("Heart acrylic keyring", "heart shaped acrylic keychain", True),
    ("Round acrylic keychain", "heart shaped acrylic keychain", False),
    ("Acrylic shaker key ring", "acrylic shaker keychain", True),
    ("Flat acrylic key ring", "3d acrylic keychain", False),
    ("Three-dimensional acrylic keychain", "3d acrylic keychain", True),
    ("Sublimation acrylic keyring blanks", "sublimation printable acrylic keychain blank", True),
    ("Printable acrylic keyring blanks", "sublimation acrylic keychain blank", False),
    ("Sublimation wooden sign blanks", "sublimation wood sign blank", True),
    ("Acrylic sign blank", "sublimation wood sign blank", False),
    ("Boxy Crew Neck Cotton Tee", "boxy crewneck cotton t shirt", True),
    ("Boxy Crew Neck Polyester Tee", "boxy crewneck cotton shirt", False),
    ("Foil-stamped wrapping paper", "foil gift wrap", True),
    ("Matte floral wrapping paper", "glossy floral gift wrap", False),
    ("2025 Spiral Desk Calendar", "2026 spiral desk calendar", False),
])
def test_listing_requires_the_specific_design_and_physical_product(title, query, expected):
    assert relevant(title, query) is expected


def selected_design():
    return {"config": {"selling_months": [3], "trends": {"history_scope": "seasonal", "history_months": [3], "analysis_year": 2025},
                       "niches": [{"id": "N", "name": "Printed apparel"}]},
        "keywords": [{"id": "K", "niche_id": "N", "text": "Sabrina Carpenter shirt", "origin": "public_web"}],
        "screening": {"status": "available", "method": "selected_months_observed_interest_v1", "analysis_year": 2025},
        "selection": {"selection_basis": "selected_month_observations", "note": "Quan sát tháng đã chọn."},
        "keyword_screening": [{"keyword_id": "K", "keyword": "Sabrina Carpenter shirt", "measurement_query": "Sabrina Carpenter shirt", "measurement_scope": "exact_keyword", "relative_interest": 1.25, "score": 100, "rank": 1, "status": "available"}],
        "keyword_selection": [{"keyword_id": "K", "keyword": "Sabrina Carpenter shirt", "measurement_query": "Sabrina Carpenter shirt", "measurement_scope": "exact_keyword", "relative_interest": 1.25, "score": 100, "rank": 1, "status": "available", "selected": True, "selection_basis": "selected_month_observations"}]}


def test_selected_month_design_report_uses_observed_ratio_and_exact_month():
    data = selected_design()
    doc = Document()
    screening_details(doc, data)
    md, _ = doc.render("Design", "Fixture")
    assert "Sabrina Carpenter shirt" in md and "Tháng phân tích: 3 năm 2025" in md
    assert "1.25" in md and "28 ngày" not in md
    assert "Tháng mạnh nhất / quan tâm anchor" in md
    md, _ = build(data).render("Keywords", "Fixture")
    assert "Điểm tháng mạnh nhất" in md and "Điểm gần đây" not in md


@pytest.mark.parametrize("keyword", ["acrylic shaker keychain", "spiral desk calendar", "boxy cotton shirt", "sublimation wood sign blank", "foil floral gift wrap"])
def test_report_describes_general_manufacturable_models_without_an_artist_requirement(keyword):
    data = selected_design()
    data["keywords"][0]["text"] = keyword
    for field in ("keyword_screening", "keyword_selection"):
        data[field][0].update(keyword=keyword, measurement_query=keyword)
    doc = Document()
    screening_details(doc, data)
    md, _ = doc.render("Models", "Fixture")
    assert keyword in md
    assert "kiểu dáng, cấu trúc, vật liệu, hoàn thiện" in md
    assert "Mẫu hàng / keyword" in md and "nghệ sĩ" not in md


def test_idea_preserves_design_and_month_observation_apart_from_historical_series():
    direction = {"id": "D", "niche_id": "N", "name": "Áo in", "keyword": "Sabrina Carpenter shirt", "measurement_query": "Sabrina Carpenter shirt",
        "measurement_scope": "exact_keyword", "analysis_year": 2025, "selection_basis": "selected_month_observations",
        "analysis_windows": [{"start": "2025-03-01", "end": "2025-03-31"}], "evidence_ids": ["E-screen"]}
    product = {"product_id": "P", "title": "Sabrina Carpenter shirt", "direction_ids": ["D"], "price": 15, "currency": "USD", "url": "https://www.amazon.com/dp/B012345678",
        "purchase_lower_bound": 100, "purchase_badge": "100+ bought in past month", "detail_status": "available", "description": "", "attributes": {}, "evidence_ids": ["E-listing"]}
    assessment = {"directions": [{"direction_id": "D", "status": "watchlist"}], "product_checks": [{"product_id": "P", "status": "eligible", "pending": []}]}
    history = {"direction_id": "D", "measurement_query": "shirt", "measurement_scope": "broader_product_type", "monthly": [], "evidence_ids": ["E-history"]}
    result = generate({"selling_months": [3], "history_years": [2023, 2024]}, [direction], {"products": [product], "reviews": []}, assessment, [history])[0]
    assert result["candidate_keyword"] == result["measurement_query"] == "Sabrina Carpenter shirt"
    assert result["analysis_months"] == [3] and result["analysis_year"] == 2025
    assert "Sabrina Carpenter shirt" in result["sell_what"]
    assert result["market_evidence"]["historical_measurement_query"] == "shirt"
    assert result["market_evidence"]["measurement_scope"] == "exact_keyword"
    assert result["market_evidence"]["evidence_ids"] == ["E-history", "E-listing", "E-screen"]
    assert "E-screen" in result["evidence_ids"]
    assert "không phải doanh số của tháng lịch sử" in result["market_evidence"]["limitation"]
