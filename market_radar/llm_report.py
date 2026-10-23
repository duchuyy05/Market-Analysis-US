"""Source-linked LLM interpretations for the combined Python report."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import time

from .io import ROOT, Client, KEYS, load_env, now, save_json, scrub
from .study import select_review_evidence

PROMPT_PATH=ROOT/"market_radar/prompts/report_vi.md"
KINDS={"observations":"Điều quan sát được", "reviews":"Phản hồi trong mẫu",
       "recommendations":"Đề xuất để kiểm chứng", "gaps":"Dữ liệu còn thiếu"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def paragraph_digest(item):
    return hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True).encode("utf-8")).hexdigest()


def evidence_pack(output):
    data=json.loads((output/"dataset.json").read_text(encoding="utf-8"))
    analysis=json.loads((output/"monthly-analysis.json").read_text(encoding="utf-8"))
    if analysis.get("input_sha256")!=digest(output/"dataset.json"):
        raise RuntimeError("Phân tích không khớp dataset; chạy demo trước khi gọi LLM")
    config=json.loads((output/"collection.json").read_text(encoding="utf-8"))["config"]
    cards={}; by_asin={}
    families={f["id"]:f for f in config["families"]}
    for i,p in enumerate(data["products"],1):
        identifier=f"P{i:02d}"; by_asin[p["asin"]]=identifier
        cards[identifier]={"id":identifier,"type":"product","asin":p["asin"],"name":p["product_name"],
            "family_ids":p["family_ids"],"niche_ids":p["niche_ids"],
            "family_names":[families[f].get("name_vi",families[f]["name"]) for f in p["family_ids"]],
            "price_usd":p.get("price_usd"),"purchase_badge":p.get("bought_past_month_text"),
            "observed_at_utc":p.get("observed_at_utc"),"full_reviews":p.get("full_reviews_collected",0),
            "review_excerpts":p.get("review_excerpts_collected",0),
            "attributes":{k:p[k] for k in ("color","size","material","scent","included_components_explicit") if p.get(k)},
            "description":(p.get("seller_features") or p.get("description") or "")[:600],
            "source_id":p["asin"],"source_url":p["source_url"]}
    for i,f in enumerate(config["families"],1):
        identifier=f"T{i:02d}"
        timings=[r for r in analysis["monthly_keyword_analysis"] if r["keyword_id"]=="K-"+f["id"]]
        cards[identifier]={"id":identifier,"type":"timing","family_id":f["id"],"niche_ids":[f["niche_id"]],
            "name":f.get("name_vi",f["name"]),"keyword":f["keyword"],
            "months":[{k:r.get(k) for k in ("month","timing_status","completed_year_count","peak_year_count","historical_profile_pct_of_own_period_peak")} for r in timings],
            "source_id":"K-"+f["id"],"source_url":next((r["source_url"] for r in data["trends"] if r["keyword_id"]=="K-"+f["id"]),None)}
    products={p["asin"]:p for p in data["products"]}
    for i,r in enumerate(select_review_evidence(data,limit=64),1):
        identifier=f"R{i:02d}"; p=products[r["asin"]]
        cards[identifier]={"id":identifier,"type":"review","asin":r["asin"],"product_id":by_asin[r["asin"]],
            "family_ids":p["family_ids"],"niche_ids":p["niche_ids"],"product_name":p["product_name"],
            "text":r["review_text"][:900],"text_kind":r.get("review_text_kind","full"),
            "rating":r.get("rating_out_of_5"),"date":r.get("review_date"),"verified_purchase":r.get("verified_purchase"),
            "variant":r.get("variant_text"),"country_explicit":r.get("reviewer_country_explicit"),
            "source_id":r["review_id"],"source_url":r["source_url"]}
    web={s["source_id"]:s for s in data.get("web_sources",[])}
    for i,s in enumerate(list(web.values())[:12],1):
        fids={r["keyword_id"].removeprefix("K-") for r in data.get("keyword_sources",[]) if r["source_id"]==s["source_id"]}
        if not fids:
            continue
        identifier=f"W{i:02d}"
        cards[identifier]={"id":identifier,"type":"web_context","niche_ids":sorted({families[f]["niche_id"] for f in fids if f in families}),
            "title":s["title"],"text":(s.get("snippet") or "")[:350],"source_id":s["source_id"],"source_url":s["source_url"]}
    scope={"category":data["category"],"market":data["market"],"as_of_date":data["as_of_date"],
        "months":data["history_months"],"years":data["history_years"],"product_count":len(data["products"]),
        "full_reviews":sum(r.get("review_text_kind","full")=="full" for r in data["reviews"]),
        "review_excerpts":sum(r.get("review_text_kind")=="excerpt" for r in data["reviews"]),
        "review_sampling":"At most two selected records per product, contrasting ratings when available; not representative of customer sentiment",
        "limits":data["limitations"]}
    tasks=[{"id":n["id"],"title":n.get("name_vi",n["name"]),"scope":scope,
            "evidence":{key:value for key,value in cards.items() if n["id"] in value["niche_ids"]}}
           for n in config["niches"]]
    return {"scope":scope,"evidence":cards,"tasks":tasks,"input_sha256":digest(output/"dataset.json")}


def validate_paragraph(item,cards):
    errors=[]
    if not isinstance(item,dict):
        return ["Đoạn không phải object JSON"]
    text=item.get("text"); ids=item.get("evidence_ids"); kind=item.get("section")
    if not isinstance(text,str) or not 40<=len(text)<=1600:
        errors.append("Nội dung phải từ 40 đến 1600 ký tự")
    elif re.search(r"\d|https?://|<[^>]*>|\[[^\]]*\]\(",text):
        errors.append("Text chứa chữ số, URL hoặc HTML; số liệu được giữ trong phụ lục nguồn")
    if not isinstance(kind,str) or kind not in KINDS:
        errors.append("Loại đoạn không hợp lệ")
    if not isinstance(ids,list) or not 1<=len(ids)<=3 or any(not isinstance(i,str) or i not in cards for i in ids):
        errors.append("Cần một đến ba mã ngắn có thật trong evidence")
        return errors
    types={cards[i]["type"] for i in ids}
    if kind=="reviews" and "review" not in types:
        errors.append("Nhận định review phải dẫn mã R")
    if kind=="observations" and not types&{"product","timing"}:
        errors.append("Nhận định sản phẩm/mùa vụ phải dẫn P hoặc T")
    if kind=="recommendations" and not types&{"product","review"}:
        errors.append("Đề xuất phải dẫn P hoặc R")
    reviews=[cards[i] for i in ids if cards[i]["type"]=="review"]
    products=[cards[i] for i in ids if cards[i]["type"]=="product"]
    if not reviews and item.get("quote") is not None:
        errors.append("Quote chỉ được dùng khi dẫn review R")
    if reviews:
        quote=item.get("quote")
        if not isinstance(quote,dict) or quote.get("id") not in ids or cards[quote["id"]]["type"]!="review":
            errors.append("Thiếu quote dẫn đúng review đang dùng")
        elif not isinstance(quote.get("text"),str) or not 18<=len(quote["text"])<=300:
            errors.append("Trích dẫn review phải từ 18 đến 300 ký tự")
        elif " ".join(quote["text"].split()) not in " ".join(cards[quote["id"]]["text"].split()):
            errors.append("Trích dẫn không khớp nguyên văn nguồn")
        if products and any(r["asin"] not in {p["asin"] for p in products} for r in reviews):
            errors.append("Review và sản phẩm dẫn kèm không cùng ASIN")
    timing={cards[i]["family_id"] for i in ids if cards[i]["type"]=="timing"}
    if timing and any(not timing.intersection(c.get("family_ids",[])) for c in products+reviews):
        errors.append("Nhóm Trends không khớp sản phẩm/review được dẫn")
    return errors


def parse_answer(envelope):
    try:
        choice=envelope["response"]["choices"][0]
        content=choice["message"]["content"]
        if not content and choice.get("finish_reason")=="length":
            raise RuntimeError("Model hết ngân sách token đầu ra trước khi trả nội dung báo cáo")
        body=re.sub(r"^```(?:json)?\s*|\s*```$","",content.strip())
        result=json.loads(body)
        if not isinstance(result,dict) or not isinstance(result.get("paragraphs"),list):
            raise ValueError()
        return result["paragraphs"][:8]
    except (KeyError,IndexError,AttributeError,TypeError,ValueError):
        raise RuntimeError("Model không trả JSON paragraphs hợp lệ") from None


def request_payload(task):
    """Long source IDs/URLs stay in the registry; the model only sees short IDs."""
    keep={"product":("id","type","name","family_names","price_usd","purchase_badge","observed_at_utc","full_reviews","review_excerpts","attributes","description"),
          "review":("id","type","product_id","text","text_kind","rating","date","verified_purchase","variant","country_explicit"),
          "timing":("id","type","name","keyword","months"),"web_context":("id","type","title","text")}
    payload={k:v for k,v in task.items() if k not in {"scope","evidence"}}
    payload["scope"]={k:task["scope"][k] for k in ("category","market","as_of_date","months","years","review_sampling")}
    payload["evidence"]={i:{k:c[k] for k in keep[c["type"]]} for i,c in task["evidence"].items()}
    for i,c in payload["evidence"].items():
        original=task["evidence"][i]
        for key in ("statistics","history"):
            if key in original: c[key]=original[key]
        if c["type"]=="product":
            c["name"]=c["name"][:240]; c["description"]=c["description"][:280]
        elif c["type"]=="review":
            c["text"]=c["text"][:650]
    return payload


def publish_latest(run,output):
    """Publish only the evaluation used to assemble the combined report."""
    shutil.copyfile(run/"evaluation.json",output/"llm-report-evaluation.json")


def review_saved_report(output,run_name,decisions,notes=(),reviewer="Chưa ghi tên"):
    """Record a reading of ALL paragraphs, reject mistakes, never rewrite model prose.

    A decision is keyed by task and paragraph SHA256, with keep/reject and reason.
    This function records an explicit review, not an automatic semantic checker.
    It does not call any API or alter the original automatic sections/evaluation.
    """
    output=Path(output).resolve(); run=(output/run_name).resolve()
    if not run.is_relative_to(output/"llm-reports"):
        raise ValueError("Lượt báo cáo phải nằm trong llm-reports của nghiên cứu")
    pack=json.loads((run/"input.json").read_text(encoding="utf-8"))
    if digest(output/"dataset.json")!=pack["input_sha256"]:
        raise RuntimeError("Dataset đã đổi; không cập nhật báo cáo của dữ liệu cũ")
    original=json.loads((run/"sections.json").read_text(encoding="utf-8"))
    evaluation=json.loads((run/"evaluation.json").read_text(encoding="utf-8"))
    if evaluation.get("manual_review"):
        raise ValueError("Lượt này đã có kết quả đọc đối chiếu")
    by_key={(d["task"],d["paragraph_sha256"]):d for d in decisions}
    expected={(s["id"],paragraph_digest(p)) for s in original for p in s["paragraphs"]}
    if len(by_key)!=len(decisions) or set(by_key)!=expected:
        raise ValueError("Cần quyết định đúng checksum cho mọi đoạn của lượt báo cáo")
    for d in decisions:
        if d["decision"] not in {"keep","reject"} or not isinstance(d.get("reason"),str) or not d["reason"].strip():
            raise ValueError("Mỗi quyết định cần keep/reject và lý do")
    sections=[{**s,"paragraphs":[p for p in s["paragraphs"] if by_key[(s["id"],paragraph_digest(p))]["decision"]=="keep"]} for s in original]
    rejected=sum(d["decision"]=="reject" for d in decisions)
    review={"reviewed_at_utc":now(),"reviewer":reviewer,"reviewed_paragraphs":len(decisions),"rejected_paragraphs":rejected,
            "method":"Recorded reading against the supplied source registry; not an automatic check or self-evaluation by the report model",
            "decisions":decisions,"notes":list(notes)}
    save_json(run/"automatic-evaluation.json",evaluation)
    evaluation["automatic_status"]=evaluation["status"]
    evaluation["automatic_accepted_paragraphs"]=evaluation["accepted_paragraphs"]
    evaluation["accepted_paragraphs"]-=rejected
    evaluation["manual_review"]=review
    evaluation["sections"]=[{"id":s["id"],"title":s["title"],"paragraphs":len(s["paragraphs"])} for s in sections]
    if rejected:
        evaluation["status"]="partial" if evaluation["accepted_paragraphs"] else "failed"
        evaluation["warnings"].append("Đã loại thêm đoạn sai khi đọc đối chiếu. Xem manual-review.json; không dùng đoạn đã loại làm kết luận.")
    save_json(run/"manual-review.json",review)
    save_json(run/"reviewed-sections.json",sections)
    save_json(run/"evaluation.json",evaluation)
    publish_latest(run,output)
    return evaluation


def run_llm_report(output,model=None,max_calls=6,event=None,*,profile="standalone"):
    output=Path(output)
    if profile not in {"standalone","combined"}:
        raise ValueError("Loại báo cáo không được hỗ trợ")
    if type(max_calls) is not int or not 1<=max_calls<=8:
        raise ValueError("Chọn tối đa 1–8 lần gọi model")
    env=load_env(); model=model or env.get("OPENROUTER_MODEL","openrouter/free")
    if not (model.endswith(":free") or model=="openrouter/free"):
        raise ValueError("Nhánh so sánh này chỉ gọi model :free hoặc openrouter/free")
    if not env.get("OPENROUTER_API_KEY"):
        raise RuntimeError("Điền OPENROUTER_API_KEY trong api/.env trước khi gọi LLM")
    pack=evidence_pack(output)
    pack["analysis_sha256"]=digest(output/"monthly-analysis.json")
    if profile=="combined":
        from .combined_context import enrich_pack
        enrich_pack(pack,json.loads((output/"dataset.json").read_text(encoding="utf-8")),
            json.loads((output/"monthly-analysis.json").read_text(encoding="utf-8")))
    identifier=now().replace(":","").replace(".","").replace("+","")+"-"+secrets.token_hex(3)
    run=output/"llm-reports"/identifier
    run.mkdir(parents=True)
    prompt=PROMPT_PATH.read_text(encoding="utf-8")
    if profile=="combined":
        prompt+="\n"+(ROOT/"market_radar/prompts/report_combined_vi.md").read_text(encoding="utf-8")
    (run/"prompt.txt").write_text(prompt,encoding="utf-8")
    save_json(run/"input.json",pack)
    baseline=digest(output/"report.md") if (output/"report.md").exists() else None
    event=event or (lambda text:print(text,flush=True))
    client=Client(run,env,event=event)
    client.max_calls.update(openrouter=max_calls,serpapi=0,tavily=0)
    evaluation={"model":model,"profile":profile,"started_at_utc":now(),"input_sha256":pack["input_sha256"],"baseline_sha256":baseline,
        "analysis_sha256":pack["analysis_sha256"],
        "run_directory":run.relative_to(output).as_posix(),"max_calls":max_calls,"calls":0,"attempts":[],"warnings":[],
        "prompt_sha256":hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "automatic_checks":["known short evidence IDs","exact review quote","matching ASIN/family","no digits, URLs or HTML in Vietnamese paragraphs"],
        "not_verified":["semantic correctness of every inference","Vietnamese naturalness","representativeness of reviews"],
        "comparison_scope":"One model/run is not evidence that all free models are weaker or stronger than paid models. No paid model called."}
    sections=[]; halted=False
    started=time.perf_counter()
    tasks=list(pack["tasks"])
    for task_index in range(len(tasks)+1):
        if task_index==len(tasks):
            used={i for s in sections for p in s["paragraphs"] for i in p["evidence_ids"]}
            if profile=="combined" and used:
                used.update(i for i,c in pack["evidence"].items() if c["type"] in {"product","timing"})
            task={"id":"overview","title":"Tổng quan và hướng kiểm chứng tiếp theo","scope":pack["scope"],
                  "evidence":{i:pack["evidence"][i] for i in sorted(used)},
                  "validated_sections":[{"title":s["title"],"paragraphs":s["paragraphs"]} for s in sections]}
            if profile=="combined":
                task["computed"]={"niches":[{"id":t["id"],"title":t["title"],**t["computed"]} for t in tasks]}
            if not used: break
        else:
            task=tasks[task_index]
        targets=({"observations":1,"recommendations":1,"gaps":1} if task["id"]=="overview" else
                 {"observations":2,"reviews":2,"recommendations":1,"gaps":1}) if profile=="combined" else (
                 {} if task["id"]=="overview" else {"observations":1,"reviews":1,"recommendations":1})
        accepted=[]; seen=set(); repair=None
        for attempt in (1,2):
            if len(client.calls)>=max_calls or halted: break
            # Give the remaining niches and the overview their first attempt
            # before spending spare calls on a repair of this section.
            remaining_tasks=len(tasks)-task_index
            if attempt==2 and max_calls-len(client.calls)<=remaining_tasks:
                break
            payload=request_payload(task)
            payload["request_type"]="overview" if task["id"]=="overview" else "niche_section"
            if repair: payload["repair_only_rejected_paragraphs"]=repair
            metadata={"task":task["id"],"attempt":attempt}; before=len(client.calls)
            request_started=time.perf_counter()
            event(f"LLM: {task['title']} — lần {attempt}, còn {max_calls-len(client.calls)} lượt trong giới hạn")
            try:
                envelope=client.request("openrouter",{"model":model,"messages":[{"role":"system","content":prompt},
                    {"role":"user","content":json.dumps(payload,ensure_ascii=False)}],
                    # Flint's developer recommends temperature 1.0; very low
                    # sampling caused long, empty completions in our first run.
                    "temperature":1.0 if model.startswith("recursive/flint-") else 0.2,"max_tokens":16000,
                    "reasoning":{"effort":"low","exclude":True},"response_format":{"type":"json_object"}},cache=False)
                usage=envelope["response"].get("usage",{})
                metadata.update(raw_file=envelope["raw_file"],served_model=envelope["response"].get("model"),usage=usage)
                metadata["finish_reason"]=(envelope["response"].get("choices") or [{}])[0].get("finish_reason")
                items=parse_answer(envelope)
                reviewed=[]; bad=[]
                for item in items:
                    errors=validate_paragraph(item,task["evidence"])
                    if not errors and attempt==2 and task["id"]!="overview" and sum(p["section"]==item["section"] for p in accepted)>=targets.get(item["section"],1):
                        errors=["Đã có đoạn cho loại này; bỏ đoạn lặp trong lần sửa"]
                    reviewed.append({"paragraph":item,"errors":errors})
                    if errors: bad.append({"paragraph":item,"errors":errors})
                    elif item["text"] not in seen:
                        accepted.append(item); seen.add(item["text"])
                metadata["validation_errors"]=[{"paragraph_index":i,"errors":r["errors"]} for i,r in enumerate(reviewed) if r["errors"]]
                metadata.update(accepted=sum(not r["errors"] for r in reviewed),rejected=len(bad))
                present=Counter(p["section"] for p in accepted)
                missing={kind:amount-present[kind] for kind,amount in targets.items() if present[kind]<amount}
                metadata["missing_sections"]=sorted(missing)
                repair={"rejected":bad,"missing_sections":sorted(missing),"missing_paragraph_counts":missing,
                        "instruction":"Only replace rejected paragraphs and add missing section types. Keep using the supplied evidence."}
                if not bad and not missing and accepted: break
            except RuntimeError as error:
                metadata["error"]=str(error)
                repair={"error":str(error),"instruction":"Return the requested JSON paragraphs with exact short IDs and quotes"}
                if any(s in str(error) for s in ("HTTP 400","HTTP 401","HTTP 402","HTTP 403","HTTP 404","HTTP 429","Network/timeout","budget","Missing")):
                    halted=True
            finally:
                metadata["network_calls"]=len(client.calls)-before
                metadata["elapsed_seconds"]=round(time.perf_counter()-request_started,2)
                evaluation["attempts"].append(metadata)
                save_json(run/"evaluation.json",evaluation)
        sections.append({"id":task["id"],"title":task["title"],"paragraphs":accepted})
    overview=[s for s in sections if s["id"]=="overview"]
    sections=overview+[s for s in sections if s["id"]!="overview"]
    counts=Counter(p["section"] for s in sections for p in s["paragraphs"])
    expected={"observations":2,"reviews":2,"recommendations":1,"gaps":1} if profile=="combined" else {"observations":1,"reviews":1,"recommendations":1}
    complete=all(any(s["id"]==t["id"] and all(sum(p["section"]==kind for p in s["paragraphs"])>=amount for kind,amount in expected.items()) for s in sections) for t in tasks)
    if profile=="combined":
        complete=complete and bool(overview) and {p["section"] for p in overview[0]["paragraphs"]}>={"observations","recommendations","gaps"}
    total=sum(counts.values())
    evaluation.update(status="generated_needs_reading" if complete and overview and overview[0]["paragraphs"] else "partial" if total else "failed",
        calls=len(client.calls),accepted_paragraphs=total,rejected_paragraphs=sum(a.get("rejected",0) for a in evaluation["attempts"]),
        sections=[{"id":s["id"],"title":s["title"],"paragraphs":len(s["paragraphs"])} for s in sections],
        finished_at_utc=now(),elapsed_seconds=round(time.perf_counter()-started,2))
    costs=[a.get("usage",{}).get("cost") for a in evaluation["attempts"] if a.get("usage")]
    evaluation["reported_cost_usd"]=sum(costs) if costs and all(type(c) in (int,float) for c in costs) else None
    if not complete: evaluation["warnings"].append("Một số mục chưa đủ đoạn có dẫn chứng; không tự dùng văn bản mẫu Python để lấp chỗ trống.")
    evaluation["warnings"].extend(a["task"]+": "+a["error"] for a in evaluation["attempts"] if a.get("error"))
    if not overview or not overview[0]["paragraphs"]:
        evaluation["warnings"].append("Chưa có phần tổng quan do model viết và qua kiểm tra.")
    if digest(output/"dataset.json")!=pack["input_sha256"] or digest(output/"monthly-analysis.json")!=pack["analysis_sha256"]:
        raise RuntimeError("Dataset hoặc phân tích đổi giữa lúc model viết; giữ nhật ký nhưng không cập nhật báo cáo mới nhất")
    clean=lambda value:scrub(value,[env.get(k,"") for k in KEYS])
    sections=clean(sections); evaluation=clean(evaluation)
    save_json(run/"sections.json",sections)
    save_json(run/"evaluation.json",evaluation)
    publish_latest(run,output)
    event(f"Đã lưu phần diễn giải LLM — {evaluation['status']}, {total} đoạn, {evaluation['calls']} lượt API")
    return evaluation
