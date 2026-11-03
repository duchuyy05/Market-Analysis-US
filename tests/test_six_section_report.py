"""Reader report scope, honest gaps, source association and portable PDF assets."""
import hashlib
from types import SimpleNamespace

import pytest

from market_research.reporting.summary import SECTIONS, build
from market_research.reporting.images import allowed, asset, public_host
from market_research.reporting.pdf import export_pdf, runtime


def sample(tmp_path):
    product = {"product_id": "P1", "title": "Đồ treo <script>nguồn</script>", "asin": "B012345678", "url": "https://www.amazon.com/dp/B012345678", "direction_ids": ["D1"],
        "price": 14.5, "currency": "USD", "rating": 4.9, "review_count": 100, "purchase_badge": None, "detail_status": "available", "observed_at": "2026-10-29T00:00:00Z", "thumbnail": "https://m.media-amazon.com/images/test.png"}
    config = {"brief": "Quà gia đình cuối năm", "category": "Christmas gifts", "mode": "offline", "market": "US", "target_year": 2026, "as_of_date": "2026-10-29", "selling_months": [11, 12], "history_years": [2021, 2022, 2025],
        "niches": [{"id": "N1", "name": "Quà gia đình", "customer_hypothesis": "Gia đình"}, {"id": "N0", "name": "Niche chưa có mẫu"}], "limits": {"serpapi_requests": 20, "tavily_requests": 3, "llm_requests": 8}}
    monthly = [{"year": y, "month": m, "value": 10 if y == 2022 else None, "status": "complete" if y == 2022 else "unavailable"} for y in config["history_years"] for m in range(1, 13)]
    history = {"direction_id": "D1", "measurement_query": "ornament", "status": "available", "monthly": monthly, "usable_years": [2022], "stability": "stable", "seasonal_stability": {"status": "variable", "annual_cv": .15, "profile_correlation": .2},
        "validation": {"folds": [], "metrics": {"mae": None}, "baseline_metrics": {"mae": None}, "confidence": {"level": "insufficient", "reasons": ["Thiếu năm đủ dữ liệu"]}},
        "same_period": [{"year": 2021, "mean_index": None, "coverage_pct": 0, "status": "unavailable"}], "comparison_periods": [{"start": "2022-10", "end": "2022-12", "label": "2022-10 → 2022-12", "mean_index": 10, "coverage_pct": 100}], "forecast": []}
    data = {"config": config, "directions": [{"id": "D1", "niche_id": "N1", "keyword": "personalized ornament", "measurement_query": "personalized ornament"}], "histories": [history], "products": [product], "assessments": {"directions": [{"direction_id": "D1", "niche_id": "N1", "status": "watchlist"}]},
        "ideas": [], "reviews": [{"product_id": "P1", "text": "Phản hồi riêng của đồ treo", "rating": None, "evidence_ids": ["E1"]}], "product_history": {"note": "Snapshot chỉ có năm 2026; chưa có lịch sử ASIN 2021–2025."}}
    run = SimpleNamespace(root=tmp_path, output=tmp_path/"outputs/test", manifest={"warnings": [], "usage": []}, evidence={"E1": {"url": "https://www.amazon.com/review/R1"}})
    return run, data


def test_six_sections_keep_year_gaps_exact_review_and_custom_period(tmp_path):
    run, data = sample(tmp_path)
    doc = build(run, data)
    assert [b["text"] for b in doc.blocks if b["type"] == "heading" and b["level"] == 2] == SECTIONS
    md, html = doc.render("Báo cáo", "Offline")
    assert "2021, 2022, 2025" in md and "2022-10 → 2022-12" in md
    assert "chưa phải Top độ hot" in md
    assert "Snapshot chỉ có năm 2026" in md
    assert "&lt;script&gt;nguồn&lt;/script&gt;" in html and "<script>nguồn</script>" not in html
    assert "\n\n" in md and "\\n" not in md
    card = next(b for b in doc.blocks if b["type"] == "product_card")["product"]
    assert "Phản hồi riêng của đồ treo" in card["review"]
    assert "Sao riêng: Chưa có" in card["review"] and "4.90" in card["signals"]
    assert card["review_url"] == "https://www.amazon.com/review/R1"
    validation = next(b for b in doc.blocks if b["type"] == "table" and b["headers"][0] == "Truy vấn kiểm chứng")
    assert validation["rows"][0][0] == "ornament"
    assert "Có biến động" in validation["rows"][0][-1]
    priority = next(b for b in doc.blocks if b["type"] == "table" and b["headers"][0] == "Niche" and b["headers"][1] == "Ưu tiên trong mẫu")
    assert priority["rows"][0][3] == "0/1 hướng ổn định"


def test_main_sample_limit_preserves_full_dataset(tmp_path):
    run, data = sample(tmp_path)
    base = data["products"][0]
    data["products"] = [{**base, "product_id": "P"+str(i), "title": "Mẫu "+str(i)} for i in range(20)]
    cards = [b for b in build(run, data).blocks if b["type"] == "product_card"]
    assert len(cards) == 3
    assert len(data["products"]) == 20


@pytest.mark.parametrize("url", ["http://m.media-amazon.com/a.jpg", "https://127.0.0.1/a.jpg", "https://10.0.0.1/a.jpg", "https://m.media-amazon.com.evil.example/a.jpg", "https://user:pass@m.media-amazon.com/a.jpg", "https://m.media-amazon.com:8443/a.jpg", "file:///secret", None])
def test_image_urls_reject_private_and_arbitrary_sources(url):
    assert allowed(url) is False


def test_image_cache_and_public_dns_guard(tmp_path, monkeypatch):
    run, data = sample(tmp_path)
    assert allowed(data["products"][0]["thumbnail"])
    assert asset(run, data["products"][0]["thumbnail"])["status"] == "unavailable"
    monkeypatch.setattr("market_research.reporting.images.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.168.0.1",443))])
    with pytest.raises(ValueError, match="công khai"):
        public_host(data["products"][0]["thumbnail"])


def test_pdf_six_parts_embeds_cached_image_and_binds_product_review_links(tmp_path):
    try:
        runtime()
        from pypdf import PdfReader
        from PIL import Image
    except ImportError:
        pytest.skip("Optional PDF runtime not installed")
    run, data = sample(tmp_path)
    url = data["products"][0]["thumbnail"]
    cache = run.root/"data/report-images"; cache.mkdir(parents=True)
    picture = cache/(hashlib.sha256(url.encode()).hexdigest()[:24]+".png")
    Image.new("RGB", (60, 40), "#2654bb").save(picture)
    doc = build(run,data)
    path = tmp_path/"reader.pdf"
    result = export_pdf(path,doc,"Báo cáo","Ngoại tuyến")
    assert result["status"] == "available", result
    reader = PdfReader(path)
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert all(s in text for s in SECTIONS)
    assert len(reader.pages) <= 12
    assert sum(len(p.images) for p in reader.pages) == 1
    assert "14.50 USD" in text and "Phản hồi riêng của đồ treo" in text
    urls = [str(a.get_object().get("/A", {}).get("/URI", "")) for p in reader.pages for a in p.get("/Annots", [])]
    assert data["products"][0]["url"] in urls and "https://www.amazon.com/review/R1" in urls
