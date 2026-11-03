"""Explicit replay of real saved Q4 observations; never synthesize Shopping."""
from ..common import ROOT, read_json, identity


def candidates(run, direction):
    data = read_json(ROOT / "data/seasonal-gifts-us/dataset.json", {})
    plan = read_json(ROOT / "examples/archive-plan.json", {})
    family = next((f for f in plan.get("families", []) if f["keyword"] == direction["keyword"]), None)
    if not family:
        return [], []
    products, reviews = [], []
    for old in data.get("products", []):
        if family["id"] not in old["family_ids"]:
            continue
        pid, lid = identity("P", "amazon.com", old["asin"]), identity("L", "amazon.com", old["asin"])
        eid = run.add_evidence("product_listing", old["source_url"], old["observed_at_utc"], "archive:" + old["source_raw_file"], (old.get("seller_features") or old["product_name"])[:4000], asin=old["asin"])
        attrs = {k: {"value": old.get(k), "status": "observed" if old.get(k) is not None else "missing", "evidence_ids": [eid] if old.get(k) is not None else []} for k in ("material", "dimensions", "size", "color")}
        products.append({"product_id": pid, "listing_id": lid, "asin": old["asin"], "title": old["product_name"], "source": "amazon", "merchant": "Amazon.com", "url": old["source_url"],
            "thumbnail": None, "price": old["price_usd"], "currency": old.get("currency"), "rating": old["rating_out_of_5"], "review_count": old.get("displayed_rating_or_review_count"),
            "rating_scope": "amazon_listing_may_share_variants", "purchase_badge": old["bought_past_month_text"], "purchase_lower_bound": old["bought_past_month_lower_bound"],
            "purchase_scope": "amazon_product_page", "observed_at": old["observed_at_utc"], "direction_ids": [direction["id"]], "evidence_ids": [eid],
            "sponsored": None, "search_position": None, "description": old.get("seller_features") or old.get("description") or "", "attributes": attrs, "variant": None, "detail_status": "archive_snapshot", "relevant": True})
        for review in [r for r in data.get("reviews", []) if r["asin"] == old["asin"]]:
            reid = run.add_evidence("review", review["source_url"], review["observed_at_utc"], "archive:" + review["source_raw_file"], review["review_text"], asin=old["asin"], published_at=review["review_date"])
            reviews.append({"id": review["review_id"], "product_id": pid, "asin": old["asin"], "text": review["review_text"], "kind": review.get("review_text_kind", "full"),
                "rating": review["rating_out_of_5"], "published_at": review["review_date"], "variant": review.get("variant_text"), "verified_purchase": review.get("verified_purchase"), "evidence_ids": [reid]})
    return products, reviews
