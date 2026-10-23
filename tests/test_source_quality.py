"""Current-pipeline regressions for web text and Amazon snapshot provenance."""
import unittest
from market_radar.web_sources import visible_web_text, canonical_url
from market_radar.product_data import current_product
from market_radar.normalize import normalize_product


class SourceQualityTests(unittest.TestCase):
    def test_keyword_in_an_image_url_does_not_count_as_visible_web_evidence(self):
        self.assertEqual(visible_web_text("Gift guide ![photo](https://example.test/candles.jpg)"),"Gift guide")

    def test_web_cleaning_keeps_visible_link_labels_and_deduplicates_tracking_urls(self):
        self.assertEqual(visible_web_text('<p>Winter <a href="https://example.test/hidden">gift set</a></p>'),"Winter gift set")
        self.assertEqual(canonical_url("https://EXAMPLE.test/gifts/?utm_source=test#section"),"https://example.test/gifts")

    def test_current_snapshot_does_not_fill_missing_price_or_sales_from_search_card(self):
        envelope = {"parameters":{"asin":"TEST000001"},"response":{"product_results":{"title":"Spa gift set","stock":"In Stock"}},
                    "raw_file":"raw/test.json","fetched_at_utc":"2026-10-22T00:00:00Z"}
        candidate = {"item":{"asin":"TEST000001","extracted_price":100,"bought_last_month":"20K+ bought in past month"},"search_sources":[]}
        normalized,_ = normalize_product(envelope,candidate,"P-TEST000001")
        current = current_product(normalized,envelope,candidate)
        self.assertIsNone(current["price_usd"])
        self.assertIsNone(current["bought_past_month_lower_bound"])


if __name__=="__main__":
    unittest.main()
