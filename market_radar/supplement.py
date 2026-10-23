"""Bounded, append-only Amazon probes for existing products; no Trends/Tavily requests."""
from collections import Counter
import json
from pathlib import Path
import re
import secrets
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from .io import Client, load_env, now, save_json
from .normalize import purchase_lower_bound, source_review_items


def supplement_targets(output,manifest,data):
    """Use untried device views, plus one additional nonsponsored ASIN per keyword family."""
    from .seasonal import family_match
    full=Counter(r["asin"] for r in data["reviews"] if r.get("review_text_kind","full")=="full")
    bands={p["asin"]:p.get("bought_past_month_lower_bound") or 0 for p in data["products"]}
    new=[]
    known=set(bands)|{a for group in manifest.get("family_asins",{}).values() for a in group}
    families={f["id"]:f for f in manifest.get("config",{}).get("families",[])}
    for label,path in manifest["sources"].items():
        if not label.startswith("search_"):
            continue
        raw=json.loads((output/path).read_text(encoding="utf-8"))
        items=(raw.get("response") or {}).get("organic_results",[]) or []
        for item in items:
            if item.get("asin") in bands and not item.get("sponsored"):
                bands[item["asin"]]=max(bands[item["asin"]],purchase_lower_bound(item.get("bought_last_month")) or 0)
        fid=label.removeprefix("search_")
        if fid not in families:
            continue
        candidates=[item for item in items if re.fullmatch(r"[A-Z0-9]{10}",item.get("asin", ""))
                    and item["asin"] not in known and not item.get("sponsored")
                    and family_match(item.get("title", ""),families[fid])]
        candidates.sort(key=lambda item:(-(purchase_lower_bound(item.get("bought_last_month")) or 0),-(item.get("reviews") or 0)))
        if candidates:
            item=candidates[0]; known.add(item["asin"])
            new.append({"asin":item["asin"],"device":"desktop","new_product":True,"candidate":{
                "item":item,"search_sources":[path],"search_queries":[raw.get("parameters",{}).get("k")],"family_ids":[fid]}})
    ordered=sorted(data["products"],key=lambda p:(full[p["asin"]]>0,full[p["asin"]],-bands[p["asin"]],p["asin"]))
    first=[]; later=[]
    for p in ordered:
        asin=p["asin"]
        paths=[path for label,path in manifest["sources"].items() if label.endswith("_"+asin)]
        paths+=manifest.get("supplement_sources",{}).get(asin,[])
        used={json.loads((output/path).read_text(encoding="utf-8")).get("parameters",{}).get("device","desktop") for path in paths}
        choices=[{"asin":asin,"device":device,"new_product":False} for device in ("mobile","tablet","desktop") if device not in used]
        if choices:
            first.append(choices[0]); later.extend(choices[1:])
    return first+new+later


def free_searches_left(env):
    key=env.get("SERPAPI_API_KEY")
    if not key:
        raise RuntimeError("Cần SERPAPI_API_KEY trong api/.env")
    try:
        with urlopen("https://serpapi.com/account.json?"+urlencode({"api_key":key}),timeout=30) as response:
            data=json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Không kiểm tra được quota SerpApi: HTTP {error.code}") from None
    except (OSError,ValueError):
        raise RuntimeError("Không kiểm tra được quota SerpApi; chưa gửi yêu cầu bổ sung") from None
    if data.get("plan_monthly_price")!=0:
        raise RuntimeError("Lượt bổ sung này chỉ dùng gói SerpApi miễn phí đã xác minh")
    remaining=data.get("plan_searches_left")
    if type(remaining) is not int or remaining<=0:
        raise RuntimeError("SerpApi đã hết hạn mức miễn phí; không dùng extra credits")
    return remaining


class SupplementRun:
    def __init__(self,output,max_requests=12,event=None,reserve_searches=50):
        if type(max_requests) is not int or not 1<=max_requests<=45:
            raise ValueError("Số lượt bổ sung phải từ 1 đến 45")
        if type(reserve_searches) is not int or reserve_searches<0:
            raise ValueError("Số lượt giữ lại phải là số nguyên không âm")
        self.output=Path(output)
        self.limit=max_requests
        self.reserve=reserve_searches
        self.event=event or (lambda text:print(text,flush=True))

    def collect(self):
        output=self.output
        manifest=json.loads((output/"collection.json").read_text(encoding="utf-8"))
        data=json.loads((output/"dataset.json").read_text(encoding="utf-8"))
        env=load_env()
        available=free_searches_left(env)
        limit=min(self.limit,max(0,available-self.reserve))
        if not limit:
            raise RuntimeError(f"SerpApi còn {available} lượt; đang giữ {self.reserve} lượt cho demo, chưa gọi bổ sung")
        self.event(f"SerpApi còn {available} lượt miễn phí; lần này tối đa {limit} lượt, giữ ít nhất {self.reserve} lượt cho demo")
        targets=supplement_targets(output,manifest,data)
        identifier="supplement-"+now().replace(":","").replace(".","").replace("+","")+"-"+secrets.token_hex(3)
        staging=output/"supplements"/identifier
        client=Client(staging,env,event=self.event)
        client.max_calls["serpapi"]=limit
        history={"id":identifier,"started_at_utc":now(),"max_requests":limit,"reserve_searches":self.reserve,"free_searches_before":available,"attempts":[]}
        manifest.setdefault("supplement_sources",{})
        for p in targets:
            if len(client.calls)>=limit:
                break
            try:
                current_available=free_searches_left(env)
            except RuntimeError as error:
                history["stop_reason"]=str(error)
                self.event("Dừng bổ sung và giữ phần nguồn đã lấy: "+str(error))
                break
            if current_available<=self.reserve:
                history["stop_reason"]="Reserved quota reached"
                self.event("Đã chạm phần quota giữ lại cho demo; dừng bổ sung")
                break
            asin=p["asin"]
            device=p["device"]
            attempt={"asin":asin,"device":device,"new_product":p["new_product"],"started_at_utc":now()}
            self.event(f"Bổ sung {asin}: lấy nhãn mua và nhận xét ({device})")
            try:
                envelope=client.request("serpapi",{"engine":"amazon_product","asin":asin,"amazon_domain":"amazon.com",
                    "language":"en_US","shipping_location":"US","device":device,"output":"json"},cache=False)
                relative=(staging/envelope["raw_file"]).relative_to(output).as_posix()
                envelope["raw_file"]=relative
                save_json(output/relative,envelope)
                if envelope.get("parameters",{}).get("asin")!=asin:
                    raise RuntimeError("ASIN trả về không khớp yêu cầu")
                returned_asin=(envelope.get("response",{}).get("product_results") or {}).get("asin")
                if returned_asin and returned_asin!=asin:
                    raise RuntimeError("Trang sản phẩm trả về ASIN khác; không gộp dữ liệu")
                if p["new_product"]:
                    from .seasonal import family_match
                    pr=envelope["response"].get("product_results") or {}
                    family=next(f for f in manifest["config"]["families"] if f["id"]==p["candidate"]["family_ids"][0])
                    accepted=bool(pr.get("title") and family_match(pr["title"],family) and not re.search(r"currently unavailable|out of stock",pr.get("stock") or "",re.I))
                    attempt["retained_product"]=accepted
                    if accepted:
                        manifest["candidates"][asin]=p["candidate"]
                        manifest["family_asins"].setdefault(family["id"],[]).append(asin)
                        manifest["sources"]["product_"+asin]=relative
                        # New ASINs get an untried mobile view if the budget permits.
                        targets.append({"asin":asin,"device":"mobile","new_product":False})
                else:
                    manifest["supplement_sources"].setdefault(asin,[]).append(relative)
                reviews=source_review_items(envelope["response"])
                attempt["full_texts_returned"]=sum(r["_kind"]=="full" for r in reviews)
                attempt["excerpts_returned"]=sum(r["_kind"]=="excerpt" for r in reviews)
                attempt.update(status="received",source_raw_file=relative)
                self.event(f"Nguồn trả: {attempt['full_texts_returned']} nhận xét đầy đủ, {attempt['excerpts_returned']} trích đoạn; sẽ lọc trùng khi chuẩn hóa")
            except RuntimeError as error:
                attempt.update(status="failed",error=str(error))
                self.event("Chưa lấy thêm được "+asin+": "+str(error))
            history["attempts"].append(attempt)
            manifest.setdefault("request_history",[]).extend(client.calls[-1:])
            save_json(output/"collection.json",manifest)
            save_json(staging/"run.json",history)
            if attempt.get("error","").startswith("HTTP 429") or "Network/timeout" in attempt.get("error",""):
                break
        history.update(finished_at_utc=now(),requests_made=len(client.calls))
        save_json(staging/"run.json",history)
        return history


def run_supplement(output,max_requests=12,use_llm=False,event=None,reserve_searches=50):
    from .seasonal_data import build_seasonal_data,verify_seasonal_data
    from .seasonal_report import generate_report
    result=SupplementRun(output,max_requests,event,reserve_searches).collect()
    build_seasonal_data(output)
    if use_llm:
        from .study import write_insights
        try:
            write_insights(output,event or print)
        except (RuntimeError,ValueError) as error:
            result["llm_warning"]=str(error)
            (event or print)("AI chưa viết được phần mới: "+str(error))
    generate_report(output)
    verify_seasonal_data(output)
    return result
