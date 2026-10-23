"""Bounded seasonal API collection. Raw responses remain the audit source."""
from collections import Counter
from datetime import date
import json
import re

from .io import ROOT, Client, load_env, now, save_json
from .web_sources import web_records
from .settings import validate_config


DEFAULT_OUTPUT = "data/seasonal-gifts-us"


def family_match(text,family):
    return all(re.search(pattern,text,re.I) for pattern in family["required_patterns"])


class SeasonalRun:
    def __init__(self,output,config=None,config_path=None,event=None,fresh=False):
        self.output=output
        self.config=validate_config(config if config is not None else json.loads((config_path or ROOT/"config/seasonal.json").read_text(encoding="utf-8-sig")))
        self.event=event or (lambda message: print(message,flush=True))
        self.path=output/"collection.json"
        if self.path.exists():
            self.manifest=json.loads(self.path.read_text(encoding="utf-8"))
            if fresh:
                raise RuntimeError("--fresh cần thư mục --output mới để giữ nguyên nguồn cũ")
            if validate_config(self.manifest["config"])!=self.config:
                raise RuntimeError("Seasonal config changed; use a new --output folder")
        else:
            self.manifest={"schema_version":3,"config":self.config,"sources":{},"errors":[],"request_history":[],
                           "candidates":{},"family_asins":{},"review_probes":[],"started_at_utc":now()}
        self.manifest["config"]=self.config
        self.client=Client(output,load_env(),event=self.event)
        self.client.reuse_cache=not fresh
        self.client.max_calls.update(serpapi=self.config["max_serpapi_requests"],tavily=self.config["max_tavily_requests"])

    def save(self):
        save_json(self.path,self.manifest)

    def call(self,label,provider,parameters):
        self.event("Nguồn: "+label)
        before=len(self.client.calls)
        try:
            result=self.client.request(provider,parameters)
            self.manifest["sources"][label]=result["raw_file"]
            self.manifest["errors"]=[e for e in self.manifest["errors"] if e["source"]!=label]
            return result
        except RuntimeError as error:
            self.manifest["errors"]=[e for e in self.manifest["errors"] if e["source"]!=label]
            self.manifest["errors"].append({"source":label,"error":str(error)})
            if "Network/timeout" in str(error) or "budget" in str(error):
                raise
            self.event(f"Unavailable {label}: {error}")
            return None
        finally:
            self.manifest["request_history"].extend(self.client.calls[before:])
            self.save()

    def collect(self):
        for niche in self.config["niches"]:
            self.call("tavily_"+niche["id"],"tavily",{"query":niche["discovery_query"],"search_depth":"basic",
                "topic":"general","max_results":8,"country":"united states","language":"en","filter_by_language":True,
                "include_answer":False,"include_raw_content":"markdown","include_usage":True,"include_published_date":True})
        self.manifest["web_sources"]=web_records(self.output,self.manifest)
        self.save()
        for family in self.config["families"]:
            # Separate fixed-window series retain small keywords' seasonality.
            self.call("trends_"+family["id"],"serpapi",{"engine":"google_trends","q":family["keyword"],"geo":"US","hl":"en",
                "date":f"{min(self.config['years'])}-01-01 {self.config['as_of_date']}","data_type":"TIMESERIES","tz":0})
            query=self.manifest.get("query_overrides",{}).get(family["id"],family["amazon_query"])
            source=self.call("search_"+family["id"],"serpapi",{"engine":"amazon","k":query,
                "amazon_domain":"amazon.com","language":"en_US","shipping_location":"US","s":"exact-aware-popularity-rank","output":"json"})
            if not source and query!=family["keyword"]:
                self.manifest.setdefault("query_overrides",{})[family["id"]]=family["keyword"]
                source=self.call("search_"+family["id"],"serpapi",{"engine":"amazon","k":family["keyword"],
                    "amazon_domain":"amazon.com","language":"en_US","shipping_location":"US","s":"exact-aware-popularity-rank","output":"json"})
            if not source:
                continue
            items=[]
            for item in source["response"].get("organic_results",[]):
                asin=item.get("asin","")
                title=item.get("title","")
                if not re.fullmatch(r"[A-Z0-9]{10}",asin) or item.get("sponsored") or not family_match(title,family):
                    continue
                items.append(item)
            # A search-card badge is used only to select a sample. Final measures
            # are taken from the product response, with their own observation time.
            from .normalize import purchase_lower_bound
            items.sort(key=lambda p:-(purchase_lower_bound(p.get("bought_last_month")) or 0))
            chosen=[]
            for item in items[:max(4,self.config["products_per_family"]*3)]:
                asin=item["asin"]
                candidate=self.manifest["candidates"].setdefault(asin,{"item":item,"search_sources":[],"search_queries":[],"family_ids":[]})
                if family["id"] not in candidate["family_ids"]:
                    candidate["family_ids"].append(family["id"])
                    candidate["search_sources"].append(source["raw_file"])
                    candidate["search_queries"].append(family["amazon_query"])
                self.save()
                detail=self.call("product_"+asin,"serpapi",{"engine":"amazon_product","asin":asin,"amazon_domain":"amazon.com",
                    "language":"en_US","shipping_location":"US","output":"json"})
                if detail and detail["response"].get("product_results",{}).get("title"):
                    chosen.append(asin)
                if len(chosen)>=self.config["products_per_family"]:
                    break
            self.manifest["family_asins"][family["id"]]=chosen
            self.save()
        missing=[]
        for asin in sorted({a for group in self.manifest["family_asins"].values() for a in group}):
            path=self.manifest["sources"].get("product_"+asin)
            if not path or asin in self.manifest["review_probes"]:
                continue
            response=json.loads((self.output/path).read_text(encoding="utf-8"))["response"]
            if not (response.get("reviews_information") or {}).get("authors_reviews"):
                missing.append(((response.get("product_results") or {}).get("reviews") or 0,asin))
        limit=max(0,self.config["max_mobile_review_requests"]-len(self.manifest["review_probes"]))
        for _,asin in sorted(missing,reverse=True)[:limit]:
            self.manifest["review_probes"].append(asin)
            self.save()
            self.call("reviews_mobile_"+asin,"serpapi",{"engine":"amazon_product","asin":asin,"device":"mobile",
                "amazon_domain":"amazon.com","language":"en_US","shipping_location":"US","output":"json"})


def run_seasonal(output,phase,config_path=None,fresh=False):
    if phase in ("collect","all"):
        SeasonalRun(output,config_path=config_path,fresh=fresh).collect()
    if phase in ("build","all"):
        from .seasonal_data import build_seasonal_data
        build_seasonal_data(output)
    if phase in ("report","build","all"):
        from .seasonal_report import generate_report
        generate_report(output)
    if phase in ("verify","report","build","all"):
        from .seasonal_data import verify_seasonal_data
        verify_seasonal_data(output)
