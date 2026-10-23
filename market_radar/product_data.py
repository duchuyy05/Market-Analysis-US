"""Listing snapshots, review evidence and ranking shared by all product topics."""
from collections import defaultdict
import re

from .normalize import number, purchase_lower_bound
from .web_sources import visible_web_text


def clean_text(value):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"^\*\*\s*\d(?:\.\d)?\s+out of\s+5\s+stars.*?\*\*", "", value, flags=re.I)
    return visible_web_text(value)


def current_product(p, envelope, candidate):
    raw = envelope["response"].get("product_results", {})
    specs = p["specifications"]
    stock = raw.get("stock")
    # Snapshot measures come exclusively from this product response, not an
    # older search-card fallback with a different observation time.
    price = number(raw.get("extracted_price"))
    bought = raw.get("bought_last_month")
    brand = re.sub(r"^Visit the (.*?) Store$",r"\1",clean_text(p.get("brand")),flags=re.I)
    if re.search(r"currently unavailable|out of stock", stock or "", re.I):
        availability = "unavailable"
    elif re.search(r"in stock|only\s+\d+\s+left", stock or "", re.I):
        availability = "available"
    else:
        availability = "not_confirmed"
    return {"product_id": p["product_evidence_id"], "asin": p["asin"], "product_name": clean_text(p["product_name"]),
        "brand": brand, "product_group": None,
        "price_usd": price, "price_text": raw.get("price"), "price_max_usd": number(raw.get("extracted_max_price")), "currency": "USD" if price is not None else None,
        "price_unit_text": raw.get("price_unit"), "availability_status": availability, "availability_text": stock,
        "rating_out_of_5": number(raw.get("rating")), "displayed_rating_or_review_count": number(raw.get("reviews")),
        "rating_count_explicit": p["rating_count_explicit"], "written_review_count_explicit": p["written_review_count_explicit"],
        "customer_reviews_collected": 0, "bought_past_month_text": bought,
        "bought_past_month_lower_bound": purchase_lower_bound(bought), "sales_signal_rank_in_sample": None,
        "main_category_bsr": p["bsr_main_rank"], "main_bsr_category": p["bsr_main_category"],
        "bsr_rank_within_category_sample": None, "color": p["color"], "size": p["size"], "dimensions": p["dimensions"],
        "material": p["material"], "scent": p["scent"], "listing_unit_count": specs.get("unit_count"),
        "listing_number_of_items": specs.get("number_of_items"), "included_components_explicit": clean_text(p.get("included_components")) or None,
        "seller_features": clean_text(p.get("seller_features")), "description": clean_text(p.get("description")),
        "christmas_mentioned_by_seller": p["christmas_in_listing"], "date_first_available": p["date_first_available"],
        "discovered_by_tavily": bool(candidate.get("tavily_source_ids")),
        "discovery_channels": "reused_same_day_amazon_snapshot" if candidate.get("inherited_from") else "tavily_web;amazon_component_search" if candidate.get("tavily_source_ids") and candidate.get("search_queries") else "tavily_web" if candidate.get("tavily_source_ids") else "amazon_component_search",
        "source_url": p["source_url"], "source_raw_file": p["source_raw_file"], "observed_at_utc": p["collected_at_utc"],
        "source_processed_at": p["source_processed_at"], "market": "US", "source_language_requested": "en_US",
        "sales_measure": "Amazon past-month purchase badge: rounded lower-bound band, not exact units or revenue",
        "quality_measure": "Customer star rating and sampled review evidence; no physical quality test"}


def rank_current_products(products):
    bands = sorted({p["bought_past_month_lower_bound"] for p in products if p["bought_past_month_lower_bound"] is not None}, reverse=True)
    ranks = defaultdict(set)
    for p in products:
        if p["main_category_bsr"] is not None:
            ranks[p["main_bsr_category"]].add(p["main_category_bsr"])
    for p in products:
        band = p["bought_past_month_lower_bound"]
        p["sales_signal_rank_in_sample"] = bands.index(band) + 1 if band is not None else None
        order = sorted(ranks[p["main_bsr_category"]])
        p["bsr_rank_within_category_sample"] = order.index(p["main_category_bsr"]) + 1 if p["main_category_bsr"] in order else None
    return sorted(products, key=lambda p: (p["sales_signal_rank_in_sample"] is None, p["sales_signal_rank_in_sample"] or 99999, p["asin"]))


def review_needs(reviews):
    patterns = {
        "scent": r"\b(scent|smell|fragrance|aroma)\w*\b",
        "packaging": r"\b(packaging|packaged|box|wrapped|presentation)\b",
        "size_or_quantity": r"\b(small|smaller|large|larger|size|tiny|quantity|pieces)\b",
        "material_or_quality": r"\b(quality|soft|cheap|durable|broken|broke|leak|leaked)\b",
        "value_for_money": r"\b(price|value|worth|money|expensive|affordable)\b",
        "gift_recipient_or_occasion": r"\b(mom|mother|wife|sister|friend|daughter|christmas|birthday|gift)\b",
        "skin_or_sensitivity": r"\b(skin|irritat\w*|allerg\w*|sensitive|rash)\b",
        "delivery": r"\b(shipping|delivery|arrived|damaged|late)\b",
    }
    rows = []
    for review in reviews:
        body = review["review_text"]
        for theme, pattern in patterns.items():
            match = re.search(pattern, body, re.I)
            if match:
                rows.append({"review_id": review["review_id"], "asin": review["asin"], "theme": theme,
                    "evidence_excerpt": body[max(0,match.start()-90):min(len(body),match.end()+160)],
                    "review_rating": review["rating_out_of_5"], "review_date": review["review_date"],
                    "is_q4_2023_2026": review["is_q4_2023_2026"], "verified_purchase": review["verified_purchase"],
                    "source_url": review["source_url"], "classification_method": "Keyword match in customer text; not automated sentiment or population demand"})
    return rows
