"""
Aggregator and ranker for multi-platform product discovery without API keys.
Combines results from Reddit, Amazon, and Etsy.
"""
import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .reddit_scraper import RedditScraper
from .amazon_scraper import AmazonScraper
from .etsy_scraper import EtsyScraper


class ProductAggregator:
    def __init__(self, timeout: int = 12):
        self.reddit = RedditScraper(timeout=timeout)
        self.amazon = AmazonScraper(timeout=timeout)
        self.etsy = EtsyScraper(timeout=timeout)
        self.source_status = []

    def scrape(
        self,
        keyword: str,
        sources: Optional[List[str]] = None,
        limit_per_source: int = 15,
        sort_by: str = "hot"  # 'hot', 'sales', 'reviews'
    ) -> List[Dict[str, Any]]:
        """
        Scrape and aggregate products across multiple free sources.
        sources: list containing 'amazon', 'etsy', 'reddit' or None for all.
        """
        if sources is None:
            sources = ["amazon", "etsy", "reddit"]
        sources = [s.lower().strip() for s in sources]

        all_results: List[Dict[str, Any]] = []
        self.source_status = []

        print(f"\n🚀 Đang tìm kiếm sản phẩm cho từ khóa: '{keyword}'...")

        if "amazon" in sources:
            print("  🛒 Đang cào Amazon (lấy sản phẩm, lượt mua 'bought in past month', rating)...")
            amz_items = self.amazon.search(keyword, limit=limit_per_source)
            self.source_status.append(dict(self.amazon.last_status))
            print(f"     ➔ Thu thập được {len(amz_items)} sản phẩm từ Amazon.")
            all_results.extend(amz_items)

        if "etsy" in sources:
            print("  🎨 Đang cào Etsy (lấy handmade/decor/gifts, badge Bestseller, giỏ hàng)...")
            etsy_items = self.etsy.search(keyword, limit=limit_per_source)
            self.source_status.append(dict(self.etsy.last_status))
            print(f"     ➔ Thu thập được {len(etsy_items)} sản phẩm từ Etsy.")
            all_results.extend(etsy_items)

        if "reddit" in sources:
            print("  💬 Đang cào Reddit (đo độ thảo luận, trending, bài viết viral về sản phẩm)...")
            reddit_items = self.reddit.search(keyword, limit=limit_per_source)
            self.source_status.append(dict(self.reddit.last_status))
            print(f"     ➔ Thu thập được {len(reddit_items)} thảo luận từ Reddit.")
            all_results.extend(reddit_items)

        # Xếp hạng tổng thể
        ranked = self._rank_products(all_results, sort_by=sort_by)
        return ranked

    def _rank_products(self, items: List[Dict[str, Any]], sort_by: str) -> List[Dict[str, Any]]:
        # Different source units must never become one cross-platform demand
        # ranking: Amazon bought badges, Etsy carts, Reddit upvotes differ.
        order={"amazon":0,"etsy":1,"reddit":2}
        def key(item):
            source=str(item.get("source","")).casefold()
            value=(item.get("sales_count") or 0) if source=="amazon" and sort_by!="reviews" else (item.get("review_count") or 0) if source!="reddit" else (item.get("score") or 0)
            return (order.get(source,3),-value,-(item.get("review_count") or 0))
        return sorted(items,key=key)

    @staticmethod
    def export_csv(items: List[Dict[str, Any]], filepath: str) -> None:
        if not items:
            print("Không có dữ liệu để xuất CSV.")
            return

        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        keys = [
            "source", "niche", "seed_keyword", "title", "price",
            "sales_count", "bought_label", "rating", "review_count",
            "badge", "hotness_score", "link", "image", "currency", "cart_count", "score", "num_comments", "published_at", "kind"
        ]

        with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(items)
        print(f"💾 Đã lưu file CSV ({len(items)} dòng): {filepath}")

    @staticmethod
    def export_json(items: List[Dict[str, Any]], filepath: str) -> None:
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"💾 Đã lưu file JSON: {filepath}")

    @staticmethod
    def print_summary(items: List[Dict[str, Any]], top_n: int = 30) -> None:
        """In bảng tóm tắt đẹp mắt ra terminal."""
        if not items:
            print("\n❌ Không tìm thấy sản phẩm nào.")
            return

        print("\n" + "=" * 108)
        print(f"{f'{min(len(items), top_n)} MẪU VÀ THẢO LUẬN THU ĐƯỢC — CẦN ĐỐI CHIẾU TÍN HIỆU NGUỒN':^108}")
        print("=" * 108)
        header = f"{'STT':<4} | {'Nguồn':<7} | {'Giá':<9} | {'Lượt bán / Tín hiệu':<22} | {'Rating':<7} | {'Độ Hot':<7} | {'Tên sản phẩm':<40}"
        print(header)
        print("-" * 108)

        for i, item in enumerate(items[:top_n], 1):
            src = item.get("source", "")
            price = f"{item['price']:.2f} {item.get('currency') or '?'}" if item.get("price") is not None else "N/A"

            signal = item.get("bought_label") or item.get("badge") or ""
            if not signal and item.get("sales_count"):
                signal = f"{item['sales_count']}+ đã bán"
            elif not signal and item.get("review_count"):
                signal = f"{item['review_count']} reviews"
            elif not signal and item.get("score"):
                signal = f"{item['score']} upvotes"

            signal = (signal[:20] + "..") if len(signal) > 22 else signal
            hot_score = str(item.get("hotness_score", 0))
            rating_str = f"{item['rating']}★" if item.get("rating") else "N/A"

            title = item.get("title", "")
            title = (title[:37] + "...") if len(title) > 40 else title

            print(f"{i:<4} | {src:<7} | {price:<9} | {signal:<22} | {rating_str:<7} | {hot_score:<7} | {title:<40}")

        print("=" * 108 + "\n")

