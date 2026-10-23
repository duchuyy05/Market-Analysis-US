"""Offline checks using synthetic records, never market evidence or real credentials."""
import unittest
from market_radar.normalize import purchase_lower_bound, description_text
from market_radar.product_data import rank_current_products
from market_radar.io import scrub


def sample(asin, band=None, rank=None, category=None, price=None):
    return {"asin": asin, "bought_past_month_lower_bound": band,
            "main_category_bsr": rank, "main_bsr_category": category, "price_usd": price}


class MarketDataTests(unittest.TestCase):
    def test_purchase_badge_preserves_missing_and_k_m_thresholds(self):
        self.assertEqual(purchase_lower_bound("20K+ bought in past month"), 20000)
        self.assertEqual(purchase_lower_bound("1.5K+ bought in past month"), 1500)
        self.assertIsNone(purchase_lower_bound("2,000 customer ratings"))
        self.assertIsNone(purchase_lower_bound(None))

    def test_purchase_band_ties_share_rank_and_missing_is_not_zero(self):
        rows = rank_current_products([sample("A", 3000), sample("B", 3000), sample("C", 1000), sample("D")])
        self.assertEqual([r["sales_signal_rank_in_sample"] for r in rows], [1, 1, 2, None])

    def test_bsr_never_compares_unrelated_categories(self):
        rows = rank_current_products([sample("A", rank=20, category="Beauty"), sample("B", rank=5, category="Home"), sample("C", rank=10, category="Beauty")])
        by_id = {r["asin"]: r for r in rows}
        self.assertEqual(by_id["A"]["bsr_rank_within_category_sample"], 2)
        self.assertEqual(by_id["B"]["bsr_rank_within_category_sample"], 1)
        self.assertEqual(by_id["C"]["bsr_rank_within_category_sample"], 1)

    def test_description_ignores_similar_product_comparison(self):
        value = [{"title": "Spa gift set", "compare_with_similar": [{"title": "Christmas competitor"}], "image": "https://example.test"}]
        self.assertEqual(description_text(value), "Spa gift set")

    def test_secrets_are_removed_from_nested_error_and_urls(self):
        clean = scrub({"api_key": "secret", "nested": ["https://example.test/?api_key=secret", "echo secret"]}, ["secret"])
        self.assertNotIn("secret", str(clean))


if __name__ == "__main__":
    unittest.main()
