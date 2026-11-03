from market_research.analysis.product_history import summarize_product_history
from market_research.storage.run import Run


def product(year=2026, price=20, variant="blue", currency="USD"):
    return {"product_id": "P", "asin": "B012345678", "source": "amazon", "title": "Blanket",
            "url": "https://www.amazon.com/dp/B012345678", "observed_at": f"{year}-10-29T00:00:00Z",
            "price": price, "currency": currency, "variant": variant, "review_count": 10}


def test_archive_replay_does_not_create_years_or_duplicate_snapshots(tmp_path):
    for name in ("original", "replay"):
        run = Run(name, tmp_path)
        run.save_dataset({"products": [product()]})
    item = summarize_product_history(run.db, [product()], [2021, 2022, 2023, 2024, 2025], "2026-10-29")["items"][0]
    assert item["captured_years"] == [2026]
    assert item["requested_years_available"] == []
    assert item["requested_years_missing"] == [2021, 2022, 2023, 2024, 2025]
    assert item["status"] == "insufficient_history"
    assert len(item["observations"]) == 1
    assert item["price_cv"] is None


def test_price_comparison_requires_same_verified_variant_and_currency(tmp_path):
    run = Run("history", tmp_path)
    run.save_dataset({"products": [product(2024, 20)]})
    assert summarize_product_history(run.db, [product(2025, 22)], [2024, 2025], "2026-10-29")["items"][0]["status"] == "comparable_price_snapshots"
    for sample in (product(2025, 22, "red"), product(2025, 22, None), product(2025, 22, {}), product(2025, 22, "blue", "EUR")):
        item = summarize_product_history(run.db, [sample], [2024, 2025], "2026-10-29")["items"][0]
        assert item["status"] == "unverified_variants"
        assert item["price_cv"] is None


def test_capture_cutoff_excludes_future_observations(tmp_path):
    run = Run("cutoff", tmp_path)
    run.save_dataset({"products": [product(2026, 99)]})
    item = summarize_product_history(run.db, [product(2025, 20)], [2024, 2025], "2025-12-31")["items"][0]
    assert item["captured_years"] == [2025]
    assert item["annual"][0]["median_price"] == 20
