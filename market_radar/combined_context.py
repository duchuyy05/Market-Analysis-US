"""Computed facts for the combined report; no configuration-written ideas are sent."""
from collections import Counter
from statistics import median


def enrich_pack(pack,data,analysis):
    products={p["asin"]:p for p in data["products"]}
    product_ids={c["asin"]:i for i,c in pack["evidence"].items() if c["type"]=="product"}
    timing_ids={c["family_id"]:i for i,c in pack["evidence"].items() if c["type"]=="timing"}
    ranks={}
    for r in analysis["monthly_top5"]:
        ranks[r["asin"]]=min(ranks.get(r["asin"],1000),r["rank_in_month"])
    for card in pack["evidence"].values():
        if card["type"]=="product":
            p=products[card["asin"]]
            card["statistics"]={k:p.get(k) for k in ("rating_out_of_5","displayed_rating_or_review_count",
                "rating_count_explicit","written_review_count_explicit","dimensions","listing_unit_count","listing_number_of_items")}
            card["statistics"]["listing_text_is_truncated"]=len(p.get("seller_features") or p.get("description") or "")>280
        elif card["type"]=="timing":
            card["history"]=[{k:r.get(k) for k in ("year","month","mean_interest_index","observation_status","observed_days")}
                for r in data["trends"] if r["keyword_id"]==card["source_id"]]
    for task in pack["tasks"]:
        cards=task["evidence"]
        ps=[c for c in cards.values() if c["type"]=="product"]
        asins={c["asin"] for c in ps}
        prices=[c["price_usd"] for c in ps if c["price_usd"] is not None]
        reviews=[r for r in data["reviews"] if r["asin"] in asins]
        themes=Counter(theme for _,theme in sorted({(r["review_id"],r["theme"]) for r in data["customer_needs"] if r["asin"] in asins}))
        shortlist=[]
        for r in analysis["monthly_top5"]:
            if r["asin"] not in asins: continue
            shortlist.append({"month":r["month"],"rank_in_month":r["rank_in_month"],"product_id":product_ids[r["asin"]],
                "timing_id":timing_ids[r["timing_keyword_id"].removeprefix("K-")],"price_usd":r["price_usd"],
                "snapshot_purchase_badge":r["current_purchase_badge"],"snapshot_at":r["current_snapshot_at_utc"],
                "timing_status":r["timing_status"],"historical_years_used":r["historical_years_used"]})
        task["computed"]={"method":"Python-calculated facts; explain them, never recalculate or treat a shortlist as the whole market",
            "metrics":{"products":len(ps),"full_reviews":sum(r.get("review_text_kind","full")=="full" for r in reviews),
                "review_excerpts":sum(r.get("review_text_kind")=="excerpt" for r in reviews),
                "price_min_usd":min(prices) if prices else None,"price_median_usd":median(prices) if prices else None,
                "price_max_usd":max(prices) if prices else None,"products_without_price":len(ps)-len(prices)},
            "monthly_shortlist":shortlist,"review_theme_mentions":dict(themes),
            "limits":["Search interest is relative and separately normalized for each keyword, not visits or orders",
                "Historical peaks use completed periods, not future demand predictions",
                "Purchase badges are rounded snapshots, not historical monthly sales",
                "Theme mentions are keyword matches in collected full reviews and excerpts, not sentiment or population rates"]}
        # Keep detail manageable for a small model while retaining all product and timing cards.
        selected_reviews=sorted((c for c in cards.values() if c["type"]=="review"),
            key=lambda c:(c["text_kind"]!="full",ranks.get(c["asin"],1000),c["product_id"],c["id"]))[:12]
        selected_web=[c for c in cards.values() if c["type"]=="web_context"][:4]
        keep={c["id"] for c in selected_reviews+selected_web}
        task["evidence"]={i:c for i,c in cards.items() if c["type"] in {"product","timing"} or i in keep}
    pack["report_profile"]="combined"
    return pack
