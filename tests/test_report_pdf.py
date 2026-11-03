"""Portable PDF/association checks; no browser, API keys or external requests."""
import sys
from pathlib import Path

import pytest

from market_research.reporting.document import Document, link
from market_research.reporting.pdf import export_pdf, runtime
from market_research.reporting.render import niche_section


def test_review_rows_name_the_exact_product_and_keep_unknown_review_rating():
    product = {"product_id": "P1", "title": "Crystal ornament A", "asin": "B012345678", "url": "https://www.amazon.com/dp/B012345678", "direction_ids": ["D"], "price": 12, "currency": "USD", "rating": 4.9,
               "review_count": 1000, "source": "amazon", "merchant": "Example merchant", "purchase_badge": None, "detail_status": "search_only", "observed_at": "2026-10-29T00:00:00Z", "attributes": {}}
    other = {**product, "product_id": "P2", "title": "Blanket B", "asin": "B012345679", "url": "https://www.amazon.com/dp/B012345679"}
    data = {"config": {"history_years": [2023, 2024, 2025], "target_year": 2026}, "directions": [{"id": "D", "niche_id": "N", "name": "Gift", "keyword": "gift", "keyword_ids": ["K"]}],
        "histories": [], "assessments": {"directions": [{"direction_id": "D", "growth_pct": None, "growth_scope": "unknown", "status": "watchlist"}]}, "keywords": [{"id": "K", "text": "gift"}],
        "products": [product, other], "review_themes": [], "reviews": [{"product_id": "P1", "text": "The exact review belongs to ornament A", "kind": "excerpt", "rating": None, "published_at": None, "evidence_ids": ["E"]}], "ideas": []}
    doc = Document()
    niche_section(doc, {"id": "N", "name": "Gifts"}, data, {"E": {"kind": "review", "url": "https://www.amazon.com/review/R123"}})
    md, _ = doc.render("Report", "test")
    row = next(line for line in md.splitlines() if "The exact review belongs" in line)
    assert "Crystal ornament A" in row and "B012345678" in row
    assert "Blanket B" not in row
    assert "Nguồn không nêu sao" in row and "4.9" not in row
    assert "https://www.amazon.com/review/R123" in row
    assert "1/2" in md


def test_empty_niche_has_one_clear_explanation_instead_of_repeated_empty_tables():
    doc = Document()
    data = {"directions": [], "histories": [], "assessments": {"directions": []}, "products": []}
    niche_section(doc, {"id": "N", "name": "Unmeasured niche"}, data, {})
    assert len(doc.blocks) == 2
    assert doc.blocks[1]["kind"] == "warning"
    assert "chưa có keyword" in doc.blocks[1]["text"]


def test_pdf_has_selectable_vietnamese_and_real_product_review_links(tmp_path):
    try:
        runtime()
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("Optional PDF packages are not installed")
    doc = Document()
    doc.heading("Báo cáo quà tặng cho bố mẹ", 1)
    doc.paragraph("Không thay sao sản phẩm bằng sao comment. Unicode tiếng Việt có dấu.")
    doc.table(["Sản phẩm / ASIN", "Comment", "Nguồn"], [[link("Đồ treo cá nhân hóa · B012345678", "https://www.amazon.com/dp/B012345678"), "Đóng gói tốt", link("Mở comment", "https://www.amazon.com/review/R1")]])
    target = tmp_path / "report.pdf"
    result = export_pdf(target, doc, "Báo cáo", "Kiểm thử offline")
    if result["status"] == "unavailable":
        pytest.skip(result["reason"])
    assert result["status"] == "available", result
    reader = PdfReader(target)
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Báo cáo quà tặng cho bố mẹ" in extracted
    links = [str(annotation.get_object().get("/A", {}).get("/URI", "")) for page in reader.pages for annotation in page.get("/Annots", []) if annotation.get_object().get("/Subtype") == "/Link"]
    assert "https://www.amazon.com/dp/B012345678" in links
    assert "https://www.amazon.com/review/R1" in links
    assert not target.with_suffix(".pdf.tmp").exists()
