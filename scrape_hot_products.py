#!/usr/bin/env python
"""
TOOL CÀO SẢN PHẨM NHIỀU LƯỢT BÁN & HOT NHẤT (KHÔNG CẦN API KEY)
Hỗ trợ lấy dữ liệu từ: Amazon, Etsy, Reddit.

Cách dùng:
  python scrape_hot_products.py --keyword "christmas ornament"
  python scrape_hot_products.py --keyword "desk organizer" --sources amazon,etsy --sort sales
  python scrape_hot_products.py --keyword "tote bag" --sort hot --output data/tote_bags.csv
"""
import argparse
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from scrapers import ProductAggregator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tool cào sản phẩm nhiều lượt bán & hot nhất từ Amazon, Etsy, Reddit mà không cần API key."
    )
    parser.add_argument(
        "-k", "--keyword",
        type=str,
        help="Từ khóa sản phẩm cần tìm (Ví dụ: 'christmas gift', 'desk organizer', 'tote bag')"
    )
    parser.add_argument(
        "-s", "--sources",
        type=str,
        default="amazon,etsy,reddit",
        help="Các nguồn cần cào, phân tách bằng dấu phẩy (Mặc định: amazon,etsy,reddit)"
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=["hot", "sales", "reviews"],
        default="sales",
        help="Cách sắp xếp kết quả: 'sales' (nhiều lượt bán nhất), 'hot' (độ hot/trending), 'reviews' (nhiều đánh giá nhất)"
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=15,
        help="Số lượng sản phẩm lấy từ mỗi nguồn (Mặc định: 15)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="outputs/scraped_hot_products.csv",
        help="Đường dẫn file lưu kết quả (.csv hoặc .json, mặc định: outputs/scraped_hot_products.csv)"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    keyword = args.keyword
    if not keyword:
        # Nếu chạy không tham số, yêu cầu nhập từ terminal
        print("\n=== TOOL CÀO SẢN PHẨM KHÔNG CẦN API KEY ===")
        try:
            keyword = input("Nhập từ khóa sản phẩm bạn muốn tìm: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nĐã hủy.")
            sys.exit(0)

    if not keyword:
        print("Lỗi: Từ khóa không được để trống.")
        sys.exit(1)

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]

    aggregator = ProductAggregator()
    items = aggregator.scrape(
        keyword=keyword,
        sources=sources,
        limit_per_source=args.limit,
        sort_by=args.sort
    )

    # In kết quả
    aggregator.print_summary(items, top_n=20)
    for status in aggregator.source_status:
        print(f"{status['source']}: {status['status']} - {status.get('reason') or str(status.get('count',0))+' dòng dữ liệu'}")

    # Xuất file kết quả
    if args.output:
        if args.output.endswith(".json"):
            aggregator.export_json(items, args.output)
        else:
            aggregator.export_csv(items, args.output)


if __name__ == "__main__":
    main()

