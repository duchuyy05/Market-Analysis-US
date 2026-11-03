from pathlib import Path
import sys

_source = Path(__file__).resolve().parents[1] / "src"
if str(_source) not in sys.path:
    sys.path.insert(0, str(_source))

from .reddit_scraper import RedditScraper
from .amazon_scraper import AmazonScraper
from .etsy_scraper import EtsyScraper
from .aggregator import ProductAggregator

__all__ = ["RedditScraper", "AmazonScraper", "EtsyScraper", "ProductAggregator"]

