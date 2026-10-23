"""Local-only research workbench. Browser receives no API keys or arbitrary file access."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import mimetypes
from pathlib import Path
import re
import secrets
import socket
import threading
from statistics import median
from urllib.parse import parse_qs, unquote, urlsplit

from .io import ROOT, KEYS, load_env, now, save_json, scrub
from .csv_exports import CSV_NAME, csv_files
from .settings import local_today, study_months, validate_config


def report_status(output):
    """Describe what is actually included in the saved report, not merely configured."""
    output = Path(output)
    available = all((output/name).is_file() for name in ("report.html", "report.md"))
    result = {"available": available, "current": False, "mode": "not_generated", "llm": None,
              "ai_input_available": (output/"ai-input.json").is_file()}
    try:
        build = json.loads((output/"report-build.json").read_text(encoding="utf-8"))
        current_hash = hashlib.sha256((output/"dataset.json").read_bytes()).hexdigest()
        current = available and build.get("input_sha256") == current_hash
        result.update(current=current, mode=build.get("mode", "unknown"), generated_at_utc=build.get("generated_at_utc"))
        if current and build.get("mode") == "rules_plus_llm":
            insights = json.loads((output/"llm-insights.json").read_text(encoding="utf-8"))
            if insights.get("input_sha256") == current_hash and insights.get("insights"):
                result["llm"] = {"model": insights.get("model"), "created_at_utc": insights.get("created_at_utc"),
                                 "insight_count": len(insights["insights"])}
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return result


def study_summary(data, config):
    """Summaries of the same normalized rows exported to the source CSVs."""
    products, reviews = data.get("products",[]), data.get("reviews",[])
    product_ids={p["asin"] for p in products}
    reviewed={r["asin"] for r in reviews}&product_ids
    prices=[p["price_usd"] for p in products if type(p.get("price_usd")) in (int,float)]
    bins=[{"label":"Dưới $10","count":sum(v<10 for v in prices)},
          {"label":"$10 đến dưới $20","count":sum(10<=v<20 for v in prices)},
          {"label":"$20 đến dưới $30","count":sum(20<=v<30 for v in prices)},
          {"label":"Từ $30","count":sum(v>=30 for v in prices)}]
    groups=[]
    for niche in config.get("niches",[]):
        ids={p["asin"] for p in products if niche["id"] in p.get("niche_ids",[])}
        groups.append({"name":niche.get("name_vi",niche.get("name",niche["id"])),"products":len(ids),
                       "reviewed_products":len(ids&reviewed),"reviews":sum(r["asin"] in ids for r in reviews)})
    return {"products":len(product_ids),"reviews":len(reviews),"keywords":len(data.get("keywords",[])),
            "full_reviews":sum(r.get("review_text_kind","full")=="full" for r in reviews),
            "review_excerpts":sum(r.get("review_text_kind")=="excerpt" for r in reviews),
            "web_sources":len(data.get("web_sources",[])),"reviewed_products":len(reviewed),
            "price_bins":bins,"missing_prices":len(products)-len(prices),"median_price_usd":median(prices) if prices else None,
            "groups":groups}


class Jobs:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.data = self.root/"data"
        self.lock = threading.RLock()
        self.jobs = {}
        self.active = None
        self.directory = self.data/".jobs"
        self.directory.mkdir(parents=True,exist_ok=True)
        for path in self.directory.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] in ("queued","running"):
                    job.update(status="interrupted",message="Server đã dừng giữa lượt chạy. Nguồn đã thu được giữ lại.")
                    save_json(path,job)
                    if job.get("study_id"):
                        meta_path=self.folder(job["study_id"])/"study.json"
                        if meta_path.exists():
                            meta=json.loads(meta_path.read_text(encoding="utf-8"))
                            if job.get("kind") == "report":
                                meta.update(last_report_warnings=[job["message"]])
                            else:
                                meta.update(status="interrupted",error=job["message"])
                            save_json(meta_path,meta)
                self.jobs[job["id"]] = job
            except (ValueError,KeyError,OSError):
                continue

    def folder(self, identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}",identifier):
            raise ValueError("Mã lượt chạy không hợp lệ")
        path = (self.data/identifier).resolve()
        if not path.is_relative_to(self.data.resolve()):
            raise ValueError("Đường dẫn ngoài thư mục dữ liệu")
        return path

    def safe(self, value):
        env = load_env()
        return scrub(value,[env.get(k,"") for k in KEYS])

    def update(self, identifier, **values):
        with self.lock:
            self.jobs[identifier].update(self.safe(values))
            self.jobs[identifier]["updated_at_utc"] = now()
            save_json(self.directory/(identifier+".json"),self.jobs[identifier])

    def event(self, identifier, message):
        with self.lock:
            logs = self.jobs[identifier]["logs"]
            logs.append({"at":now(),"message":self.safe(str(message))[:700]})
            self.update(identifier,logs=logs[-300:],message=self.safe(str(message))[:350])

    def get(self, identifier):
        with self.lock:
            if identifier not in self.jobs:
                raise ValueError("Không tìm thấy tác vụ")
            return deepcopy(self.jobs[identifier])

    def submit(self, kind, payload):
        with self.lock:
            if kind not in {"plan", "run", "rebuild", "report", "supplement"}:
                raise ValueError("Chức năng không hợp lệ")
            if self.active and self.jobs[self.active]["status"] in ("queued","running"):
                raise RuntimeError("Đang có một tác vụ. Chờ hoàn tất trước khi tạo tác vụ khác.")
            if kind == "run":
                payload = {**payload,"config":validate_config(payload.get("config"))}
                env = load_env()
                if not env.get("SERPAPI_API_KEY") or not env.get("TAVILY_API_KEY"):
                    raise ValueError("Cần SERPAPI_API_KEY và TAVILY_API_KEY trong api/.env trước khi thu thập")
            elif kind == "supplement":
                output=self.folder(payload.get("study_id"))
                if not all((output/name).is_file() for name in ("collection.json","dataset.json")):
                    raise ValueError("Cần có dữ liệu sản phẩm trước khi bổ sung")
                if not load_env().get("SERPAPI_API_KEY"):
                    raise ValueError("Cần SERPAPI_API_KEY trong api/.env")
                budget=payload.get("max_requests",12)
                if type(budget) is not int or not 1<=budget<=45:
                    raise ValueError("Số lượt bổ sung phải từ 1 đến 45")
                payload={"study_id":payload["study_id"],"max_requests":budget}
            elif kind == "rebuild":
                if not (self.folder(payload.get("study_id"))/"collection.json").exists():
                    raise ValueError("Lượt chạy chưa có nguồn để dựng lại")
            elif kind == "report":
                output = self.folder(payload.get("study_id"))
                if not all((output/name).is_file() for name in ("dataset.json", "monthly-analysis.json", "collection.json")):
                    raise ValueError("Cần có dữ liệu và phân tích trước khi viết báo cáo bằng AI")
                env = load_env()
                if not env.get("OPENROUTER_API_KEY"):
                    raise ValueError("Điền OPENROUTER_API_KEY trong api/.env trước khi dùng AI")
                model = env.get("OPENROUTER_MODEL", "openrouter/free")
                if not (model.endswith(":free") or model == "openrouter/free"):
                    raise ValueError("Chọn model :free hoặc openrouter/free trong api/.env")
                payload = {**payload, "use_llm_report": True}
            identifier = kind+"-"+secrets.token_hex(6)
            self.jobs[identifier] = {"id":identifier,"kind":kind,"status":"queued","stage":"queued",
                "progress":0,"message":"Đang chuẩn bị","logs":[],"created_at_utc":now(),"updated_at_utc":now(),
                "topic":payload.get("topic") or (payload.get("config") or {}).get("category","")}
            if kind in {"report", "rebuild", "supplement"}:
                self.jobs[identifier]["study_id"] = payload["study_id"]
            self.active = identifier
            self.update(identifier)
            threading.Thread(target=self.work,args=(identifier,kind,deepcopy(payload)),daemon=True).start()
            return deepcopy(self.jobs[identifier])

    def work(self, identifier, kind, payload):
        from .study import new_config, write_insights
        from .seasonal import SeasonalRun
        from .seasonal_data import build_seasonal_data, verify_seasonal_data
        from .seasonal_report import generate_report
        event = lambda message: self.event(identifier,message)
        study_id = None
        warnings = []
        try:
            self.update(identifier,status="running",stage={"plan":"planning", "report":"writing", "rebuild":"building"}.get(kind,"collecting"),progress=5)
            if kind == "plan":
                output = self.directory/identifier
                config, planning = new_config(payload,output,event)
                save_json(output/"plan.json",{"config":config,"planning":planning})
                self.update(identifier,status="completed",stage="ready",progress=100,
                            message="Kế hoạch đã sẵn sàng. Bạn có thể sửa keyword và nhóm trước khi thu thập.",
                            result={"config":config,"planning":planning})
                return
            if kind == "run":
                study_id = "study-"+local_today().strftime("%Y%m%d")+"-"+secrets.token_hex(4)
                output = self.folder(study_id)
                output.mkdir(parents=True,exist_ok=False)
                save_json(output/"study.json",{"id":study_id,"status":"running","created_at_utc":now(),
                    "planning":payload.get("planning",{}),"config":payload["config"]})
                save_json(output/"config.json",payload["config"])
                self.update(identifier,study_id=study_id,message="Đang lấy dữ liệu qua Tavily và SerpApi")
                collector = SeasonalRun(output,config=payload["config"],event=event,fresh=bool(payload.get("fresh")))
                try:
                    collector.collect()
                except RuntimeError as error:
                    if not any(collector.manifest["family_asins"].values()):
                        raise
                    warnings.append(str(error))
                    event("Thu thập dừng sớm; dựng báo cáo từ phần nguồn đã lấy được")
                warnings.extend(e["source"]+": "+e["error"] for e in collector.manifest["errors"])
            else:
                study_id = payload["study_id"]
                output = self.folder(study_id)
                self.update(identifier,study_id=study_id)
            if kind == "supplement":
                from .supplement import SupplementRun
                supplement=SupplementRun(output,payload["max_requests"],event).collect()
                warnings.extend(a["asin"]+": "+a["error"] for a in supplement["attempts"] if a["status"]=="failed")
            if kind != "report":
                self.update(identifier,stage="building",progress=78,message="Chuẩn hóa CSV và tính mùa vụ theo các tháng đã chọn")
                build_seasonal_data(output)
            llm_updated = False
            if payload.get("use_llm_report"):
                self.update(identifier,stage="writing",progress=88,message="Đang gọi model viết nhận định có trích dẫn")
                try:
                    write_insights(output,event)
                    llm_updated = True
                except (RuntimeError,ValueError) as error:
                    warnings.append(str(error))
                    event("AI chưa viết được nhận định mới; báo cáo dùng số liệu và phần nhận định hợp lệ đã lưu, nếu có")
            self.update(identifier,stage="reporting",progress=94,message="Xuất báo cáo và dashboard")
            generate_report(output)
            verify_seasonal_data(output)
            meta_path = output/"study.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"id":study_id}
            status = "completed_with_warnings" if warnings else "completed"
            if kind == "report":
                meta.update(report_updated_at_utc=now(),last_report_warnings=warnings)
            else:
                meta.update(status=status,finished_at_utc=now(),warnings=warnings)
            save_json(meta_path,meta)
            self.update(identifier,status=status,stage="done",progress=100,warnings=warnings,
                        result={"report":report_status(output), "llm_updated":llm_updated},
                        message=("Chưa tạo được nhận định AI mới. Báo cáo hiện có vẫn mở được; xem lý do bên dưới." if kind=="report" else "Đã có kết quả; xem các nguồn thiếu/cảnh báo bên dưới.") if warnings else
                                ("Đã thêm phân tích AI vào báo cáo. Bạn có thể mở hoặc tải báo cáo ở phần Kết quả." if kind=="report" else "Đã hoàn tất dữ liệu, báo cáo và dashboard."))
        except Exception as error:
            # Never expose exception URLs/headers or tracebacks in the browser.
            message = str(error) if isinstance(error,(ValueError,RuntimeError)) else "Không hoàn tất lượt chạy; kiểm tra dữ liệu nguồn và quyền đọc/ghi trên máy."
            self.update(identifier,status="failed",failed_stage=self.get(identifier).get("stage"),stage="failed",message=message,progress=0)
            if study_id:
                path = self.folder(study_id)/"study.json"
                meta = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"id":study_id}
                if kind == "report":
                    meta.update(last_report_warnings=[self.safe(message)])
                else:
                    meta.update(status="failed",error=self.safe(message))
                save_json(path,meta)
        finally:
            with self.lock:
                if self.active == identifier:
                    self.active = None

    def studies(self):
        result = []
        for path in self.data.glob("*/collection.json"):
            if path.parent.name.startswith("."):
                continue
            try:
                self.folder(path.parent.name)
                collection = json.loads(path.read_text(encoding="utf-8"))
                config = collection["config"]
                if not config.get("families"):
                    continue
                meta_path = path.parent/"study.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
                if meta.get("hidden"):
                    continue
                dataset_path = path.parent/"dataset.json"
                data = json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.exists() else {}
                ready = bool(data) and (path.parent/"dashboard.html").exists()
                result.append({"id":path.parent.name,"category":config["category"],"display_name":meta.get("display_name",config["category"]),"niches":[n.get("name_vi",n["name"]) for n in config["niches"]],
                    "months":study_months(config),"years":config["years"],"as_of_date":config["as_of_date"],
                    "products":len(data.get("products",[])),"reviews":len(data.get("reviews",[])),"ready":ready,
                    "status":meta.get("status","completed" if ready else "partial"),"warnings":meta.get("warnings",[]),
                    "source_errors":collection.get("errors",[]),"config":config,
                    "summary":study_summary(data,config),
                    "report":report_status(path.parent),"report_warnings":meta.get("last_report_warnings",[]),
                    "exports":csv_files(path.parent),
                    "created_at_utc":meta.get("created_at_utc",collection.get("started_at_utc",""))})
            except (ValueError,KeyError,OSError,TypeError):
                continue
        return sorted(result,key=lambda r:r["created_at_utc"],reverse=True)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, manager=None):
        self.manager = manager or Jobs()
        self.token = secrets.token_urlsafe(32)
        super().__init__(address,Handler)

    def server_bind(self):
        # On Windows, SO_REUSEADDR can let two servers share the same address.
        # Requests may then reach an older process even after a new one starts.
        if hasattr(socket,"SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            self.allow_reuse_address = False
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def trusted_host(self):
        port = self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}",f"localhost:{port}"}

    def send(self, status, body, content_type="application/json; charset=utf-8", download=None):
        if not isinstance(body,bytes):
            body = json.dumps(body,ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("X-Frame-Options","SAMEORIGIN")
        self.send_header("Referrer-Policy","no-referrer")
        if download:
            self.send_header("Content-Disposition",f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.trusted_host():
            return self.send(403,{"error":"Chỉ truy cập bằng localhost hoặc 127.0.0.1"})
        path = unquote(urlsplit(self.path).path)
        manager = self.server.manager
        try:
            file_root = ROOT
            if path == "/api/bootstrap":
                from .study import presets
                env = load_env()
                with manager.lock:
                    jobs = sorted((deepcopy(j) for j in manager.jobs.values() if not j.get("hidden")),key=lambda j:j["created_at_utc"],reverse=True)[:12]
                return self.send(200,{"token":self.server.token,"today":local_today().isoformat(),
                    "keys":{k:bool(env.get(k)) for k in KEYS},"model":env.get("OPENROUTER_MODEL","openrouter/free"),
                    "presets":presets(),"studies":manager.studies(),"jobs":jobs})
            if path == "/api/studies":
                return self.send(200,manager.studies())
            if path.startswith("/api/jobs/"):
                return self.send(200,manager.get(path.rsplit("/",1)[-1]))
            if path == "/":
                file = ROOT/"market_radar/assets/workspace.html"
            elif path in ("/assets/workspace.js","/assets/workspace.css","/assets/workspace-theme.css","/assets/csv.css"):
                file = ROOT/"market_radar"/path.lstrip("/")
            elif path.startswith("/runs/"):
                parts = path.split("/")
                if len(parts)!=4:
                    raise ValueError("Đường dẫn kết quả không hợp lệ")
                identifier,name = parts[2:]
                allowed = name in {"report.html","dashboard.html","report.md","acceptance.json","dataset.json","monthly-analysis.json","config.json","ai-input.json","llm-insights.json","report-build.json"} or bool(CSV_NAME.fullmatch(name))
                if not allowed:
                    return self.send(404,{"error":"File không được công khai qua dashboard"})
                file = manager.folder(identifier)/name
                file_root = manager.data
            else:
                return self.send(404,{"error":"Không tìm thấy"})
            if not file.is_file() or not file.resolve().is_relative_to(file_root.resolve()):
                return self.send(404,{"error":"File chưa sẵn sàng"})
            media = {".js":"text/javascript",".css":"text/css",".html":"text/html",".json":"application/json",
                     ".csv":"text/csv",".md":"text/markdown"}.get(file.suffix.lower())
            media = media or mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            download = file.name if path.startswith("/runs/") and file.name in {"report.html","report.md"} and parse_qs(urlsplit(self.path).query).get("download")==["1"] else None
            if path.startswith("/runs/") and CSV_NAME.fullmatch(file.name):
                download = file.name
            return self.send(200,file.read_bytes(),media+"; charset=utf-8",download=download)
        except (ValueError,KeyError,OSError):
            self.send(404,{"error":"Chưa tìm thấy dữ liệu phù hợp"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        allowed = {f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}
        if not self.trusted_host() or (origin and origin not in allowed) or not secrets.compare_digest(self.headers.get("X-Radar-Token",""),self.server.token):
            return self.send(403,{"error":"Yêu cầu cần xuất phát từ dashboard local"})
        try:
            if self.headers.get("Content-Type","").split(";")[0] != "application/json":
                raise ValueError("Cần nội dung JSON")
            length = int(self.headers.get("Content-Length",0))
            if not 0 < length <= 100000:
                raise ValueError("Nội dung rỗng hoặc quá lớn")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload,dict):
                raise ValueError("Cần JSON object")
            kind = {"/api/plan":"plan","/api/run":"run","/api/rebuild":"rebuild","/api/report":"report","/api/supplement":"supplement"}.get(urlsplit(self.path).path)
            if not kind:
                return self.send(404,{"error":"Không tìm thấy chức năng"})
            job = self.server.manager.submit(kind,payload)
            self.send(202,job)
        except (ValueError,UnicodeError) as error:
            self.send(400,{"error":self.server.manager.safe(str(error))})
        except RuntimeError as error:
            self.send(409,{"error":self.server.manager.safe(str(error))})


def serve(port=8765):
    try:
        server = LocalServer(("127.0.0.1",port))
    except OSError as error:
        raise RuntimeError(f"Không mở được cổng {port}; thử dashboard --port {port+1}") from error
    print(f"Market Radar local: http://127.0.0.1:{server.server_port}",flush=True)
    print("Giữ terminal mở. Ctrl+C để dừng. API key chỉ đọc phía Python.",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
