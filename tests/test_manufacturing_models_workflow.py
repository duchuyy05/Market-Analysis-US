"""Different manufacturable product models survive the same monthly workflow."""
import hashlib
from datetime import date, datetime, timedelta, timezone

from market_research.pipeline import execute


def test_keychain_shape_calendar_format_and_printable_decor_share_a_broad_research_run(tmp_path):
    models = ["cat shaped acrylic keychain", "spiral desk calendar", "sublimation photo slate"]
    calls, searched = [], []
    def source(provider, params):
        assert provider == "serpapi"
        calls.append(params)
        if params["engine"] == "google_trends":
            start, end = map(date.fromisoformat, params["date"].split())
            assert start.month == end.month == 11
            assert start.year == end.year and start.year in {2023, 2024, 2025}
            points = []
            while start <= end:
                points.append({"timestamp": str(int(datetime.combine(start, datetime.min.time(), timezone.utc).timestamp())),
                    "values": [{"query": query, "extracted_value": 20 if query == "gift basket" else 40 + index}
                               for index, query in enumerate(params["q"].split(","))]})
                start += timedelta(days=1)
            return {"interest_over_time": {"timeline_data": points}}
        assert params["engine"] == "amazon"
        searched.append(params["k"])
        asin = "B0" + hashlib.sha256(params["k"].encode()).hexdigest()[:8].upper()
        return {"organic_results": [{"asin": asin, "title": params["k"], "extracted_price": 15}]}

    config = {"brief": "Tìm mẫu sản phẩm hot cho công ty gia công in ấn hoặc nhập phôi để in: móc khóa, lịch và decor; khám phá kiểu dáng, cấu trúc, vật liệu linh hoạt.",
        "as_of_date": "2026-11-02", "selling_months": [11], "history_years": [2023, 2024, 2025], "target_year": 2026,
        "business": {"profile": "custom_manufacturing", "categories": ["keychains", "printed_paper", "home_decor"]},
        "niches": [{"name": name, "seeds": [keyword]} for name, keyword in zip(["Móc khóa", "Lịch", "Decor/phôi in"], models)],
        "llm": {"enabled": False}, "sources": {"web": False, "shopping": False},
        "trends": {"provider": "serpapi", "history_scope": "seasonal", "history_months": [11], "analysis_year": 2025},
        "limits": {"candidate_keywords": 3, "monthly_keywords": 3, "top_keywords": 3, "product_details": 0,
                   "related_seeds_per_niche": 0, "serpapi_requests": 20, "trends_serpapi_requests": 8,
                   "serpapi_product_reserve": 8, "retry_attempts": 0}}
    run = execute(config, run_id="broad-manufacturing-models", root=tmp_path, transport=source, event=lambda _: None)
    data = run.load_dataset()
    assert run.manifest["status"] in {"complete", "partial"}
    assert set(searched) == set(models)
    assert len(data["ideas"]) == len(data["products"]) == 3
    assert data["selection"]["trends_verified_keywords"] == 3
    assert {row["measurement_query"] for row in data["keyword_screening"]} == set(models)
    assert all(row["measurement_scope"] == "exact_keyword" for row in data["keyword_screening"])
    assert sum(params["engine"] == "google_trends" for params in calls) == 3
    assert len({idea["niche_id"] for idea in data["ideas"]}) == 3
