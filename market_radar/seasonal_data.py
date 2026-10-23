"""English source tables and an auditable month-by-month seasonal shortlist."""
from collections import Counter
from datetime import date
import csv
import hashlib
import json
import re

from .io import KEYS, load_env, now, save_json
from .normalize import normalize_product, write_csv, purchase_lower_bound, source_review_items, deduplicate_review_rows, number, iso_date
from .web_sources import visible_web_text
from .product_data import clean_text, current_product, rank_current_products, review_needs
from .seasonality import parse_series, monthly_period, period_keyword_summary
from .monthly_analysis import build_monthly_analysis, timing_profiles, link_product_months, listing_evidence, TABLES
from .seasonal import family_match
from .settings import study_months, profile_value, period_label, month_end


SOURCE_TABLES=("products","reviews","keywords","trends","trends_weekly","product_components","keyword_sources","web_sources","excluded_products",
               "amazon_purchase_evidence","keyword_product_evidence","keyword_market_summary")


def monthly_top_five(analysis,settings):
    """A transparent, diversified shortlist within the observed sample, not Amazon's global top five."""
    output=[]
    priority={"historical_period_peak":0,"historical_q4_peak":0,"historical_build_up":1,"secondary_period":2}
    limit=settings.get("top_n",5)
    for month in study_months(settings):
        eligible=[r for r in analysis["product_month_opportunities"] if r["month"]==month
                  and r["current_purchase_band_lower_bound"] is not None
                  and r["timing_status"] in priority and (profile_value(r) or 0)>=settings["ramp_up_profile_threshold_pct"]]
        eligible.sort(key=lambda r:(priority[r["timing_status"]],r["current_purchase_band_lower_bound"] is None,
            -(r["current_purchase_band_lower_bound"] or 0),-(profile_value(r) or 0),r["asin"]))
        selected=[]
        families=set()
        for row in eligible:
            if row["timing_keyword_id"] not in families:
                selected.append(row)
                families.add(row["timing_keyword_id"])
            if len(selected)==limit:
                break
        for row in eligible:
            if len(selected)==limit:
                break
            if row["asin"] not in {r["asin"] for r in selected}:
                selected.append(row)
        for rank,row in enumerate(selected,1):
            output.append({**row,"rank_in_month":rank,
                "ranking_policy":"Require >=2 completely observed selected periods, profile >= threshold and a current purchase badge; peak before build-up, then purchase band and month fit; diversify families; within sample only"})
    return output


def seasonal_review_needs(reviews):
    rows=review_needs(reviews)
    patterns={"battery_or_power":r"\b(batter(?:y|ies)|power|plug|electric)\b",
        "assembly_or_instructions":r"\b(assembl\w*|instructions?|install\w*|setup)\b",
        "adhesion":r"\b(stick|stuck|adhes\w*|cling\w*|peel\w*)\b",
        "appearance_or_color":r"\b(colou?r\w*|bright\w*|pretty|cute|beautiful|look\w*)\b"}
    for review in reviews:
        for theme,pattern in patterns.items():
            match=re.search(pattern,review["review_text"],re.I)
            if match:
                rows.append({"review_id":review["review_id"],"asin":review["asin"],"theme":theme,
                    "evidence_excerpt":review["review_text"][max(0,match.start()-70):match.end()+150],"review_rating":review["rating_out_of_5"],
                    "review_date":review["review_date"],"is_q4_2023_2026":review["is_q4_2023_2026"],
                    "verified_purchase":review["verified_purchase"],"source_url":review["source_url"],
                    "classification_method":"Keyword mention in this review, not sentiment or population demand"})
    selected={r["review_id"]:r.get("is_selected_period",False) for r in reviews}
    for row in rows:
        row["is_selected_period"]=selected[row["review_id"]]
    return rows


def build_seasonal_data(output):
    path=output/"collection.json"
    if not path.exists():
        raise RuntimeError("No collection yet. Run: python -m market_analysis seasonal --phase collect")
    manifest=json.loads(path.read_text(encoding="utf-8"))
    source_errors=list(manifest.get("errors",[]))
    supplement_products=set()
    for run_path in sorted((output/"supplements").glob("*/run.json")):
        supplement=json.loads(run_path.read_text(encoding="utf-8"))
        supplement_products.update(a["asin"] for a in supplement.get("attempts",[]) if a.get("retained_product") is True)
        source_errors.extend({"source":supplement["id"]+"_"+a["asin"]+"_"+a["device"],"error":a["error"]}
                             for a in supplement.get("attempts",[]) if a.get("status")=="failed")
    config=manifest["config"]
    keywords=[{"keyword_id":"K-"+f["id"],"id":f["id"],"keyword":f["keyword"],"name":f["name"],
        "niche_id":f["niche_id"],"demand_scope":"seasonal_product_family","keyword_origin":"Configured product-family seed, measured using Google Trends US",
        "tavily_source_count":0} for f in config["families"]]
    sources=[{**w,"title":clean_text(w["title"]),"snippet":clean_text(w.get("snippet")),"page_content":clean_text(w.get("page_content"))}
             for w in manifest.get("web_sources",[])]
    keyword_sources=[]
    for family,keyword in zip(config["families"],keywords):
        for source in sources:
            text=" ".join(source.get(k) or "" for k in ("title","snippet","page_content"))
            if family_match(text,family):
                match=re.search(family["required_patterns"][-1],text,re.I)
                keyword_sources.append({"keyword_id":keyword["keyword_id"],"source_id":source["source_id"],
                    "evidence_excerpt":text[max(0,match.start()-60):match.end()+170],"source_url":source["source_url"],
                    "observed_at_utc":source["collected_at_utc"],"source_role":"Web context matching the family; not measured demand or sales"})
        keyword["tavily_source_count"]=sum(r["keyword_id"]==keyword["keyword_id"] for r in keyword_sources)
    series=[]
    for family in config["families"]:
        raw_file=manifest["sources"].get("trends_"+family["id"])
        if not raw_file:
            continue
        envelope=json.loads((output/raw_file).read_text(encoding="utf-8"))
        batch={"batch_id":"single_"+family["id"],"terms":[family["keyword"]],"single_term":True,"date":envelope["parameters"]["date"]}
        series.extend(parse_series(envelope,batch,keywords,anchor=""))
    cutoff=date.fromisoformat(config["as_of_date"])
    months=study_months(config)
    monthly=monthly_period(series,keywords,config["years"],cutoff,months)
    keyword_rows=period_keyword_summary(keywords,monthly,cutoff,months,series)
    for row,seed in zip(keyword_rows,keywords):
        row["niche_id"]=seed["niche_id"]
    products=[]; reviews=[]; links=[]; excluded=[]
    families={f["id"]:f for f in config["families"]}
    selected=sorted({a for group in manifest["family_asins"].values() for a in group}|supplement_products)
    for asin in selected:
        candidate=manifest["candidates"][asin]
        raw_file=manifest["sources"].get("product_"+asin)
        if not raw_file:
            continue
        envelope=json.loads((output/raw_file).read_text(encoding="utf-8"))
        base,source_reviews=normalize_product(envelope,candidate,"P-"+asin)
        if not base:
            continue
        product=current_product(base,envelope,candidate)
        text=" ".join(product.get(k) or "" for k in ("product_name","seller_features","description"))
        matched=[fid for fid in candidate["family_ids"] if family_match(product["product_name"],families[fid])]
        if not matched or product["availability_status"]=="unavailable":
            excluded.append({"asin":asin,"product_name":product["product_name"],"reason":"Family not confirmed in own listing or explicitly unavailable","source_raw_file":raw_file})
            continue
        product.update(family_ids=matched,niche_ids=sorted({families[f]["niche_id"] for f in matched}),
            product_group=families[matched[0]]["name"],discovery_channels="amazon_family_search",marketplace="amazon.com",
            language_screen="en_US requested; source text retained in English without generated translation")
        products.append(product)
        for fid in matched:
            pattern=families[fid]["required_patterns"][-1]
            field=next(k for k in ("product_name","seller_features","description") if re.search(pattern,product.get(k) or "",re.I))
            body=product[field]; match=re.search(pattern,body,re.I)
            links.append({"asin":asin,"component_id":fid,"matched_text":match[0],"evidence_excerpt":body[max(0,match.start()-55):match.end()+130],
                "source_field":field,"source_url":product["source_url"],"source_raw_file":raw_file,"observed_at_utc":product["observed_at_utc"],
                "relationship":"Classified into configured seasonal family by own listing text; not observed historical ASIN sales"})
        mobile=manifest["sources"].get("reviews_mobile_"+asin)
        if mobile:
            _,extra=normalize_product(json.loads((output/mobile).read_text(encoding="utf-8")),candidate,product["product_id"])
            source_reviews.extend(extra)
        for path in manifest.get("supplement_sources",{}).get(asin,[]):
            extra_raw=json.loads((output/path).read_text(encoding="utf-8"))
            if extra_raw.get("parameters",{}).get("asin")!=asin:
                raise RuntimeError("Supplement source ASIN mismatch")
            _,extra=normalize_product(extra_raw,candidate,product["product_id"])
            source_reviews.extend(extra)
        for review in source_reviews:
            body=clean_text(review["review_text"])
            if not body or re.search(r"[đĐăĂơƠưƯấầẩẫậắằẳẵặếềểễệốồổỗộớờởỡợứừửữự]",body):
                continue
            day=date.fromisoformat(review["review_date"]) if review.get("review_date") else None
            if day and day>cutoff:
                continue
            reviews.append({"review_id":review["review_evidence_id"],"asin":asin,"review_title":clean_text(review["review_title"]),
                "review_id_kind":review["review_id_kind"],
                "review_text":body,"rating_out_of_5":review["star_rating"],"review_date":review["review_date"],
                "review_text_kind":review.get("review_text_kind","full"),"source_section":review.get("source_section","authors_reviews"),
                "review_year":day.year if day else None,"review_month":day.month if day else None,
                "is_selected_period":bool(day and day.year in config["years"] and day.month in months),
                "is_q4_2023_2026":bool(day and 2023<=day.year<=2026 and day.month in (10,11,12)),
                "verified_purchase":review["verified_purchase"],"variant_text":clean_text("; ".join(f"{k}: {v}" for k,v in (review.get("variant") or {}).items())),
                "helpful_votes_text":review.get("helpful_votes_text"),"is_vine":review.get("is_vine"),
                "reviewer_country_explicit":review["review_country_explicit"],"source_url":review["source_url"],
                "source_raw_file":review["source_raw_file"],"observed_at_utc":review["collected_at_utc"],
                "review_scope":"Visible listing sample may share variants; publication date is not purchase date or proof of US buyer"})
    reviews=deduplicate_review_rows(reviews)
    counts=Counter(r["asin"] for r in reviews)
    full_counts=Counter(r["asin"] for r in reviews if r["review_text_kind"]=="full")
    excerpt_counts=Counter(r["asin"] for r in reviews if r["review_text_kind"]=="excerpt")
    dated_counts=Counter(r["asin"] for r in reviews if r["review_text_kind"]=="full" and r["review_date"])
    verified_counts=Counter(r["asin"] for r in reviews if r["review_text_kind"]=="full" and r["verified_purchase"] is True)
    for product in products:
        product["customer_reviews_collected"]=counts[product["asin"]]
        product["full_reviews_collected"]=full_counts[product["asin"]]
        product["review_excerpts_collected"]=excerpt_counts[product["asin"]]
        product["dated_full_reviews_collected"]=dated_counts[product["asin"]]
        product["verified_full_reviews_collected"]=verified_counts[product["asin"]]
    if not products:
        raise RuntimeError("No verified seasonal product listings; inspect collection errors")
    products=rank_current_products(products)
    data={"schema_version":5,"category":config["category"],"niche":config["category"]+" / "+period_label(months),
        "niches":[{"id":n["id"],"name":n["name"]} for n in config["niches"]],"market":"US","as_of_date":config["as_of_date"],
        "history_years":config["years"],"history_months":config["months"],"built_at_utc":now(),"products":products,"reviews":reviews,
        "keywords":keyword_rows,"trends":monthly,"trends_weekly":[p for p in series if any(p["period_start"]<=month_end(year,m).isoformat() and p["period_end_exclusive"]>date(year,m,1).isoformat() for year in config["years"] for m in months)],
        "product_components":links,"keyword_sources":keyword_sources,"web_sources":sources,"excluded_products":excluded,
        "customer_needs":seasonal_review_needs(reviews),"source_errors":source_errors,
        "limitations":["Google Trends indices measure relative searches, not Amazon traffic or units sold.",
            "Each term uses a separate fixed-window scale. Compare timing within a keyword; do not compare index magnitudes as demand size.",
            "Monthly averages approximate source indices by overlapping days; historical peak is within selected months only.",
            "Future months beyond the as-of date are blank, not zero. A completed current-year period can contribute to timing.",
            "Amazon prices, purchase bands and ratings are current snapshots, not historical monthly ASIN sales.",
            "A top-five list is a transparent shortlist within this limited sample, not Amazon's global top five or a sales forecast.",
            "Review publication month is not verified purchase month. Reviews may share variants and do not establish US demographics.",
            "Full reviews and linked review excerpts are counted separately. Excerpts without date or rating remain undated/unrated; AI summaries are excluded. Records are not necessarily unique customers.",
            "Purchase evidence preserves exact ASIN, source type and observation date. Search-result badges supplement coverage but do not silently replace product-page snapshots or enter Top 5 ranking.",
            "Search sampling is not comprehensive market coverage. Missing review/source data does not imply low demand or low competition.",
            "Configured families are survey seeds, not proof they are hot. No profit estimate is made without costs."]}
    analysis=build_monthly_analysis(data,config)
    analysis["monthly_top5"]=monthly_top_five(analysis,config)
    from .market_evidence import build_market_evidence
    data["amazon_purchase_evidence"],data["keyword_product_evidence"],data["keyword_market_summary"]=build_market_evidence(output,data,analysis,manifest)
    save_json(output/"dataset.json",data)
    for name in SOURCE_TABLES:
        rows=data[name]
        write_csv(output/f"{name}.csv",rows,fields=list(rows[0]) if rows else ["asin","reason","source_raw_file"])
    analysis["input_sha256"]=hashlib.sha256((output/"dataset.json").read_bytes()).hexdigest()
    save_json(output/"monthly-analysis.json",analysis)
    for name in (*TABLES,"monthly_top5"):
        rows=analysis[name]
        write_csv(output/f"{name}.csv",rows,fields=list(rows[0]) if rows else ["month","asin","timing_status"])
    print(json.dumps({"products":len(products),"reviews":len(reviews),"keywords":len(keyword_rows),
        "monthly_top5_counts":dict(Counter(r["month"] for r in analysis["monthly_top5"])),"source_errors":len(source_errors)}))
    return data,analysis


def verify_seasonal_data(output):
    data=json.loads((output/"dataset.json").read_text(encoding="utf-8"))
    analysis=json.loads((output/"monthly-analysis.json").read_text(encoding="utf-8"))
    manifest=json.loads((output/"collection.json").read_text(encoding="utf-8"))
    checks=0
    def require(value,message):
        nonlocal checks
        if not value:
            raise RuntimeError("Seasonal verification failed: "+message)
        checks+=1
    require(data["history_years"]==manifest["config"]["years"],"configured years")
    require(data["history_months"]==study_months(manifest["config"]),"configured months")
    require(analysis["input_sha256"]==hashlib.sha256((output/"dataset.json").read_bytes()).hexdigest(),"analysis belongs to current dataset")
    expected_profiles=timing_profiles(data,manifest["config"])
    expected_evidence=listing_evidence(data)
    require(analysis["monthly_keyword_analysis"]==expected_profiles,"month timing reproducible from observed search series")
    require(analysis["listing_evidence"]==expected_evidence,"listing evidence reproducible")
    require(analysis["product_month_opportunities"]==link_product_months(data,expected_profiles,expected_evidence),"product timing links reproducible")
    products={p["asin"]:p for p in data["products"]}
    for p in products.values():
        raw=json.loads((output/p["source_raw_file"]).read_text(encoding="utf-8"))
        pr=raw["response"]["product_results"]
        require(raw["parameters"]["asin"]==p["asin"],"ASIN provenance")
        require(p["price_usd"]==pr.get("extracted_price"),"price from own snapshot")
        require(p["bought_past_month_text"]==pr.get("bought_last_month"),"purchase badge from own snapshot")
        require(p["bought_past_month_lower_bound"]==purchase_lower_bound(p["bought_past_month_text"]),"badge is a lower-bound band")
        for fid in p["family_ids"]:
            family=next(f for f in manifest["config"]["families"] if f["id"]==fid)
            require(family_match(p["product_name"],family),"family confirmed in own product title")
    for r in data["trends"]:
        require(r["month"] in study_months(data),"only requested months")
        if date(r["year"],r["month"],1)>date.fromisoformat(data["as_of_date"]):
            require(r["mean_interest_index"] is None and r["observed_days"]==0,"future months blank")
    for evidence in analysis["listing_evidence"]:
        p=products[evidence["asin"]]
        require(p[evidence["source_field"]][evidence["quote_start"]:evidence["quote_end_exclusive"]]==evidence["verbatim_quote"],"listing quote exact and source position valid")
    for review in data["reviews"]:
        raw=json.loads((output/review["source_raw_file"]).read_text(encoding="utf-8"))
        require(raw["parameters"]["asin"]==review["asin"],"review ASIN provenance")
        original=source_review_items(raw["response"])
        require(any(clean_text(r.get("text") or r.get("body") or "")==review["review_text"] and r["_kind"]==review.get("review_text_kind","full") for r in original),"review quote and text kind from raw response")
        require(any(clean_text(r.get("text") or r.get("body") or "")==review["review_text"] and r["_kind"]==review.get("review_text_kind","full")
                    and number(r.get("rating"))==review["rating_out_of_5"] and iso_date(r.get("date"))==review["review_date"]
                    and r.get("verified_purchase")==review["verified_purchase"] for r in original),"review date, rating and purchase verification match raw evidence")
    if "amazon_purchase_evidence" in data:
        from .market_evidence import build_market_evidence
        expected=build_market_evidence(output,data,analysis,manifest)
        require(expected==tuple(data[name] for name in ("amazon_purchase_evidence","keyword_product_evidence","keyword_market_summary")),"keyword, ASIN and purchase provenance reproducible")
    require(len({(r["month"],r["asin"]) for r in analysis["monthly_top5"]})==len(analysis["monthly_top5"]),"no duplicate ASIN per month")
    require(analysis["monthly_top5"]==monthly_top_five(analysis,manifest["config"]),"top five reproducible from published ranking rule")
    for row in analysis["product_month_opportunities"]:
        p=products[row["asin"]]
        require(row["current_purchase_badge"]==p["bought_past_month_text"] and row["current_snapshot_at_utc"]==p["observed_at_utc"],"snapshot not reassigned to historical/future months")
        require(all(month_end(y,max(study_months(data)))<=date.fromisoformat(data["as_of_date"]) for y in row["historical_years_used"]),"partial selected periods excluded from preferred-month calculation")
    def encoded(value):
        if isinstance(value,(list,dict)):
            value=json.dumps(value,ensure_ascii=False)
        if isinstance(value,str) and value.lstrip().startswith(("=","+","-","@")):
            value="'"+value
        return "" if value is None else str(value)
    counts={}
    for name in (*SOURCE_TABLES,*TABLES,"monthly_top5"):
        if name in ("amazon_purchase_evidence","keyword_product_evidence","keyword_market_summary") and name not in data:
            continue
        expected=data[name] if name in SOURCE_TABLES else analysis[name]
        with (output/f"{name}.csv").open(encoding="utf-8-sig",newline="") as stream:
            rows=list(csv.DictReader(stream))
        require(len(rows)==len(expected),"CSV row count: "+name)
        require(all(all(row.get(k)==encoded(v) for k,v in original.items()) for row,original in zip(rows,expected)),"CSV cells match JSON: "+name)
        counts[name]=len(rows)
    secrets=[load_env().get(k) for k in KEYS]
    for path in output.rglob("*"):
        if path.is_file() and path.suffix in (".json",".csv",".html",".md"):
            content=path.read_text(encoding="utf-8-sig")
            require(not any(s and s in content for s in secrets),"no credentials in outputs")
    for name in ("report.md","report.html","dashboard.html"):
        require((output/name).exists(),"generated "+name)
    result={"status":"passed","checks":checks,"verified_at_utc":now(),"row_counts":counts,"source_errors":data["source_errors"],
            "scope":"Source/calculation checks, not proof of representative demand or historical ASIN sales"}
    save_json(output/"acceptance.json",result)
    save_json(output/"csv-validation.json",{"status":"passed","verified_at_utc":result["verified_at_utc"],
        "method":"Python csv reader: every CSV row and cell compared against the corresponding JSON table",
        "row_counts":counts})
    print(json.dumps(result,ensure_ascii=True))
    return result
