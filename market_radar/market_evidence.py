"""Join keyword seasonality to independently sourced Amazon purchase bands and review coverage."""
from collections import Counter
import json

from .normalize import purchase_lower_bound
from .seasonal import family_match


def build_market_evidence(output, data, analysis, manifest):
    products={p["asin"]:p for p in data["products"]}
    families={f["id"]:f for f in manifest["config"]["families"]}
    evidence=[]
    seen=set()
    paths=set(manifest["sources"].values())
    paths.update(path for values in manifest.get("supplement_sources",{}).values() for path in values)
    for path in sorted(paths):
        raw=json.loads((output/path).read_text(encoding="utf-8"))
        params, response=raw.get("parameters",{}),raw.get("response") or {}
        if params.get("amazon_domain")!="amazon.com":
            continue
        if params.get("engine")=="amazon_product":
            items=[(params.get("asin"),response.get("product_results") or {},"product_listing")]
        elif params.get("engine")=="amazon":
            items=[(item.get("asin"),item,"search_listing") for item in response.get("organic_results",[]) if not item.get("sponsored")]
        else:
            continue
        for asin, item, kind in items:
            p=products.get(asin)
            if not p or not any(family_match(item.get("title", ""),families[fid]) for fid in p["family_ids"]):
                continue
            badge=item.get("bought_last_month")
            lower=purchase_lower_bound(badge)
            if lower is None or (asin,path,kind) in seen:
                continue
            seen.add((asin,path,kind))
            evidence.append({"evidence_id":f"S{len(evidence)+1}","asin":asin,"product_name":p["product_name"],
                "purchase_badge":badge,"purchase_lower_bound":lower,"evidence_type":kind,
                "observed_at_utc":raw["fetched_at_utc"],"source_raw_file":path,"source_url":p["source_url"],
                "source_query":params.get("k"),"measure":"Rounded Amazon past-month purchase band; not exact units, historical sales or US buyer count"})
    full=Counter(r["asin"] for r in data["reviews"] if r.get("review_text_kind","full")=="full")
    excerpts=Counter(r["asin"] for r in data["reviews"] if r.get("review_text_kind")=="excerpt")
    dated=Counter(r["asin"] for r in data["reviews"] if r.get("review_text_kind","full")=="full" and r.get("review_date"))
    verified=Counter(r["asin"] for r in data["reviews"] if r.get("review_text_kind","full")=="full" and r.get("verified_purchase") is True)
    linked=[]; summaries=[]
    for fid, family in families.items():
        keyword_id="K-"+fid
        timing=[r for r in analysis["monthly_keyword_analysis"] if r["keyword_id"]==keyword_id]
        peaks=[r["month"] for r in timing if r["timing_status"] in {"historical_period_peak","historical_q4_peak"}]
        supported=[r["month"] for r in timing if r.get("timing_supported")]
        matched=[p for p in products.values() if fid in p["family_ids"]]
        family_rows=[]
        for p in matched:
            choices=[r for r in evidence if r["asin"]==p["asin"]]
            choices.sort(key=lambda r:(r["evidence_type"]=="product_listing",r["observed_at_utc"]),reverse=True)
            best=choices[0] if choices else None
            row={"keyword_id":keyword_id,"keyword":family["keyword"],"niche_id":family["niche_id"],
                 "peak_months":peaks,"supported_months":supported,"amazon_query":family["amazon_query"],
                 "asin":p["asin"],"product_name":p["product_name"],"price_usd":p["price_usd"],
                 "product_observed_at_utc":p.get("observed_at_utc"),"product_source_raw_file":p.get("source_raw_file"),
                 "purchase_badge":best["purchase_badge"] if best else None,
                 "purchase_lower_bound":best["purchase_lower_bound"] if best else None,
                 "purchase_source_type":best["evidence_type"] if best else "not_returned",
                 "purchase_observed_at_utc":best["observed_at_utc"] if best else None,
                 "purchase_evidence_id":best["evidence_id"] if best else None,
                 "purchase_source_raw_file":best["source_raw_file"] if best else None,
                 "full_review_texts":full[p["asin"]],"review_excerpts":excerpts[p["asin"]],
                 "dated_full_review_texts":dated[p["asin"]],"verified_full_review_texts":verified[p["asin"]],
                 "review_status":"full_text_available" if full[p["asin"]] else "excerpts_only" if excerpts[p["asin"]] else "not_collected",
                 "source_url":p["source_url"]}
            linked.append(row); family_rows.append(row)
        summaries.append({"keyword_id":keyword_id,"keyword":family["keyword"],"niche_id":family["niche_id"],
            "peak_months":peaks,"search_history_status":"supported" if supported else "insufficient_history",
            "products_collected":len(matched),"products_with_purchase_evidence":sum(r["purchase_lower_bound"] is not None for r in family_rows),
            "products_with_full_reviews":sum(full[p["asin"]]>0 for p in matched),
            "products_with_any_review_text":sum(full[p["asin"]]+excerpts[p["asin"]]>0 for p in matched),
            "full_review_texts":sum(full[p["asin"]] for p in matched),"review_excerpts":sum(excerpts[p["asin"]] for p in matched),
            "dated_full_review_texts":sum(dated[p["asin"]] for p in matched),"verified_full_review_texts":sum(verified[p["asin"]] for p in matched),
            "coverage_status":"no_products_collected" if not matched else "no_purchase_evidence" if not any(r["purchase_lower_bound"] is not None for r in family_rows) else "evidence_available",
            "scope":"Collected sample only; purchase bands are not summed into market sales"})
    return evidence,linked,summaries
