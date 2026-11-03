"""Public collectors adapted to the existing evidence/product/report contract."""
import re
import time
from datetime import datetime, timezone

from ..common import identity, now, read_json, write_json, safe_url
from ..control import check_cancel
from ..scraping import AmazonScraper, EtsyScraper, RedditScraper
from ..analysis.products import candidate, relevant


class Collector:
    def __init__(self, run, client, config):
        self.run, self.client, self.config = run, client, config
        self.blocked, self.instances = {}, {}
        self.last_request = 0

    def fetch(self, source, query, detail=False):
        check_cancel(self.client.cancel_event)
        key = identity("scrape", 3, source, query, detail, None if detail else self.config["limits"]["products_per_direction"])
        path = self.run.path/"raw/scrapers"/(key+".json")
        shared = self.run.root/"data/cache/scrapers"/(key+".json")
        previous = read_json(path) or read_json(shared)
        hours = self.config["product_collection"]["cache_hours"]
        if previous and previous.get("status", {}).get("status") in {"available", "empty"}:
            age = (datetime.now(timezone.utc)-datetime.fromisoformat(previous["retrieved_at"])).total_seconds()
            if path.exists() or (hours and 0 <= age < hours*3600):
                previous.update(raw_file=str(path.relative_to(self.run.path)).replace("\\","/"), cached=True)
                previous["status"]={**previous["status"],"requests":0,"cached":True}
                write_json(path,previous)
                self.run.log("search", "scraper_cache_hit", "Dùng lại dữ liệu cào đã lưu; không HTTP mới", source=source, query=query)
                return previous
        used = sum(u["provider"] == "public_scraper" for u in self.run.manifest["usage"])
        if source in self.blocked or used >= self.config["limits"]["scraper_requests"] or time.monotonic()-self.client.started > self.config["limits"]["max_run_seconds"]:
            return {"rows": [], "status": {"source":source,"status":"blocked" if source in self.blocked else "limited","reason":self.blocked.get(source,"Hết trần HTTP lấy sản phẩm")}, "retrieved_at":now(), "raw_file":None}
        event = {"provider":"public_scraper","engine":source,"purpose":"product_detail" if detail else "product_search","requested_at":now(),"cost_usd":0,"status":"started"}
        self.run.manifest["usage"].append(event)
        self.run.save()
        self.run.log("enrich" if detail else "search", "scraper_request", "Lấy trang công khai không dùng API key", source=source,query=query)
        if time.monotonic()-self.last_request < 1:
            if self.client.cancel_event:
                self.client.cancel_event.wait(1)
            else:
                time.sleep(1)
        check_cancel(self.client.cancel_event)
        classes={"amazon":AmazonScraper,"etsy":EtsyScraper,"reddit":RedditScraper}
        if source not in self.instances:
            self.instances[source]=classes[source](timeout=min(20,self.config["limits"]["timeout_seconds"]),retries=1,cancel=lambda:check_cancel(self.client.cancel_event))
        scraper=self.instances[source]
        # Transport is a test seam, never a second production data provider.
        if self.client.transport:
            fixture=self.client.transport("public_scraper",{"source":source,"query":query,"detail":detail})
            rows=fixture.get("rows",[])
            status=fixture.get("status",{"status":"available" if rows else "empty","source":source})
            snapshot=fixture.get("html")
        else:
            rows=scraper.detail(query) if detail else scraper.search(query,limit=self.config["limits"]["products_per_direction"])
            status,snapshot=scraper.last_status,scraper.raw_snapshot
        self.last_request=time.monotonic()
        result={"provider":"public_scraper","source":source,"query":query,"rows":rows,"status":status,"snapshot":snapshot,
            "retrieved_at":now(),"raw_file":str(path.relative_to(self.run.path)).replace("\\","/")}
        write_json(path,result)
        event["status"]=status.get("status","unavailable")
        self.run.save()
        self.run.log("search","scraper_response",status.get("reason") or "Đã đọc dữ liệu trang",source=source,count=len(rows),status=status.get("status"),http_status=status.get("http_status"),raw_file=result["raw_file"])
        if status.get("status") in {"blocked","unavailable"}:
            self.blocked[source]=status.get("reason","Nguồn chưa dùng được")
        else:
            write_json(shared,result)
        check_cancel(self.client.cancel_event)
        return result


def collect(run,client,config,directions):
    collector=Collector(run,client,config)
    client.product_collector=collector
    occurrences,statuses,discussions=[],[],[]
    for direction in directions:
        for source in config["product_collection"]["sources"]:
            envelope=collector.fetch(source,direction["search_query"])
            status={**envelope["status"],"direction_id":direction["id"],"source":source,"collection_method":"public_http","raw_file":envelope.get("raw_file"),"count":len(envelope["rows"])}
            statuses.append(status)
            for item in envelope["rows"]:
                if source == "reddit":
                    if not safe_url(item.get("link")) or not set(re.findall(r"[a-z]+",direction["keyword"].lower())) & set(re.findall(r"[a-z]+",item.get("title", "").lower())):
                        continue
                    if item.get("published_at") and item["published_at"][:10] > config["as_of_date"]:
                        continue
                    eid=run.add_evidence("reddit_discussion",item["link"],envelope["retrieved_at"],envelope["raw_file"],item.get("snippet") or item["title"],scope="public_discussion_not_verified_customer_review")
                    discussions.append({**item,"id":identity("discussion",item["link"]),"direction_id":direction["id"],"evidence_ids":[eid],"observed_at":envelope["retrieved_at"],"scope":"discussion_not_sales_or_verified_review"})
                    continue
                normalized={"title":item.get("title"),"asin":item.get("id") if source=="amazon" else None,"link":item.get("link"),
                    "extracted_price":item.get("price"),"currency":item.get("currency"),"rating":item.get("rating"),"reviews":item.get("review_count"),
                    "thumbnail":item.get("image"),"bought_last_month":item.get("bought_label") if source=="amazon" else None,
                    "sponsored":item.get("sponsored"),"source":source}
                row=candidate(normalized,"amazon" if source=="amazon" else "shopping",direction,envelope,run)
                if row:
                    row.update(source=source,collection_method="public_http",detail_status="scraped_search",rating_scope=item.get("rating_scope"),
                        currency=item.get("currency"),cart_count=item.get("cart_count"),cart_scope="listing_cart_interest_not_sales" if item.get("cart_count") is not None else None,
                        search_query=direction["search_query"],occurrence_id=identity("S",row["listing_id"],direction["id"],"scraper"))
                    design=direction.get("source_design") or {}
                    row["relevant"]=relevant(row["title"],direction["keyword"],subject=design.get("subject"),kind=design.get("kind"))
                    occurrences.append(row)
    return occurrences,statuses,discussions


def enrich(run,client,config,collected):
    collector=getattr(client,"product_collector",None) or Collector(run,client,config)
    count=0
    for product in collected["products"]:
        if product.get("collection_method")!="public_http" or not product.get("asin") or count>=config["product_collection"]["detail_limit"]:
            continue
        if product["source"] in collector.blocked:
            continue
        result=collector.fetch("amazon",product["asin"],detail=True)
        count+=1
        if not result["rows"]:
            continue
        item=result["rows"][0]
        eid=run.add_evidence("scraped_product_detail",product["url"],result["retrieved_at"],result["raw_file"],item.get("description") or item["title"])
        product.update(title=item["title"],description=item.get("description", ""),detail_status="available",evidence_ids=sorted(set(product["evidence_ids"])|{eid}))
        for review in item.get("reviews",[]):
            rid=identity("R",product["product_id"],review.get("id"),review["text"])
            collected["reviews"].append({"id":rid,"product_id":product["product_id"],"text":review["text"],"rating":review.get("rating"),"date":None,
                "kind":"excerpt","title":"","source":"amazon_public_page","evidence_ids":[eid],"verified_purchase":None})
    return collected
