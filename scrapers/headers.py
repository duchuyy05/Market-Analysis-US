"""Stable public research headers; no rotation or challenge bypass."""
from market_research.scraping.engine import headers as get_browser_headers

def get_random_user_agent():
    return get_browser_headers()["User-Agent"]
