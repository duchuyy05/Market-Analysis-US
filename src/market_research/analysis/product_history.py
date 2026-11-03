"""Evidence for the same listing comes from captured snapshots, not Trends."""
import json
from statistics import median, mean, pstdev

from ..storage.database import product_identity


def summarize_product_history(database, products, requested_years, cutoff):
    items = []
    for product in products:
        identity = product_identity(product)
        saved = database.product_history(identity, limit=500)
        observations, seen = [], set()
        for row in [*saved, product]:
            stamp = str(row.get("observed_at") or "")
            if len(stamp) < 10 or stamp[:10] > cutoff:
                continue
            variant = row.get("variant")
            key = (stamp, row.get("price"), row.get("currency"), json.dumps(variant, sort_keys=True, ensure_ascii=False), row.get("rating"), row.get("review_count"), row.get("purchase_lower_bound"), row.get("purchase_scope"))
            if key in seen:
                continue
            seen.add(key)
            observations.append({"observed_at": stamp, "price": row.get("price"), "currency": row.get("currency"),
                "variant": variant, "rating": row.get("rating"), "review_count": row.get("review_count"),
                "purchase_lower_bound": row.get("purchase_lower_bound"), "purchase_scope": row.get("purchase_scope"),
                "url": row.get("url"), "evidence_ids": row.get("evidence_ids", []), "run_id": row.get("run_id")})
        observations.sort(key=lambda row: row["observed_at"])
        captured_years = sorted({int(row["observed_at"][:4]) for row in observations})
        annual = []
        for year in captured_years:
            rows = [row for row in observations if int(row["observed_at"][:4]) == year]
            # Price rollups are descriptive only; unknown/mixed variants may not
            # be compared as the price history of one SKU.
            currencies = {row["currency"] for row in rows if row["price"] is not None}
            variants = {json.dumps(row["variant"], sort_keys=True) for row in rows if row["variant"] is not None}
            comparable = len(currencies) == 1 and None not in currencies and len(variants) == 1 and all(row["variant"] not in (None, "", {}, []) for row in rows)
            prices = [row["price"] for row in rows if isinstance(row["price"], (int, float)) and not isinstance(row["price"], bool)]
            annual.append({"year": year, "observations": len(rows), "currency": next(iter(currencies)) if len(currencies) == 1 else None,
                "variant_comparable": comparable, "median_price": median(prices) if comparable and prices else None,
                "min_price": min(prices) if comparable and prices else None, "max_price": max(prices) if comparable and prices else None})
        available = sorted(set(captured_years) & set(requested_years))
        selected = [row for row in annual if row["year"] in requested_years]
        usable = len(available) >= 2 and all(row["variant_comparable"] and row["median_price"] is not None for row in selected)
        selected_observations = [row for row in observations if int(row["observed_at"][:4]) in requested_years]
        variants_all = {json.dumps(row["variant"], sort_keys=True) for row in selected_observations}
        currencies_all = {row["currency"] for row in selected_observations}
        comparable_years = usable and len(variants_all) == len(currencies_all) == 1 and None not in currencies_all
        prices = [row["median_price"] for row in selected] if comparable_years else []
        cv = pstdev(prices)/mean(prices) if len(prices) >= 2 and mean(prices) > 0 else None
        items.append({"product_id": product["product_id"], "identity_key": identity, "asin": product.get("asin"),
            "title": product["title"], "url": product.get("url"), "captured_years": captured_years,
            "requested_years_available": available, "requested_years_missing": sorted(set(requested_years)-set(available)),
            "status": "comparable_price_snapshots" if comparable_years else "insufficient_history" if len(available) < 2 else "unverified_variants",
            "observations": observations, "annual": annual, "price_cv": round(cv, 4) if cv is not None else None,
            "notes": ["Chỉ gồm quan sát đã thu thập, không khôi phục giá/đơn hàng quá khứ từ keyword.",
                      "Nhãn mua là mức làm tròn của cửa sổ nguồn; không cộng các snapshot thành doanh số năm.",
                      "Giá chỉ so khi cùng tiền tệ và biến thể được xác minh; ổn định giá không đồng nghĩa ổn định nhu cầu."]})
    return {"requested_years": list(requested_years), "items": items,
            "note": "Lịch sử sản phẩm lấy từ snapshot thực tế trong SQLite. Google Trends kiểm tra loại hàng/truy vấn; không chứng minh doanh số của cùng ASIN trong các năm chưa có bản ghi."}
