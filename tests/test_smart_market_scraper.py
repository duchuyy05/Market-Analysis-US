"""
Unit test for SmartMarketScraper pipeline with mocked LLM and scraper data.
"""
import unittest
from unittest.mock import MagicMock
from pathlib import Path
from smart_market_scraper import SmartMarketScraper


class TestSmartMarketScraperPipeline(unittest.TestCase):
    def test_pipeline_execution(self):
        scraper = SmartMarketScraper(root_dir=Path(__file__).parent.parent)

        # Mock LLM response
        fake_llm_json = """
        {
          "category": "Quà tặng Giáng sinh",
          "target_audience": "Gia đình và đồng nghiệp",
          "niches": [
            {
              "niche_name": "Đồ trang trí cá nhân hóa",
              "search_keywords": ["personalized wooden ornament"],
              "reason": "Mùa Giáng sinh nhu cầu cao"
            }
          ]
        }
        """
        scraper.call_llm = MagicMock(return_value=fake_llm_json)

        # Mock scraper response
        mock_items = [
            {
                "source": "Amazon",
                "id": "B0TEST01",
                "title": "Custom Wooden Christmas Ornament 2026",
                "price": 14.99,
                "rating": 4.9,
                "review_count": 2100,
                "sales_count": 8000,
                "bought_label": "8K+ bought in past month",
                "badge": "Best Seller",
                "hotness_score": 12500.0,
                "link": "https://www.amazon.com/dp/B0TEST01"
            },
            {
                "source": "Etsy",
                "id": "ETSY999",
                "title": "Handmade Engraved Family Ornament",
                "price": 18.50,
                "rating": 4.9,
                "review_count": 850,
                "sales_count": 25,
                "bought_label": "Có trong 25+ giỏ hàng",
                "badge": "Bestseller",
                "hotness_score": 4200.0,
                "link": "https://www.etsy.com/listing/ETSY999"
            }
        ]
        scraper.aggregator.scrape = MagicMock(return_value=mock_items)

        # Chạy pipeline với brief giả lập
        test_output = "outputs/test_pipeline_output.csv"
        result = scraper.run_pipeline(
            brief="Tôi muốn tìm quà Noel cá nhân hóa",
            sources=["amazon", "etsy"],
            output_file=test_output
        )

        self.assertIn("plan", result)
        self.assertIn("products", result)
        self.assertEqual(len(result["products"]), 2)
        # Kiểm tra sản phẩm đã được gắn metadata niche & seed_keyword
        self.assertEqual(result["products"][0]["niche"], "Đồ trang trí cá nhân hóa")
        self.assertEqual(result["products"][0]["seed_keyword"], "personalized wooden ornament")
        self.assertTrue(Path(test_output).exists())

        # Cleanup
        Path(test_output).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

