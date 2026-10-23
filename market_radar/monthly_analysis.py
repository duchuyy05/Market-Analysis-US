"""Selected-month timing linked to current listings, never historical monthly ASIN sales."""
from collections import Counter, defaultdict
from datetime import date
import re
from statistics import mean

from .io import now
from .settings import study_months, month_end, profile_value


TABLES = ("monthly_keyword_analysis", "product_month_opportunities", "listing_evidence",
          "review_month_summary", "review_themes", "monthly_actions")


def timing_profiles(data, settings):
    cutoff = date.fromisoformat(data["as_of_date"])
    months = study_months(data)
    peak_status = "historical_q4_peak" if months == [10, 11, 12] else "historical_period_peak"
    output = []
    for keyword in data["keywords"]:
        monthly = [r for r in data["trends"] if r["keyword_id"]==keyword["keyword_id"]]
        years = []
        for year in data["history_years"]:
            # Include a current-year quarter only when the entire selected period is observed.
            if month_end(year, max(months))>cutoff:
                continue
            rows = sorted((r for r in monthly if r["year"]==year),key=lambda r:r["month"])
            rows = [r for r in rows if r["month"] in months]
            if len(rows)!=len(months) or any(r["observed_days"]!=r["calendar_days"] or r["mean_interest_index"] is None for r in rows):
                continue
            source_points=[p for p in data.get("trends_weekly",[]) if p["keyword_id"]==keyword["keyword_id"]
                and any(p["period_start"]<=month_end(year,m).isoformat() and p["period_end_exclusive"]>date(year,m,1).isoformat() for m in months)]
            positives=sum((p.get("interest_index") or 0)>0 for p in source_points) if source_points else sum(r["positive_source_points"] for r in rows)
            if positives<settings.get("min_positive_week_points_per_period",settings.get("min_positive_week_points_per_q4",3)):
                continue
            peak = max(r["mean_interest_index"] for r in rows)
            if peak<=0:
                continue
            winners = [r["month"] for r in rows if abs(r["mean_interest_index"]-peak)<1e-8]
            if max(r["positive_source_points"] for r in rows if r["month"] in winners)<2:
                continue
            years.append({"year":year,"rows":rows,"peak":peak,"winners":winners})
        supported = len(years)>=settings["min_completed_years_for_timing"]
        for month in months:
            values = [next(r for r in year["rows"] if r["month"]==month)["mean_interest_index"]/year["peak"]*100 for year in years]
            profile = round(mean(values),2) if values else None
            peak_years = [y["year"] for y in years if y["winners"]==[month]]
            previous=mean(next(r for r in year["rows"] if r["month"]==month-1)["mean_interest_index"]/year["peak"]*100 for year in years) if years and month-1 in months else None
            if not supported:
                status = "insufficient_search_history"
            elif len(peak_years)>=settings["min_completed_years_for_timing"] and len(peak_years)/len(years)>=2/3:
                status = peak_status
            elif profile>=settings["ramp_up_profile_threshold_pct"] and previous is not None and profile>=previous*1.2 and profile>previous:
                status = "historical_build_up"
            elif profile>=settings["ramp_up_profile_threshold_pct"]:
                status = "secondary_period"
            else:
                status = "preparation_or_off_peak"
            current = next((r for r in monthly if r["year"]==cutoff.year and r["month"]==month),{})
            source = next((r for r in monthly if r.get("source_url")),{})
            output.append({"keyword_id":keyword["keyword_id"],"keyword":keyword["keyword"],"component_id":keyword["component_id"],
                "month":month,"completed_years_used":[y["year"] for y in years],"completed_year_count":len(years),
                "historical_profile_pct_of_own_period_peak":profile,"peak_years":peak_years,"peak_year_count":len(peak_years),
                "timing_status":status,"timing_supported":supported,
                "current_year":cutoff.year,"current_year_observation_status":current.get("observation_status"),
                "current_year_month_interest_index":current.get("mean_interest_index"),
                "same_period_yoy_change_pct":keyword.get("same_period_yoy_change_pct") if month==cutoff.month else None,
                "source_url":source.get("source_url"),"source_raw_file":source.get("source_raw_file"),
                "as_of_date":data["as_of_date"],"market":data["market"],
                "measure_definition":"Mean of month index / same-keyword same-year selected-period peak * 100; timing shape, not searches, units or market share"})
    return output


def listing_evidence(data):
    products = {p["asin"]:p for p in data["products"]}
    output = []
    for link in data["product_components"]:
        product = products[link["asin"]]
        for field in ("product_name","seller_features","description"):
            body = product.get(field) or ""
            match = re.search(re.escape(link["matched_text"]),body,re.I)
            if not match:
                continue
            start,end = max(0,match.start()-55),min(len(body),match.end()+130)
            output.append({"evidence_id":f"E-{product['asin']}-{link['component_id']}","asin":product["asin"],
                "component_id":link["component_id"],"evidence_type":"product_component_family_mention",
                "matched_text":match[0],"verbatim_quote":body[start:end],"source_field":field,
                "quote_start":start,"quote_end_exclusive":end,"source_url":product["source_url"],
                "source_raw_file":product["source_raw_file"],"observed_at_utc":product["observed_at_utc"],
                "interpretation":"Seller listing mention; not ingredient concentration, medical effect, or proof this component drives sales"})
            break
    return output


def link_product_months(data, profiles, evidence):
    by_component = defaultdict(list)
    for row in profiles:
        by_component[row["component_id"]].append(row)
    by_asin = defaultdict(list)
    for row in evidence:
        by_asin[row["asin"]].append(row)
    rows = []
    priority = {"historical_period_peak":0,"historical_q4_peak":0,"historical_build_up":1,"secondary_period":2,"preparation_or_off_peak":3,
                "insufficient_search_history":4,"no_supported_keyword":5}
    for product in data["products"]:
        text = " ".join(product.get(f) or "" for f in ("product_name","seller_features","description","material"))
        for month in study_months(data):
            links = []
            for quote in by_asin[product["asin"]]:
                for profile in by_component[quote["component_id"]]:
                    if profile["month"]!=month:
                        continue
                    # A generic/heated eye mask is not evidence for a silk sleep mask.
                    if "silk" in profile["keyword"].lower() and not re.search(r"\bsilk\b",text,re.I):
                        continue
                    # Hand cream alone cannot inherit the trend of body lotion gift sets.
                    if profile["component_id"]=="body_lotion" and not re.search(r"\bbody lotion\b",text,re.I):
                        continue
                    exact = profile["keyword"].lower() in text.lower()
                    links.append((profile,quote,"exact_keyword_phrase" if exact else "component_family_proxy"))
            links.sort(key=lambda item:(priority[item[0]["timing_status"]],-(profile_value(item[0]) or 0)))
            best = links[0] if links else None
            status = best[0]["timing_status"] if best else "no_supported_keyword"
            rows.append({"month":month,"asin":product["asin"],"product_name":product["product_name"],"product_group":product["product_group"],
                "timing_status":status,"timing_rank_in_month":None,
                "historical_profile_pct_of_own_period_peak":profile_value(best[0]) if best else None,
                "timing_keyword":best[0]["keyword"] if best else None,"timing_keyword_id":best[0]["keyword_id"] if best else None,
                "historical_years_used":best[0]["completed_years_used"] if best else [],
                "mapping_type":best[2] if best else "unconfirmed",
                "listing_evidence_ids":[item[1]["evidence_id"] for item in links],"linked_keyword_ids":[item[0]["keyword_id"] for item in links],
                "price_usd":product["price_usd"],"current_purchase_badge":product["bought_past_month_text"],
                "current_purchase_band_lower_bound":product["bought_past_month_lower_bound"],"current_sales_signal_rank":product["sales_signal_rank_in_sample"],
                "rating_out_of_5":product["rating_out_of_5"],"review_texts_collected":product["customer_reviews_collected"],
                "current_snapshot_at_utc":product["observed_at_utc"],"source_url":product["source_url"],
                "recommendation_scope":"Month suitability inferred from linked generic keyword history; not observed monthly ASIN sales"})
    for month in study_months(data):
        group = [r for r in rows if r["month"]==month and r["timing_status"] not in ("insufficient_search_history","no_supported_keyword")]
        keys = sorted({(priority[r["timing_status"]],-(profile_value(r) or 0),
                        -(r["current_purchase_band_lower_bound"] or 0)) for r in group})
        for row in group:
            key=(priority[row["timing_status"]],-(profile_value(row) or 0),-(row["current_purchase_band_lower_bound"] or 0))
            row["timing_rank_in_month"]=keys.index(key)+1
    return sorted(rows,key=lambda r:(r["month"],r["timing_rank_in_month"] is None,r["timing_rank_in_month"] or 999,r["asin"]))


def review_tables(data):
    cutoff = date.fromisoformat(data["as_of_date"])
    summary = []
    for year in data["history_years"]:
        for month in study_months(data):
            reviews = [r for r in data["reviews"] if r["review_year"]==year and r["review_month"]==month and r.get("review_date")<=data["as_of_date"]]
            future = date(year,month,1)>cutoff
            summary.append({"year":year,"month":month,"review_texts_in_sample":None if future else len(reviews),
                "unique_asins_in_sample":None if future else len({r["asin"] for r in reviews}),
                "status":"not_yet_observed" if future else "partial_month_sample" if year==cutoff.year and month==cutoff.month else "visible_review_sample",
                "review_ids":[r["review_id"] for r in reviews],"as_of_date":data["as_of_date"],
                "measure_definition":"Review publication dates, not purchase dates; missing reviews are not evidence of no demand"})
    themes = []
    for theme in sorted({r["theme"] for r in data["customer_needs"]}):
        links = [r for r in data["customer_needs"] if r["theme"]==theme]
        ids = sorted({r["review_id"] for r in links})
        themes.append({"theme":theme,"unique_reviews_mentioning":len(ids),"review_sample_denominator":len(data["reviews"]),
            "unique_asins_mentioning":len({r["asin"] for r in links}),"review_ids":ids,
            "classification":"Keyword mention; count is within this visible sample, not market-wide demand or sentiment"})
    return summary,themes


def build_monthly_analysis(data,settings):
    profiles = timing_profiles(data,settings)
    evidence = listing_evidence(data)
    opportunities = link_product_months(data,profiles,evidence)
    review_months,themes = review_tables(data)
    actions=[]
    for month in study_months(data):
        group=[r for r in profiles if r["month"]==month]
        peaks=[r["keyword_id"] for r in group if r["timing_status"] in ("historical_q4_peak","historical_period_peak")]
        buildup=[r["keyword_id"] for r in group if r["timing_status"] in ("historical_build_up","secondary_period")]
        candidates=[r for r in opportunities if r["month"]==month and r["timing_rank_in_month"] is not None]
        actions.append({"month":month,"action_code":"prioritize_observed_historical_peak" if peaks else "build_up_and_test" if buildup else "prepare_and_test_current_demand",
            "historical_peak_keyword_ids":peaks,"build_up_keyword_ids":buildup,"example_asins":[r["asin"] for r in candidates[:5]],
            "basis_years":sorted({y for r in group for y in r["completed_years_used"]}),"as_of_date":data["as_of_date"],
            "future_current_year_month":date(int(data["as_of_date"][:4]),month,1)>date.fromisoformat(data["as_of_date"]),
            "claim_type":"Planning inference from historical keyword shape plus current listing snapshot, not monthly ASIN sales history"})
    return {"schema_version":1,"category":settings["category"],"niche":data["niche"],"market":data["market"],
        "as_of_date":data["as_of_date"],"history_years":data["history_years"],"history_months":study_months(data),"created_at_utc":now(),"settings":settings,
        "monthly_keyword_analysis":profiles,"product_month_opportunities":opportunities,"listing_evidence":evidence,
        "review_month_summary":review_months,"review_themes":themes,"monthly_actions":actions,
        "method_notes":["Historical peak is the peak within the selected months only, not necessarily the annual peak.",
            "Only completely observed selected periods with enough nonzero source points infer month timing.",
            "Index ratios compare timing shape within each keyword/year, not demand size across keywords.",
            "A listing-component link is an explained inference; it is not proof generic search demand caused sales.",
            "Current purchase badges retain their observation dates and are never assigned to future/historical months.",
            "Review dates are publication dates, not verified purchase dates.",
            "Insufficient evidence remains insufficient; the report does not force a different hot item for every month."]}


