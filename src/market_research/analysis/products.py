"""Conservative identities and source-specific offers, reviews and attributes."""
import re
from datetime import datetime

from ..common import canonical_url, identity, number, safe_url, text, tokens


def purchase_band(label):
    if not isinstance(label, str) or not re.search(r"bought.*(?:past|last) month", label, re.I):
        return None
    match = re.search(r"([\d,.]+)\s*([KM]?)\+?\s+bought", label, re.I)
    return int(float(match[1].replace(",", "")) * {"": 1, "K": 1000, "M": 1000000}[match[2].upper()]) if match else None


def stems(value):
    def singular(word):
        if len(word) > 4 and word.endswith("ies"):
            return word[:-3] + "y"
        if word.endswith(("ches", "shes", "sses", "xes")):
            return word[:-2]
        return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "us")) else word
    # A calendar year is a model attribute even though shared search helpers
    # omit the application's original default year from general topic tokens.
    return {singular(word) for word in tokens(value) | set(re.findall(r"\b(?:19|20)\d{2}\b", value))}


def relevant(title, query, *, subject=None, kind=None):
    # Keep the distinguishing model, construction, finish and subject words.
    # Equivalent listing wording is allowed without borrowing another model's
    # evidence, such as a wall calendar for a tabletop spiral calendar.
    def normalize(value):
        aliases = [
            (r"\b(?:t[ -]?shirts?|tees?)\b", "shirt"),
            (r"\b(?:gift\s+wrap(?:ping)?(?:\s+paper)?|wrapping\s+paper)\b", "giftwrap"),
            (r"\bkey[ -]?(?:rings?|chains?)\b", "keychain"),
            (r"\btote\s+bags?\b", "tote"),
            (r"\b(?:table[ -]?top|desktop)\b", "desk"),
            (r"\b(?:spiral[ -]?(?:bound|binding)|wire[ -]?(?:o[ -]?)?(?:bound|binding))\b", "spiral"),
            (r"\bring[ -]?(?:bound|binding)\b", "ringbound"),
            (r"\btear[ -]?(?:off|away)\b", "tearoff"),
            (r"\b(?:3[ -]?d|three[ -]dimensional|3[ -]dimensional)\b", "3d"),
            (r"\b(?:crew[ -]?neck)\b", "crewneck"),
            (r"\bv[ -]?neck\b", "vneck"),
            (r"\bdropped\s+shoulder\b", "drop shoulder"),
            (r"\b(?:plexiglass|perspex)\b", "acrylic"),
            (r"\bwooden\b", "wood"),
            (r"\b(?:engraving|engraved)\b", "engraved"),
            (r"\b(?:embroidery|embroidered)\b", "embroidered"),
            (r"\b(?:foil[ -]stamped|foiled)\b", "foil"),
            (r"\bdie[ -]?cut\b", "diecut"),
            (r"\bprint[ -]ready\b", "printable"),
            (r"\b(?:dye[ -]?sublimat(?:ed|ion)|sublimated)\b", "sublimation"),
        ]
        for pattern, replacement in aliases:
            value = re.sub(pattern, replacement, value, flags=re.I)
        value = re.sub(r"\bshaped\b", "shape", value, flags=re.I)
        # A listing explicitly supporting sublimation supports printing, while
        # a generic printable blank does not establish sublimation compatibility.
        if re.search(r"\bsublimation\b", value, re.I):
            value += " printable"
        return value
    if subject and kind in {"slogan", "character", "person"}:
        # Exact wording matters: 'not a morning person' is a different print
        # from 'a morning person', even when product words overlap.
        phrase = lambda value: " ".join(re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", value.casefold()))
        if not re.search(r"(?<!\w)" + re.escape(phrase(subject)) + r"(?!\w)", phrase(title)):
            return False
    wanted = stems(normalize(query)) - {"gift", "gifts", "set", "pack", "personalized", "custom", "ideas"}
    present = stems(normalize(title))
    context = {"printed", "graphic", "design", "pattern", "personalised", "customized", "customised", "monogrammed",
               "men", "women", "kid", "child", "adult", "unisex", "handmade", "on", "in", "shape", "ready"}
    wanted -= context
    return bool(wanted) and wanted <= present


def specification_fields(value):
    """Read labelled provider values without guessing labels from prose."""
    if isinstance(value, str):
        output = {}
        for line in re.split(r"[\n;]+", value):
            key, separator, item = line.partition(":")
            if separator and key.strip() and item.strip():
                output[re.sub(r"[^a-z0-9]+", "_", key.casefold()).strip("_")] = item.strip()
        return output
    if isinstance(value, list):
        output = {}
        for row in value:
            output.update(specification_fields(row))
        return output
    if not isinstance(value, dict):
        return {}
    label = next((value[k] for k in ("name", "label", "key", "title") if isinstance(value.get(k), str)), None)
    if label is not None and "value" in value:
        return specification_fields({label: value["value"]})
    return {re.sub(r"[^a-z0-9]+", "_", str(k).casefold()).strip("_"):
            v["value"] if isinstance(v, dict) and "value" in v else v for k, v in value.items()}


def candidate(item, source, direction, envelope, run):
    title = text(item.get("title"))
    asin = item.get("asin") if source == "amazon" else None
    url = (f"https://www.amazon.com/dp/{asin}" if asin and re.fullmatch(r"[A-Z0-9]{10}", asin) else None)
    if source == "shopping":
        url = next((u for u in (item.get("merchant_link"), item.get("link"), item.get("product_link")) if safe_url(u)), None)
        canonical = canonical_url(url)
        if canonical:
            match = re.fullmatch(r"https://www.amazon.com/dp/([A-Z0-9]{10})", canonical)
            if match:
                asin = match[1]
    url = canonical_url(url)
    if not title or not url:
        return None
    lid = identity("L", "amazon.com", asin) if asin else identity("L", source, url, item.get("product_id"), text(item.get("source")))
    pid = identity("P", "amazon.com", asin) if asin else identity("P", source, url, item.get("product_id"))
    sponsor = item.get("sponsored")
    sponsor = sponsor if type(sponsor) is bool else None
    eid = run.add_evidence("search_listing", url, envelope["retrieved_at"], envelope["raw_file"], title, source=source, asin=asin)
    item_price = number(item.get("extracted_price"))
    if item_price is None and isinstance(item.get("price"), dict):
        item_price = number(item["price"].get("value"))
    currency = item.get("currency") or ("USD" if item_price is not None and (source == "amazon" or "$" in text(item.get("price"))) else None)
    return {"product_id": pid, "listing_id": lid, "asin": asin, "title": title, "source": source,
        "merchant": "Chưa xác định nhà bán (Amazon.com)" if asin else text(item.get("source")) or "Chưa xác định", "url": url,
        "provider_product_id": item.get("product_id"), "thumbnail": item.get("thumbnail") if safe_url(item.get("thumbnail")) else None,
        "price": item_price, "currency": currency, "rating": number(item.get("rating")), "review_count": number(item.get("reviews")),
        "rating_scope": "amazon_listing_may_share_variants" if source == "amazon" else "shopping_aggregate_or_merchant_unspecified",
        "purchase_badge": item.get("bought_last_month") if source == "amazon" else None,
        "purchase_lower_bound": purchase_band(item.get("bought_last_month")) if source == "amazon" else None,
        "purchase_scope": "amazon_search_card" if source == "amazon" else None,
        "observed_at": envelope["retrieved_at"], "direction_ids": [direction["id"]], "evidence_ids": [eid],
        "suitability_status": "preliminary_keyword_match", "suitability_notes": ["Khớp từ trong tên là bước lọc sơ bộ; chưa xác nhận đúng công dụng, người nhận, quy cách và biến thể cần bán."],
        "sponsored": sponsor, "search_position": item.get("position"), "description": "", "attributes": {}, "variant": None, "detail_status": "search_only"}


def resolve(occurrences):
    products, offers, matches, exclusions = {}, [], [], []
    for row in occurrences:
        if row["sponsored"] is True:
            exclusions.append({"listing_id": row["listing_id"], "reason": "Lần xuất hiện được đánh dấu Sponsored", "evidence_ids": row["evidence_ids"]})
            continue
        if not row.get("relevant", True):
            exclusions.append({"listing_id": row["listing_id"], "reason": "Tên chưa xác nhận đúng hướng sản phẩm", "evidence_ids": row["evidence_ids"]})
            continue
        pid = row["product_id"]
        previous = products.get(pid)
        if previous:
            previous["direction_ids"] = sorted(set(previous["direction_ids"] + row["direction_ids"]))
            previous["evidence_ids"] = sorted(set(previous["evidence_ids"] + row["evidence_ids"]))
            previous["discovery_sources"] = sorted(set(previous["discovery_sources"] + [row["source"]]))
            matches.append({"product_id": pid, "listing_id": row["listing_id"], "method": "same_asin" if row["asin"] else "same_canonical_listing_identity", "status": "verified_identity", "evidence_ids": row["evidence_ids"]})
        else:
            products[pid] = {**row, "discovery_sources": [row["source"]]}
        offer = {k: row.get(k) for k in ("product_id", "listing_id", "merchant", "price", "currency", "variant", "observed_at", "url", "evidence_ids")}
        offer.update(offer_id=identity("O", row["listing_id"], row["observed_at"], row["price"], row["variant"]), unit_price=None, unit_count=None, shipping=None, tax=None)
        if offer["offer_id"] not in {o["offer_id"] for o in offers}:
            offers.append(offer)
    return list(products.values()), offers, matches, exclusions


def parse_date(label):
    if not isinstance(label, str):
        return None
    value = re.sub(r"^.*?\bon\s+", "", label).strip()
    for fmt in ("%B %d, %Y", "%d %B %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def enrich_product(product, envelope, run, review_limit, cutoff):
    data = envelope["response"]
    raw = data.get("product_results") or {}
    if not raw.get("title"):
        return product, []
    specs = [(name, specification_fields(data.get(name))) for name in ("product_details", "product_specifications", "item_specifications")]
    description = text(data.get("about_item") or data.get("product_description"))
    eid = run.add_evidence("product_listing", product["url"], envelope["retrieved_at"], envelope["raw_file"], description[:4000] or raw["title"], asin=product["asin"])
    attributes = {}
    aliases = {"material": ("material", "material_type"), "dimensions": ("product_dimensions", "item_dimensions_l_x_w", "item_dimensions", "dimensions"), "unit_count": ("unit_count", "number_of_items"), "brand": ("brand_name", "brand"), "color": ("color",), "size": ("size",), "weight": ("item_weight",), "special_feature": ("special_feature", "special_features"),
        "shape": ("shape", "item_shape"), "style": ("style", "style_name", "model_name"),
        "format": ("format", "calendar_format", "item_form"), "layout": ("layout", "page_layout", "page_format"),
        "binding": ("binding", "binding_type", "binding_style"), "finish": ("finish", "finish_type", "surface_finish"),
        "print_method": ("printing_method", "print_method", "printing_technology"),
        "structure": ("construction", "construction_type")}
    for field, keys in aliases.items():
        observations = [{"source_field": name + "." + key, "value": fields[key]} for name, fields in specs
                        for key in [next((k for k in keys if fields.get(k) not in (None, "", [], {})), None)] if key is not None]
        distinct = {text(row["value"]).strip().casefold() for row in observations}
        conflict = len(distinct) > 1
        value = observations[-1]["value"] if observations and not conflict else None
        attributes[field] = {"value": value, "status": "conflicting" if conflict else "observed" if observations else "missing", "evidence_ids": [eid] if observations else [], "source_values": observations}
    badge = raw.get("bought_last_month")
    selected_variants = {group.get("title", "variant"): item.get("name") for group in raw.get("variants", []) if isinstance(group, dict) for item in group.get("items", []) if isinstance(item, dict) and item.get("selected")}
    result = {**product, "title": text(raw["title"]), "description": description, "price": number(raw.get("extracted_price")),
        "currency": "USD" if number(raw.get("extracted_price")) is not None else None,
        "rating": number(raw.get("rating")), "review_count": number(raw.get("reviews")), "purchase_badge": badge,
        "purchase_lower_bound": purchase_band(badge), "purchase_scope": "amazon_product_page", "observed_at": envelope["retrieved_at"],
        "attributes": attributes, "evidence_ids": sorted(set(product["evidence_ids"] + [eid])), "detail_status": "available",
        "suitability_status": "preliminary_keyword_match", "suitability_notes": product.get("suitability_notes") or ["Thông tin listing chưa chứng minh mẫu phù hợp hoàn toàn với người nhận và ý tưởng bán."],
        "availability": text(raw.get("stock")), "variant": raw.get("selected_variant") or selected_variants or None,
        "source": "amazon", "rating_scope": "amazon_listing_may_share_variants"}
    info = data.get("reviews_information") or {}
    items = [(r, "full") for r in info.get("authors_reviews", []) if isinstance(r, dict)]
    for insight in (info.get("summary") or {}).get("insights", []):
        for item in insight.get("examples", []):
            if isinstance(item, dict) and safe_url(item.get("link")) and "/customer-reviews/" in item["link"]:
                items.append(({**item, "text": item.get("snippet")}, "excerpt"))
    reviews, seen = [], set()
    for item, kind in items if review_limit > 0 else []:
        body = text(item.get("text") or item.get("body"))
        if not body:
            continue
        published = parse_date(item.get("date"))
        if published and published > cutoff:
            continue
        url = item.get("link") or item.get("review_link") or product["url"]
        url = url if safe_url(url) else product["url"]
        source_id = re.search(r"/customer-reviews/(?:srp/-/)?([A-Z0-9]+)", url)
        rid = identity("R", product["asin"], source_id[1] if source_id else body)
        if rid in seen:
            continue
        seen.add(rid)
        reid = run.add_evidence("review", url, envelope["retrieved_at"], envelope["raw_file"], body, asin=product["asin"], published_at=published)
        reviews.append({"id": rid, "product_id": product["product_id"], "asin": product["asin"], "text": body, "kind": kind,
            "rating": number(item.get("rating")), "published_at": published, "variant": item.get("product"), "verified_purchase": item.get("verified_purchase"), "evidence_ids": [reid]})
        if len(reviews) >= review_limit:
            break
    return result, reviews
