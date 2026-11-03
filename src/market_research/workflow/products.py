"""Source failures are isolated per direction. Search broadly, enrich fairly."""
from ..providers import amazon, shopping, archive
from ..providers.client import SourceError
from ..analysis.products import candidate, resolve, enrich_product, relevant
from ..common import identity
import re
from ..business.domain import active, classify_product
from .design_content import content_mode
from urllib.parse import urlsplit
from ..providers.web import source_for


def company_filter(collected, config, run):
    """Keep observed exclusions, but never enrich/recommend a forbidden item."""
    if not active(config):
        return collected
    kept, removed = [], set()
    for product in collected["products"]:
        fit = classify_product(product, config)
        product["business_fit"] = fit
        if fit["status"] == "excluded":
            removed.add(product["product_id"])
            collected["exclusions"].append({"product_id": product["product_id"], "listing_id": product.get("listing_id"), "title": product["title"], "reason": fit["reason"], "kind": "company_domain", "business_fit": fit, "evidence_ids": product.get("evidence_ids", [])})
            run.log("search", "company_product_filtered", fit["reason"], product_id=product["product_id"], title=product["title"], business_fit=fit)
        else:
            kept.append(product)
    collected["products"] = kept
    if removed:
        for field in ("offers", "product_matches", "reviews"):
            collected[field] = [row for row in collected[field] if row.get("product_id") not in removed]
    return collected


def simpler_query(query):
    words = re.findall(r"[a-z0-9]+", query.lower())
    words = [w for w in words if w not in {"family", "name", "names", "for", "with", "and", "the", "best", "ideas", "2026"}]
    return " ".join(words)


def content_filter(collected, directions, run):
    """A detail response must not silently replace a matching design variant."""
    lookup = {d["id"]: d for d in directions}
    kept, removed = [], set()
    for product in collected["products"]:
        valid = []
        for did in product["direction_ids"]:
            direction = lookup.get(did, {})
            if direction.get("content_focus") != "designs":
                valid.append(did)
                continue
            design = direction.get("source_design") or {}
            if relevant(product["title"], direction["keyword"], subject=design.get("subject"), kind=design.get("kind")):
                valid.append(did)
            else:
                reason = "Tiêu đề biến thể sau lấy chi tiết không còn khớp nội dung hình/câu chữ của keyword đã đo"
                collected["exclusions"].append({"product_id": product["product_id"], "direction_id": did, "kind": "design_content_mismatch",
                    "title": product["title"], "keyword": direction["keyword"], "reason": reason, "evidence_ids": product.get("evidence_ids", [])})
                run.log("enrich", "design_variant_filtered", reason, product_id=product["product_id"], keyword=direction["keyword"])
        if valid:
            product["direction_ids"] = valid
            kept.append(product)
        else:
            removed.add(product["product_id"])
    collected["products"] = kept
    if removed:
        for field in ("offers", "product_matches", "reviews"):
            collected[field] = [row for row in collected[field] if row.get("product_id") not in removed]
    return collected


def search_source(client, adapter, query, *, preserve_query=False):
    try:
        envelope = adapter.search(client, query)
        if not preserve_query and (envelope["response"].get("organic_results") == [] or envelope["response"].get("shopping_results") == []):
            fallback = simpler_query(query)
            if fallback and fallback != query.lower():
                return adapter.search(client, fallback)
        return envelope
    except SourceError as error:
        fallback = simpler_query(query)
        if not preserve_query and fallback and fallback != query.lower() and any(s in str(error).lower() for s in ("returned any results", "no results")):
            return adapter.search(client, fallback)
        raise


def public_listing_rows(run, pages, direction):
    """Reuse actual item pages, never a pin/feed/search page as a sold product.

    Source title is preliminary evidence of this print/model; no price, sales,
    material or review is inferred from surrounding page text or the image.
    """
    rows = []
    paths = {"etsy": r"^/listing/[^/]+", "ebay": r"^/itm/[^/]+", "walmart": r"^/ip/[^/]+"}
    design = direction.get("source_design") or {}
    from .web_discovery import poor_page
    for page in pages:
        url = page.get("url") or ""
        platform = source_for(url)
        if platform not in paths or not re.match(paths[platform], urlsplit(url).path, re.I):
            continue
        if poor_page({**page, "content": page.get("excerpt", "")}, set(re.findall(r"[a-z]+", direction["keyword"].casefold()))):
            continue
        if not relevant(page.get("title", ""), direction["keyword"], subject=design.get("subject"), kind=design.get("kind")):
            continue
        proof = [run.evidence[eid] for eid in page.get("evidence_ids", []) if eid in run.evidence]
        if not proof:
            continue
        envelope = {"retrieved_at": proof[-1]["retrieved_at"], "raw_file": proof[-1].get("raw_file")}
        picture = page.get("image") or next(iter(page.get("image_links") or []), None)
        row = candidate({"title": page["title"], "link": url, "source": platform, "thumbnail": picture}, "shopping", direction, envelope, run)
        if row is None:
            continue
        row.update(source="public_web", relevant=True, search_query=direction["search_query"],
            occurrence_id=identity("S", row["listing_id"], direction["id"], "public_web"),
            evidence_ids=sorted(set(row["evidence_ids"] + page["evidence_ids"])),
            detail_status="public_listing_excerpt", retrieval_providers=page.get("retrieval_providers", []),
            rating_scope="unavailable_public_listing_excerpt",
            suitability_notes=["Mẫu lấy từ trang listing công khai khớp keyword đã chọn; chưa xác minh biến thể, giá, doanh số hoặc phản hồi."],
            design_match={"query": direction["keyword"], "subject": design.get("subject"), "status": "title_matched",
                "image_status": "source_thumbnail_not_visually_verified" if picture else "missing"})
        rows.append(row)
    return rows


def collect(run, client, config, directions, public_pages=()):
    occurrences, archived_reviews, source_status, discussions = [], [], [], []
    collection_mode=config.get("product_collection",{}).get("mode","api")
    if config["mode"] != "offline" and collection_mode != "api":
        from .scraped_products import collect as scrape
        occurrences,source_status,discussions=scrape(run,client,config,directions)
    shopping_queries = set()
    for direction in directions:
        if config["mode"] == "offline":
            rows, reviews = archive.candidates(run, direction)
            occurrences.extend(rows)
            archived_reviews.extend(reviews)
            source_status.extend([{"direction_id": direction["id"], "source": "amazon", "status": "archive", "count": len(rows)}, {"direction_id": direction["id"], "source": "shopping", "status": "unavailable", "reason": "Không có snapshot Shopping trong bộ lưu trữ"}])
            continue
        for source, adapter in (() if collection_mode=="scraper" else (("amazon", amazon), ("shopping", shopping))):
            if not config["sources"][source]:
                source_status.append({"direction_id": direction["id"], "source": source, "status": "skipped"})
                continue
            if source == "shopping" and config.get("discovery", {}).get("enabled"):
                query_key = " ".join(direction["search_query"].casefold().split())
                maximum = config["limits"].get("shopping_keywords", 2)
                if query_key not in shopping_queries and len(shopping_queries) >= maximum:
                    source_status.append({"direction_id": direction["id"], "source": source, "status": "limited", "reason": f"Ngoài {maximum} keyword đối chiếu Shopping đã chọn"})
                    run.log("search", "shopping_limited", "Giữ lượt cho Amazon theo giới hạn Shopping", keyword=direction["keyword"], limit=maximum)
                    continue
                shopping_queries.add(query_key)
            try:
                envelope = search_source(client, adapter, direction["search_query"], preserve_query=content_mode(config) == "designs")
                items = envelope["response"].get("organic_results" if source == "amazon" else "shopping_results", [])
                if not isinstance(items, list):
                    raise SourceError("Schema danh sách sản phẩm không hợp lệ")
                count = 0
                for item in items[:config["limits"]["products_per_direction"]]:
                    if not isinstance(item, dict):
                        continue
                    row = candidate(item, source, direction, envelope, run)
                    if row:
                        design = direction.get("source_design") or {}
                        row["relevant"] = relevant(row["title"], direction["keyword"], subject=design.get("subject"), kind=design.get("kind"))
                        if design:
                            row["design_match"] = {"subject": design["subject"], "kind": design.get("kind"),
                                "status": "title_matched" if row["relevant"] else "not_matched",
                                "query": direction["keyword"], "evidence_ids": list(row["evidence_ids"]),
                                "image_status": "source_thumbnail_not_visually_verified" if row.get("thumbnail") else "missing"}
                        row["search_query"] = envelope["parameters"].get("k") or envelope["parameters"].get("q")
                        row["occurrence_id"] = identity("S", row["listing_id"], direction["id"], source, row["search_position"], row["sponsored"])
                        occurrences.append(row)
                        count += 1
                source_status.append({"direction_id": direction["id"], "source": source, "status": "available" if count else "empty", "count": count})
            except (SourceError, ValueError, KeyError, TypeError) as error:
                run.warn(f"Tìm mẫu / {source} / {direction['keyword']}: {error}")
                source_status.append({"direction_id": direction["id"], "source": source, "status": "unavailable", "reason": str(error)})
    if config["mode"] != "offline":
        for direction in directions:
            if any(direction["id"] in row["direction_ids"] and row.get("relevant") and row.get("sponsored") is not True
                   and (not active(config) or classify_product(row, config)["status"] != "excluded") for row in occurrences):
                continue
            reused = public_listing_rows(run, public_pages, direction)[:config["limits"]["products_per_direction"]]
            if reused:
                occurrences.extend(reused)
                source_status.append({"direction_id": direction["id"], "source": "public_web", "status": "available", "count": len(reused),
                    "method": "reuse_matching_public_listing", "extra_requests": 0, "price_reviews_sales": "unverified"})
                run.log("search", "public_listing_reused", "Dùng lại listing có nguồn khớp keyword; không gọi thêm API và không suy giá/doanh số", keyword=direction["keyword"], count=len(reused))
    products, offers, matches, excluded = resolve(occurrences)
    # De-duplicate archived reviews repeated through several direction queries.
    reviews = list({r["id"]: r for r in archived_reviews}.values())
    return company_filter({"products": products, "offers": offers, "product_matches": matches, "search_occurrences": occurrences, "reviews": reviews, "exclusions": excluded, "source_status": source_status,"discussions":discussions}, config, run)


def enrich(run, client, config, collected, directions):
    collected = company_filter(collected, config, run)
    if config["mode"] == "offline":
        return collected
    if config.get("product_collection",{}).get("mode","api") != "api":
        from .scraped_products import enrich as enrich_scraped
        collected=enrich_scraped(run,client,config,collected)
        if config["product_collection"]["mode"]=="scraper":
            return company_filter(content_filter(collected,directions,run),config,run)
    products = {p["product_id"]: p for p in collected["products"]}
    queues = []
    for niche in config["niches"]:
        direction_ids = [d["id"] for d in directions if d["niche_id"] == niche["id"]]
        by_direction = [[p for p in sorted(products.values(), key=lambda p: -(p["purchase_lower_bound"] or 0)) if did in p["direction_ids"] and p["asin"]] for did in direction_ids]
        ordered, known = [], set()
        for depth in range(max((len(q) for q in by_direction), default=0)):
            for queue in by_direction:
                if len(queue) > depth and queue[depth]["product_id"] not in known:
                    ordered.append(queue[depth])
                    known.add(queue[depth]["product_id"])
        if ordered:
            queues.append(ordered[:config["limits"]["enrich_per_niche"]])
    chosen, reviewed = [], set()
    for depth in range(max((len(q) for q in queues), default=0)):
        for queue in queues:
            if len(queue) > depth and queue[depth]["product_id"] not in reviewed:
                chosen.append(queue[depth])
                reviewed.add(queue[depth]["product_id"])
    for p in chosen:
        if p.get("collection_method")=="public_http":
            continue
        if config.get("discovery", {}).get("enabled") and sum(u["provider"] == "serpapi" and u.get("engine") == "amazon_product" for u in run.manifest["usage"]) >= config["limits"].get("product_details", 3):
            break
        try:
            envelope = amazon.detail(client, p["asin"])
            updated, reviews = enrich_product(p, envelope, run, config["limits"]["reviews_per_product"], config["as_of_date"])
            products[p["product_id"]] = updated
            collected["reviews"].extend(reviews)
            offer = {k: updated.get(k) for k in ("product_id", "listing_id", "merchant", "price", "currency", "variant", "url", "evidence_ids")}
            offer.update(observed_at=updated["observed_at"], offer_id=identity("O", updated["listing_id"], updated["observed_at"], updated["price"], updated["variant"]), unit_price=None, unit_count=None, shipping=None, tax=None, source_type="product_listing")
            if offer["offer_id"] not in {o["offer_id"] for o in collected["offers"]}:
                collected["offers"].append(offer)
        except (SourceError, ValueError, KeyError, TypeError) as error:
            run.warn(f"Chi tiết / {p['asin']}: {error}")
    collected["products"] = list(products.values())
    collected["reviews"] = list({r["id"]: r for r in collected["reviews"]}.values())
    return company_filter(content_filter(collected, directions, run), config, run)
