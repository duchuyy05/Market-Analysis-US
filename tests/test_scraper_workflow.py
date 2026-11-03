"""Direct product collectors preserve scope, evidence and missing metrics."""
import hashlib
from datetime import date,datetime,timedelta,timezone

import pytest

from market_research.config import validate_config
from market_research.pipeline import execute
from market_research.providers.client import Client
from market_research.scraping import AmazonScraper,EtsyScraper,RedditScraper
from market_research.storage.run import Run
from market_research.workflow.scraped_products import Collector


def config(**change):
    return validate_config({"brief":"Tìm hình mèo trên móc khóa và áo in hoa theo tháng 11", "as_of_date":"2026-11-03",
        "selling_months":[11],"history_years":[2023,2024,2025],"product_collection":{"mode":"scraper","detail_limit":1},
        "niches":[{"name":"Móc khóa","seeds":["cat keychain"]},{"name":"Áo","seeds":["sunflower shirt"]}],
        "sources":{"trends":True,"web":False},"llm":{"enabled":False},
        "trends":{"provider":"free","history_scope":"seasonal","history_months":[11],"analysis_year":2025},
        "limits":{"candidate_keywords":2,"top_keywords":2,"monthly_keywords":2,"related_seeds_per_niche":0,"serpapi_requests":0,"trends_serpapi_requests":0,"free_trends_requests":20,"retry_attempts":0},**change})


def test_amazon_keeps_actual_currency_and_does_not_turn_large_usd_prices_into_vnd():
    scraper=AmazonScraper()
    for text,expected,currency in [("$1,299.99",1299.99,"USD"),("₫250,000",250000,"VND"),("€12,50",12.5,"EUR")]:
        rows=scraper._parse_amazon_html(f'<div data-component-type="s-search-result" data-asin="B012345678"><h2>Cat keychain</h2><span class="a-price"><span class="a-offscreen">{text}</span></span></div>',5)
        assert rows[0]["price"]==expected and rows[0]["currency"]==currency
        assert rows[0]["rating"] is rows[0]["review_count"] is rows[0]["sales_count"] is None
    assert scraper._parse_sales_volume("1,000+ bought in past month")==1000


def test_etsy_requires_real_listing_deduplicates_nested_cards_and_never_invents_rating_or_sales():
    body='''<div data-listing-id="123"><a class="listing-link" href="/listing/123/cat"><h3>Cat keychain</h3><img src="https://i.etsystatic.com/cat.jpg"></a><span>€<span class="currency-value">12.50</span></span><span>In 20+ carts</span></div>'''
    rows=EtsyScraper()._parse_etsy_html(body,5)
    assert len(rows)==1 and rows[0]["link"]=="https://www.etsy.com/listing/123"
    assert rows[0]["rating"] is rows[0]["sales_count"] is None
    assert rows[0]["cart_count"]==20 and rows[0]["currency"]=="EUR"
    assert EtsyScraper()._parse_etsy_html('<a href="/market/cat"><h3>Cat keychain</h3></a>',5)==[]


@pytest.mark.parametrize("source",[AmazonScraper,EtsyScraper,RedditScraper])
def test_challenges_stop_without_retry_and_are_not_empty_product_results(source):
    scraper=source(retries=3)
    calls=[]
    class Response:
        status_code=200
        text='<script>triggerInterstitialChallenge();</script>'
    scraper.session.get=lambda *a,**kw:calls.append(a) or Response()
    assert scraper.search("cat keychain")==[] and len(calls)==1
    assert scraper.last_status["status"]=="blocked"


def test_blocked_source_stops_other_keywords_and_cache_reuses_results_without_http(tmp_path):
    cfg=config()
    run=Run("collect",tmp_path)
    calls=[]
    def transport(provider,params):
        calls.append(params)
        return {"rows":[],"status":{"status":"blocked","reason":"HTTP 403"}}
    collector=Collector(run,Client(run,cfg,transport),cfg)
    collector.fetch("etsy","cat keychain");collector.fetch("etsy","sunflower shirt")
    assert len(calls)==1
    other=Run("cache-first",tmp_path)
    client=Client(other,cfg,lambda *_:{"rows":[{"title":"cat keychain"}],"status":{"status":"available"}})
    Collector(other,client,cfg).fetch("amazon","cat keychain")
    cfg["limits"]["scraper_requests"]=0
    last=Run("cache-second",tmp_path)
    response=Collector(last,Client(last,cfg,lambda *_:pytest.fail("Cache called HTTP")),cfg).fetch("amazon","cat keychain")
    assert response["cached"] and not last.manifest["usage"]


def test_reddit_is_discussion_not_a_product_review_or_purchase_signal():
    rows=RedditScraper()._parse_reddit_json({"data":{"children":[{"data":{"id":"p","title":"Cat keychain printing","permalink":"/r/crafts/comments/p/x","score":10,"num_comments":3,"selftext":"A discussion"}}]}},"cat keychain")
    assert rows[0]["kind"]=="discussion"
    assert rows[0]["rating"] is rows[0]["sales_count"] is None


def test_direct_mode_releases_only_product_reserve_without_raising_api_caps():
    cfg=config(limits={"serpapi_requests":8,"trends_serpapi_requests":8,"serpapi_product_reserve":8})
    assert cfg["limits"]["serpapi_product_reserve"]==0
    assert cfg["limits"]["serpapi_requests"]==cfg["limits"]["trends_serpapi_requests"]==8


def test_direct_tools_and_free_trends_produce_report_without_any_product_api(tmp_path):
    calls=[];names={}
    def transport(provider,params):
        calls.append(provider)
        if provider=="public_scraper":
            source,query=params["source"],params["query"]
            if params["detail"]:
                return {"rows":[{"title":names[query],"description":"Observed printed design","reviews":[{"id":"R","text":"Cute design and clear print","rating":4}]}]}
            if source=="reddit":
                return {"rows":[{"title":query+" discussion","link":"https://www.reddit.com/r/crafts/comments/p/print","snippet":"Public discussion","score":10,"num_comments":2,"kind":"discussion","published_at":"2025-11-02T00:00:00Z"}]}
            key="B0"+hashlib.sha256(query.encode()).hexdigest()[:8].upper() if source=="amazon" else str(int(hashlib.sha256(query.encode()).hexdigest()[:8],16))
            names[key]=query
            return {"rows":[{"id":key,"source":source,"title":query,"price":12,"currency":"USD" if source=="amazon" else "EUR","rating":None,"review_count":None,"bought_label":"100+ bought in past month" if source=="amazon" else None,"cart_count":20 if source=="etsy" else None,"sponsored":False,"link":("https://www.amazon.com/dp/" if source=="amazon" else "https://www.etsy.com/listing/")+key}]}
        assert provider=="google_trends_free"
        if params["endpoint"]=="explore":
            return {"widgets":[{"id":"TIMESERIES","token":"public","request":params["req"]}]}
        items=params["req"]["comparisonItem"]
        start,end=map(date.fromisoformat,items[0]["time"].split());points=[]
        while start<=end:
            points.append({"time":str(int(datetime.combine(start,datetime.min.time(),timezone.utc).timestamp())),"value":[20 if item["keyword"]=="gift basket" else 60 for item in items]})
            start+=timedelta(days=1)
        return {"default":{"timelineData":points}}
    run=execute(config(),run_id="direct-workflow",root=tmp_path,transport=transport,event=lambda _:None)
    data=run.load_dataset()
    assert run.manifest["status"] in {"complete","partial"}
    assert len(data["products"])==4 and len(data["discussions"])==2 and len(data["reviews"])==1
    assert set(calls)=={"public_scraper","google_trends_free"}
    assert all(p["purchase_lower_bound"] is None and p["cart_count"]==20 for p in data["products"] if p["source"]=="etsy")
    assert (run.output/"tables/discussions.csv").is_file()
    assert "Thảo luận Reddit" in (run.output/"report.md").read_text(encoding="utf-8")
