"""Parse Amazon source fields and write CSV; missing source values stay missing."""
from datetime import datetime
import csv
import hashlib
import json
import re
from urllib.parse import urlsplit


def text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return "\n".join(f"{key}: {text(item)}" for key, item in value.items() if item is not None)
    if isinstance(value, list):
        return "\n".join(text(item) for item in value)
    return str(value)


def number(value):
    if isinstance(value, (float, int)) and not isinstance(value, bool):
        return value
    return None


def first(*values):
    return next((value for value in values if value is not None and value != ""), None)


def description_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (description_text(item) for item in value)))
    if isinstance(value, dict):
        return "\n".join(filter(None, (description_text(value.get(key)) for key in
            ("title", "text", "description", "paragraphs", "texts", "features", "highlights"))))
    return ""


def purchase_lower_bound(label):
    if not isinstance(label, str) or not re.search(r"bought.*(?:past|last) month", label, re.I):
        return None
    match = re.search(r"([\d,.]+)\s*([KM]?)\+?\s+bought", label, re.I)
    if not match:
        return None
    return int(float(match[1].replace(",", "")) * {"": 1, "K": 1000, "M": 1000000}[match[2].upper()])


def iso_date(label):
    if not isinstance(label, str):
        return None
    value = re.sub(r"^.*?\bon\s+", "", label).strip()
    for fmt in ("%B %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def bsrs(details):
    results = []
    for item in details.get("best_sellers_rank", []) or []:
        if not isinstance(item, dict):
            continue
        category = re.sub(r"^#[\d,]+\s+in\s+", "", item.get("text", "")).split(" (See ")[0].strip()
        rank = number(item.get("extracted_rank"))
        if rank is not None and category:
            results.append({"rank": int(rank), "category": category, "url": item.get("link")})
    return results


def source_review_items(data):
    """Keep full reviews and linked excerpts separate; never use the AI summary as a review."""
    info = data.get("reviews_information") or {}
    rows = [{**item,"_kind":"full","_section":"authors_reviews"} for item in info.get("authors_reviews",[]) or [] if isinstance(item,dict)]
    for item in info.get("other_countries_reviews",[]) or []:
        if isinstance(item,dict) and (item.get("language") or {}).get("code") == "en":
            rows.append({**item,"_kind":"full","_section":"other_countries_reviews"})
    full_text = [" ".join((r.get("text") or r.get("body") or "").lower().split()) for r in rows]
    seen = set()
    for insight in (info.get("summary") or {}).get("insights",[]) or []:
        if not isinstance(insight,dict):
            continue
        for item in insight.get("examples",[]) or []:
            if not isinstance(item,dict):
                continue
            body, link = item.get("snippet"), item.get("link")
            if not isinstance(body,str) or not body.strip() or not isinstance(link,str):
                continue
            parsed = urlsplit(link)
            if parsed.scheme!="https" or parsed.hostname not in {"amazon.com","www.amazon.com"}:
                continue
            match = re.search(r"/customer-reviews/(?:srp/-/)?(R[A-Z0-9]+)(?:[/?#]|$)",parsed.path)
            if not match or match[1] in seen:
                continue
            compact=" ".join(body.lower().split()).strip('. …')
            if len(compact)>25 and any(compact in text for text in full_text):
                continue
            seen.add(match[1])
            rows.append({"text":body,"link":link,"_kind":"excerpt","_section":"summary.insights.examples"})
    return rows


def deduplicate_review_rows(rows):
    """Prefer full text and suppress excerpts already contained in a full text of the same ASIN."""
    unique={}
    for row in rows:
        previous=unique.get(row["review_id"])
        if previous and previous.get("review_text_kind","full")=="full" and row.get("review_text_kind")=="excerpt":
            continue
        if previous and previous.get("review_text_kind")==row.get("review_text_kind")=="excerpt" and len(previous["review_text"])>len(row["review_text"]):
            continue
        unique[row["review_id"]]=row
    full={}
    for row in unique.values():
        if row.get("review_text_kind","full")=="full":
            full.setdefault(row["asin"],[]).append(" ".join(row["review_text"].lower().split()))
    result=[]
    for row in unique.values():
        compact=" ".join(row["review_text"].lower().split()).strip('. …')
        if row.get("review_text_kind")=="excerpt" and len(compact)>25 and any(compact in body for body in full.get(row["asin"],[])):
            continue
        result.append(row)
    return result


def normalize_product(envelope, discovery, product_id):
    data, search = envelope["response"], discovery["item"]
    pr, details = data.get("product_results") or {}, data.get("product_details") or {}
    specs = data.get("item_specifications") or {}
    asin = envelope["parameters"]["asin"]
    about = text(data.get("about_item"))
    description = description_text(first(pr.get("description"), data.get("product_description")))
    listing_text = "\n".join([pr.get("title", ""), about, description, text(specs), text(details)])
    title = first(pr.get("title"), search.get("title"))
    if not title:
        return None, []
    url = f"https://www.amazon.com/dp/{asin}"
    reviews_info = data.get("reviews_information") or {}
    summary = reviews_info.get("summary") or {}
    counts = summary.get("customer_reviews") or {}
    reviews = []
    seen = set()
    for item in source_review_items(data):
        body = item.get("text") or item.get("body") or ""
        if not body.strip():
            continue
        fingerprint = hashlib.sha256(json.dumps([item.get("title"), body, item.get("date"), item.get("rating")], ensure_ascii=False).encode()).hexdigest()[:16]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        review_url = item.get("link") or item.get("review_link")
        match = re.search(r"/(?:customer-reviews/(?:srp/-/)?|reviews/)([A-Z0-9]+)(?:[/?#]|$)", review_url or "")
        rid = match[1] if match else f"hash-{fingerprint}"
        country_match = re.search(r"Reviewed in (?:the )?(.+?) on ", item.get("date") or "", re.I)
        reviews.append({"review_evidence_id": f"R-{asin}-{rid}", "asin": asin, "product_name": title,
                        "review_id": rid, "review_id_kind": "amazon" if match else "content_hash",
                        "review_title": item.get("title"), "review_text": body,
                        "review_text_kind":item["_kind"],"source_section":item["_section"],
                        "star_rating": number(item.get("rating")), "review_date": iso_date(item.get("date")),
                        "review_date_raw": item.get("date"), "review_country_explicit": country_match[1] if country_match else (item.get("country") or {}).get("name"),
                        "verified_purchase": item.get("verified_purchase"), "helpful_votes_text": item.get("helpful_votes"),
                        "variant": item.get("product"), "is_vine": item.get("is_vine"),
                        "review_scope": "Listing review; may refer to a different variant. See variant and quoted text.",
                        "source_url": review_url or url, "source_raw_file": envelope["raw_file"],
                        "collected_at_utc": envelope["fetched_at_utc"]})
    ranks = bsrs(details)
    top_bsr = ranks[0] if ranks else {}
    selected_variants = {group.get("title", "").lower(): item.get("name")
                         for group in pr.get("variants", []) for item in group.get("items", []) if item.get("selected")}
    price = first(number(pr.get("extracted_price")), number(search.get("extracted_price")))
    bought = first(pr.get("bought_last_month"), search.get("bought_last_month"))
    product = {"product_evidence_id": product_id, "asin": asin, "product_name": title,
               "brand": first(pr.get("brand"), details.get("brand_name"), specs.get("brand")),
               "marketplace": "amazon.com", "target_market": "US",
               "language_requested": "en_US", "price_usd": price, "price_text": first(pr.get("price"), search.get("price")),
               "price_max_usd": number(pr.get("extracted_max_price")), "currency": "USD" if price is not None else None,
               "star_rating": first(number(pr.get("rating")), number(search.get("rating"))),
               "displayed_review_count": first(number(pr.get("reviews")), number(search.get("reviews"))),
               "rating_count_explicit": number(counts.get("ratings_count")), "written_review_count_explicit": number(counts.get("reviews_count")),
               "reviews_collected": len(reviews), "quality_basis": "Customer ratings and sampled review text; no independent product test",
               "quality_summary_vi": None, "positive_review_themes_vi": None, "negative_review_themes_vi": None,
               "description": description or None, "seller_features": about or None,
               "color": first(specs.get("color"), details.get("color"), selected_variants.get("color")),
               "size": first(specs.get("size"), details.get("size"), selected_variants.get("size")),
               "dimensions": first(details.get("product_dimensions"), details.get("item_dimensions_l_x_w"), details.get("dimensions"), details.get("package_dimensions")),
               "material": first(specs.get("material"), details.get("material_type"), details.get("material")),
               "scent": first(details.get("scent_name"), specs.get("scent")),
               "included_components": first(details.get("included_components"), specs.get("included_components")),
               "specifications": {**details, **specs}, "variants": pr.get("variants"), "badges": pr.get("badges"),
               "bought_last_month_text": bought, "bought_last_month_lower_bound": purchase_lower_bound(bought),
               "bsr_main_rank": top_bsr.get("rank"), "bsr_main_category": top_bsr.get("category"), "bsr_all": ranks,
               "amazon_ai_review_summary": summary.get("text"), "rating_histogram": first(counts.get("histogram"), {k: v for k, v in counts.items() if 'star' in k}) or None,
               "christmas_in_listing": bool(re.search(r"\b(christmas|xmas)\b", listing_text, re.I)),
               "occasion_basis": "Seller listing; not proof of actual Christmas purchases",
               "date_first_available": details.get("date_first_available"),
               "review_excerpts": [r["review_text"] for r in reviews[:3]],
               "search_positions": discovery.get("search_positions", []),
               "source_url": url, "source_raw_file": envelope["raw_file"],
               "search_raw_files": discovery["search_sources"], "collected_at_utc": envelope["fetched_at_utc"],
               "source_processed_at": (data.get("search_metadata") or {}).get("processed_at"),
               "field_sources": {"price_usd": "product_results.extracted_price" if number(pr.get("extracted_price")) is not None else "search_result.extracted_price",
                                 "star_rating": "product_results.rating" if number(pr.get("rating")) is not None else "search_result.rating",
                                 "displayed_review_count": "product_results.reviews" if number(pr.get("reviews")) is not None else "search_result.reviews"}}
    product["missing_fields"] = [name for name in ("price_usd", "star_rating", "bsr_main_rank", "color", "size", "material", "included_components") if product.get(name) is None]
    if not reviews:
        product["missing_fields"].append("customer_review_text")
    return product, reviews


def write_csv(path, rows, fields=None):
    fields = fields or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            clean = {}
            for key in fields:
                value = row.get(key)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                    value = "'" + value  # CSV spreadsheet formula injection protection. Raw JSON stays exact.
                clean[key] = value
            writer.writerow(clean)
