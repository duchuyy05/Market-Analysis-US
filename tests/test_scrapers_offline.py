"""
Unit tests for scrapers offline logic (parsing, score calculation, sorting, export).
"""
import unittest
from scrapers.reddit_scraper import RedditScraper
from scrapers.amazon_scraper import AmazonScraper
from scrapers.etsy_scraper import EtsyScraper
from scrapers.aggregator import ProductAggregator


class TestScrapersOffline(unittest.TestCase):
    def test_reddit_parsing(self):
        scraper = RedditScraper()
        mock_data = {
            "data": {
                "children": [
                    {
                        "data": {
                            "id": "post123",
                            "title": "Best ergonomic mechanical keyboard in 2026?",
                            "score": 450,
                            "num_comments": 85,
                            "upvote_ratio": 0.94,
                            "subreddit": "MechanicalKeyboards",
                            "permalink": "/r/MechanicalKeyboards/comments/post123",
                            "url": "https://reddit.com/r/MechanicalKeyboards/comments/post123",
                            "selftext": "Looking for a silent wireless board..."
                        }
                    }
                ]
            }
        }
        items = scraper._parse_reddit_json(mock_data, "keyboard")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["score"], 450)
        self.assertEqual(items[0]["subreddit"], "r/MechanicalKeyboards")
        self.assertGreater(items[0]["hotness_score"], 500)

    def test_amazon_sales_parsing(self):
        scraper = AmazonScraper()
        self.assertEqual(scraper._parse_sales_volume("10K+ bought in past month"), 10000)
        self.assertEqual(scraper._parse_sales_volume("500+ bought in past month"), 500)
        self.assertEqual(scraper._parse_sales_volume("2.5K+ bought"), 2500)
        self.assertIsNone(scraper._parse_sales_volume("no sales info"))

    def test_amazon_html_parsing(self):
        scraper = AmazonScraper()
        sample_html = """
        <div data-component-type="s-search-result" data-asin="B0SAMPLE12">
            <h2><a href="#"><span>Ergonomic Desk Organizer</span></a></h2>
            <span class="a-price"><span class="a-offscreen">$29.99</span></span>
            <span class="a-icon-alt">4.7 out of 5 stars</span>
            <a href="/customerReviews/B0SAMPLE12"><span>3,420</span></a>
            <span class="a-size-small a-color-secondary">5K+ bought in past month</span>
            <span class="a-badge-text">Best Seller</span>
            <img class="s-image" src="https://m.media-amazon.com/sample.jpg" />
        </div>
        """
        items = scraper._parse_amazon_html(sample_html, limit=10)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["id"], "B0SAMPLE12")
        self.assertEqual(item["price"], 29.99)
        self.assertEqual(item["rating"], 4.7)
        self.assertEqual(item["review_count"], 3420)
        self.assertEqual(item["sales_count"], 5000)
        self.assertEqual(item["badge"], "Best Seller")
        self.assertEqual(item["hotness_score"], 5000)  # Observed lower bound, no invented hotness boost.

    def test_etsy_cart_parsing(self):
        scraper = EtsyScraper()
        self.assertEqual(scraper._parse_in_cart_count("In 20+ carts"), 20)
        self.assertEqual(scraper._parse_in_cart_count("Over 15 people have this in their cart"), 15)

    def test_aggregator_ranking(self):
        aggregator = ProductAggregator()
        mock_items = [
            {"source": "Amazon", "title": "Item A", "sales_count": 2000, "review_count": 100, "hotness_score": 3000},
            {"source": "Amazon", "title": "Item B", "sales_count": 10000, "review_count": 5000, "hotness_score": 15000},
            {"source": "Etsy", "title": "Item C", "sales_count": 50, "review_count": 800, "hotness_score": 1200},
        ]
        ranked_sales = aggregator._rank_products(mock_items, sort_by="sales")
        self.assertEqual(ranked_sales[0]["title"], "Item B")
        self.assertEqual(ranked_sales[1]["title"], "Item A")
        self.assertEqual(ranked_sales[2]["title"], "Item C")


if __name__ == "__main__":
    unittest.main()

