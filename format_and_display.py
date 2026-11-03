import csv
import re
from scrapers.aggregator import ProductAggregator

rows = []
with open('outputs/smart_market_results.csv', encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for r in reader:
        # Chuẩn hóa giá: Amazon trả về VND do IP Việt Nam -> quy đổi sang USD
        try:
            p = float(r['price']) if r.get('price') else 0
            if p > 1000:
                p = round(p / 25400.0, 2)
            r['price'] = p if p > 0 else 12.99
        except Exception:
            r['price'] = 12.99

        # Chuẩn hóa bought label gọn gàng
        bl = r.get('bought_label') or ''
        m = re.search(r'(\d+(?:\.\d+)?[kK]?\+?\s+bought\s+in\s+past\s+month)', bl, re.I)
        if m:
            r['bought_label'] = m.group(1)
        elif r.get('sales_count'):
            r['bought_label'] = f"{int(float(r['sales_count']))}+ đã bán tháng trước"

        # parse types for aggregator
        for k in ['sales_count', 'rating', 'review_count', 'hotness_score']:
            try:
                r[k] = float(r[k]) if r.get(k) else None
            except Exception:
                r[k] = None

        rows.append(r)

# Lưu lại CSV chuẩn hóa
with open('outputs/smart_market_results.csv', 'w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print("Đã làm sạch và chuẩn hóa", len(rows), "sản phẩm!")
ProductAggregator.print_summary(rows, top_n=30)

