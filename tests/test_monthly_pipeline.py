"""Candidate histories feed month-specific selection and are not fetched twice."""
import hashlib

from market_research.config import validate_config
from market_research.pipeline import execute
from test_v4_workflow_recovery import paid_series


def test_candidate_monthly_history_reused_by_selected_products(tmp_path):
    calls = []
    def transport(provider, params):
        calls.append((provider, params))
        assert provider == "serpapi"
        if params["engine"] == "google_trends":
            return paid_series(params)
        assert params["engine"] == "amazon"
        return {"organic_results": [{"asin": "B0" + hashlib.sha256(params["k"].encode()).hexdigest()[:8].upper(),
            "title": params["k"], "extracted_price": 15, "sponsored": False}]}
    config = validate_config({"brief": "Christmas gifts in the US", "selling_months": [11, 12],
        "business": {"profile": "general", "categories": []},
        "as_of_date": "2026-10-30", "niches": [{"name": "Practical", "seeds": ["candle warmer", "photo frame", "coffee mug", "hand cream"]}],
        "sources": {"web": False}, "llm": {"enabled": False}, "trends": {"provider": "serpapi", "monthly_rankings": True},
        "limits": {"candidate_keywords": 4, "monthly_keywords": 4, "top_keywords": 2, "product_details": 0,
                   "related_seeds_per_niche": 0, "serpapi_requests": 30, "trends_serpapi_requests": 10, "serpapi_product_reserve": 5, "retry_attempts": 0}})
    run = execute(config, root=tmp_path, run_id="monthly-pipeline", transport=transport, event=lambda _: None)
    data = run.load_dataset()
    assert data["selection"]["selection_basis"] == "historical_selling_months"
    assert len(data["keyword_histories"]) == 4 and len(data["histories"]) == 2
    assert len(data["keyword_monthly"]["rows"]) == 48
    history_calls = [u for u in run.manifest["usage"] if u.get("purpose") == "trends_history"]
    assert len(history_calls) == 1  # includes the anchor; final history uses checkpoints
    assert run.manifest["stages"]["monthly"]["status"] == "complete"
    assert all(h["normalization_context"]["anchor"] == "gift basket" for h in data["histories"])
    assert (run.output / "keyword-monthly.html").is_file()
    assert (run.output / "tables/keyword_monthly.csv").is_file()
