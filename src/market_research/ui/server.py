"""Loopback UI, bounded background jobs and an output-only file boundary."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as _ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import threading
from urllib.parse import urlsplit, unquote, parse_qs

from ..common import ROOT, read_json, now, identity
from ..config import DEFAULT_LIMITS, validate_config
from ..pipeline import execute, rebuild, STAGES, process_alive
from ..providers.client import environment
from ..providers.web import SOURCE_DOMAINS
from ..business.domain import CATEGORY_LABELS
from ..storage.run import Run
from ..storage.database import Database
from .workspace import Workspace, product_csv, run_path
from .progress import stage_detail

ASSETS = Path(__file__).parent / "assets"
# Windows registry associations may map .js to text/plain. Browsers block that
# response with nosniff, so the app must define its own web content types.
CONTENT_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class ThreadingHTTPServer(_ThreadingHTTPServer):
    """Own the dashboard port exclusively, including on Windows.

    HTTPServer normally enables SO_REUSEADDR. On Windows that can allow two
    dashboard processes to listen on the same address and randomly serve old
    or new application code. Set exclusivity before the socket is bound.
    """
    allow_reuse_address = False
    allow_reuse_port = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Manager:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="research")
        self.guard = threading.Lock()
        self.jobs = {}
        self.cancellations = {}
        self.operations = {}
        self.db = Database(self.root)
        self.db.migrate_legacy()
        self.workspace = Workspace(self.root)

    def manifest(self, run_id):
        stored = self.db.get_manifest(run_id)
        return stored if stored is not None else read_json(self.root / "data/runs" / run_id / "manifest.json")

    def checkpoint(self, run_id, stage):
        stored = self.db.get_checkpoint(run_id, stage)
        return stored if stored is not None else read_json(self.root / "data/runs" / run_id / "checkpoints" / (stage + ".json"), {})

    def submit(self, config=None, run_id=None, report_only=False):
        with self.guard:
            if any(not future.done() for future in self.jobs.values()):
                raise ValueError("Đang có một nghiên cứu chạy; chờ hoàn tất trước khi bắt đầu lượt khác")
            if config is not None:
                config = validate_config(config)
            run = Run(run_id, self.root)
            if config is not None:
                run.manifest.update(status="queued", input=config, input_hash=identity("config", config), mode=config["mode"], summary={"category": config["brief"][:120]})
                run.save()
            cancel = threading.Event()
            self.cancellations[run.id] = cancel
            self.operations[run.id] = "report" if report_only else "research"
            def work():
                try:
                    return rebuild(run.id, self.root) if report_only else execute(config, run_id=run.id, root=self.root, event=lambda message: None, cancel_event=cancel)
                except Exception as error:
                    state = Run(run.id, self.root)
                    state.manifest.update(status="failed", error=str(error) if isinstance(error, (ValueError, RuntimeError)) else "Lỗi nội bộ; kiểm tra checkpoint")
                    state.save()
            self.jobs[run.id] = self.pool.submit(work)
            return run.id

    def stop(self, run_id):
        run_path(self.root, run_id)
        with self.guard:
            job = self.jobs.get(run_id)
            if job is None or job.done():
                raise ValueError("Không có tiến trình đang chạy trong server này để dừng")
            if self.operations.get(run_id) == "report":
                raise ValueError("Đang dựng lại báo cáo từ dữ liệu đã lưu, không gọi API")
            self.cancellations[run_id].set()
            if job.cancel():
                run = Run(run_id, self.root)
                run.manifest.update(status="cancelled", stopped_at=now(), stop_message="Đã hủy trước khi bắt đầu")
                run.save()
            return {"run_id": run_id, "status": "cancelling" if not job.done() else "cancelled"}

    def list_runs(self):
        rows = []
        state = self.workspace.state()
        manifests = {p.parent.name: read_json(p, {}) for p in (self.root / "data/runs").glob("*/manifest.json")}
        manifests.update({row["run_id"]: row for row in self.db.list_runs()})
        for data in manifests.values():
            data = self.present(data)
            row = {k: data.get(k) for k in ("run_id", "created_at", "status", "summary", "mode", "current_stage", "updated_at", "can_stop")}
            run_id = data["run_id"]
            row.update(saved=run_id in state["saved_runs"], user_title=state["edited"].get(run_id, {}).get("title"),
                       has_report=(self.root / "outputs" / run_id / "report.html").is_file(), has_edit=run_id in state["edited"])
            rows.append(row)
        return sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)

    def present(self, manifest):
        """A crashed process must expose resume even if disk state says running."""
        data = dict(manifest)
        job = self.jobs.get(data["run_id"])
        local_active = job is not None and not job.done()
        data["can_stop"] = local_active and self.operations.get(data["run_id"]) != "report"
        if local_active and self.operations.get(data["run_id"]) == "report":
            data.update(status="running", current_stage="report", operation="report")
        if data.get("status") in {"running", "queued"}:
            lock = read_json(self.root / "data/runs" / data["run_id"] / ".running.lock", {})
            pid = lock.get("pid")
            active = job is not None and not job.done()
            active = active or (isinstance(pid, int) and pid > 0 and process_alive(pid))
            if not active:
                data["status"] = "interrupted"
            elif local_active and self.cancellations[data["run_id"]].is_set():
                data["status"] = "cancelling"
        data["request_counts"] = {provider: sum(u["provider"] == provider for u in data.get("usage", [])) for provider in ("public_scraper", "serpapi", "tavily", "exa", "openrouter", "google_trends_free")}
        return data


def handler_class(manager):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, value, content_type="application/json; charset=utf-8", download=None):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="' + download + '"')
            self.end_headers()
            self.wfile.write(body)

        def trusted(self):
            return self.headers.get("Host") in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            try:
                return self.get()
            except (ValueError, TypeError) as error:
                return self.send(400, {"error": str(error)})
            except Exception:
                return self.send(500, {"error": "Không đọc được dữ liệu; kiểm tra lượt nghiên cứu và thử lại"})

        def get(self):
            if not self.trusted():
                return self.send(403, {"error": "Chỉ truy cập qua địa chỉ local"})
            path = unquote(urlsplit(self.path).path)
            query = {k: v[-1] for k, v in parse_qs(urlsplit(self.path).query, keep_blank_values=True).items()}
            if path == "/api/runs":
                return self.send(200, manager.list_runs())
            if path == "/api/settings":
                env = environment(manager.root)
                return self.send(200, {"keys": {k: bool(env.get(k)) for k in ("SERPAPI_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "OPENROUTER_API_KEY")}, "stages": STAGES, "limits": DEFAULT_LIMITS,
                    "business": {"default_profile": "custom_manufacturing", "categories": CATEGORY_LABELS},
                    "capabilities": {"broad_discovery": True, "free_trends": True, "auto_trends_recovery": True, "stage_details": True, "seasonal_history": True, "design_month_screening": True, "manufacturing_models": True, "design_content": True, "exa_discovery": True, "public_scrapers": True, "company_domain": True, "public_sites": list(SOURCE_DOMAINS), "apify": False}})
            if path in {"/api/products", "/api/products/export.csv"}:
                rows = manager.workspace.products(query)
                if path.endswith(".csv"):
                    return self.send(200, product_csv(rows), CONTENT_TYPES[".csv"], "san-pham-da-loc.csv")
                page = int(query.get("page", "1"))
                if page < 1:
                    raise ValueError("Trang phải lớn hơn 0")
                size = 40
                return self.send(200, {"items": rows[(page - 1) * size:page * size], "total": len(rows), "page": page, "page_size": size,
                                       "saved_count": len(manager.workspace.state()["saved_products"])})
            match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_-]{1,100})/stages/([a-zA-Z0-9_-]{1,50})", path)
            if match:
                if manager.manifest(match[1]) is None:
                    return self.send(404, {"error": "Không có lượt nghiên cứu"})
                return self.send(200, stage_detail(manager.root, match[1], match[2]))
            match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_-]{1,100})/editor", path)
            if match:
                return self.send(200, manager.workspace.editor(match[1]))
            match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_-]{1,100})", path)
            if match:
                manifest = manager.manifest(match[1])
                if manifest is None:
                    return self.send(404, {"error": "Không có lượt nghiên cứu"})
                base = manager.root / "outputs" / match[1]
                files = [str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*") if p.is_file() and p.suffix in {".html", ".md", ".csv", ".json", ".pdf"}]
                state = manager.workspace.state()
                discovery = manager.checkpoint(match[1], "discover")
                screened = manager.checkpoint(match[1], "screen")
                selected = manager.checkpoint(match[1], "select")
                histories = manager.checkpoint(match[1], "history")
                monthly = manager.checkpoint(match[1], "monthly")
                from ..workflow.diagnostics import screening_diagnostics
                screening_info = screening_diagnostics(manifest.get("input", {}), screened, manifest.get("usage", []))
                monthly_overview = monthly.get("rankings", {}) if isinstance(monthly, dict) else {}
                if not monthly_overview.get("rows") and manifest.get("status") not in {"running", "queued", "cancelling"}:
                    stored_data = manager.db.get_dataset(match[1]) or {}
                    monthly_overview = stored_data.get("keyword_monthly", {})
                # Present old checkpoints using current completion semantics;
                # never rewrite a run's input, counters or raw observations.
                from ..workflow.quality import outcome
                manifest = {**manifest, "stages": {k: dict(v) for k, v in manifest.get("stages", {}).items()}}
                completed_data = {"screen": screened, "select": selected, "history": histories}
                for stage in ("cluster", "commentary"):
                    if manifest["stages"].get(stage, {}).get("status") in {"complete", "partial", "skipped"}:
                        completed_data[stage] = manager.checkpoint(match[1], stage)
                for stage, checkpoint in completed_data.items():
                    stage_state = manifest["stages"].get(stage, {})
                    if checkpoint is not None and stage_state.get("status") in {"complete", "partial", "skipped"}:
                        stage_state.update(outcome(stage, checkpoint, manifest["input"]))
                quality = [{"direction_id": h.get("direction_id"), "measurement_query": h.get("measurement_query"), "status": h.get("status"),
                            "usable_years": h.get("usable_years", []), "stability": h.get("seasonal_stability", {}).get("status", h.get("stability")),
                            "confidence": h.get("validation", {}).get("confidence", {}), "metrics": h.get("validation", {}).get("metrics", {}),
                            "baseline_metrics": h.get("validation", {}).get("baseline_metrics", {}), "skill_pct": h.get("validation", {}).get("skill_pct"),
                            "reason": h.get("reason")} for h in histories if isinstance(h, dict)] if isinstance(histories, list) else []
                return self.send(200, {**manager.present(manifest), "files": files, "saved": match[1] in state["saved_runs"],
                                       "historical_overview": quality,
                                       "monthly_overview": monthly_overview,
                                       "screening_diagnostics": screening_info,
                                       "discovery_overview": {"rows": selected.get("rows", screened.get("rows", [])), "note": selected.get("note", screened.get("note")),
                                           "research_focus": discovery.get("research_focus", {}), "coverage": discovery.get("summary", {}),
                                           "method": screened.get("method"), "selection_basis": screened.get("selection_basis"),
                                           "analysis_year": screened.get("analysis_year"), "analysis_windows": screened.get("analysis_windows", []),
                                           "sources": discovery.get("discovery_sources", []), "pages": [{k: p.get(k) for k in ("title", "url", "platform", "retrieval_providers", "image", "image_links")} for p in discovery.get("web_context", []) if p.get("url")]},
                                       "user_title": state["edited"].get(match[1], {}).get("title")})
            if path == "/":
                file = ASSETS / "index.html"
            elif path in {"/assets/app.js", "/assets/style.css"}:
                file = ASSETS / path.rsplit("/", 1)[1]
            elif path.startswith("/outputs/"):
                file = (manager.root / path.lstrip("/")).resolve()
                boundary = (manager.root / "outputs").resolve()
                if not file.is_relative_to(boundary):
                    return self.send(403, {"error": "File không được công khai"})
                parts = file.relative_to(boundary).parts
                image_asset = file.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} and len(parts) == 3 and parts[1] == "assets"
                if file.suffix.lower() not in {".html", ".md", ".csv", ".json", ".pdf"} and not image_asset:
                    return self.send(403, {"error": "File không được công khai"})
            else:
                return self.send(404, {"error": "Không có tài nguyên"})
            if not file.is_file():
                return self.send(404, {"error": "Chưa có file kết quả"})
            return self.send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix.lower(), "application/octet-stream"))

        def do_POST(self):
            if not self.trusted() or self.headers.get("X-Research-Client") != "local":
                return self.send(403, {"error": "Yêu cầu cần xuất phát từ giao diện local"})
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.send(403, {"error": "Origin không hợp lệ"})
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 <= length <= 1_000_000:
                    return self.send(413, {"error": "Nội dung quá dài"})
                body = json.loads(self.rfile.read(length) or b"{}")
                path = urlsplit(self.path).path
                if path == "/api/runs":
                    return self.send(202, {"run_id": manager.submit(config=body)})
                if not isinstance(body, dict):
                    raise ValueError("Nội dung phải là JSON object")
                if path == "/api/workspace/save":
                    return self.send(200, manager.workspace.save_item(body))
                match = re.fullmatch(r"/api/runs/([a-zA-Z0-9_-]{1,100})/(resume|report|stop|editor)", path)
                if match and manager.manifest(match[1]) is not None:
                    if match[2] == "stop":
                        return self.send(202, manager.stop(match[1]))
                    if match[2] == "editor":
                        return self.send(200, manager.workspace.save_editor(match[1], body))
                    return self.send(202, {"run_id": manager.submit(run_id=match[1], report_only=match[2] == "report")})
                return self.send(404, {"error": "Không có thao tác"})
            except (ValueError, TypeError) as error:
                return self.send(400, {"error": str(error)})
            except Exception:
                return self.send(500, {"error": "Không xử lý được yêu cầu; kiểm tra cấu hình và tiến trình"})
    return Handler


def serve(port=8765):
    manager = Manager()
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_class(manager))
    print(f"Mở http://127.0.0.1:{server.server_port} — Ctrl+C để dừng", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for cancel in manager.cancellations.values():
            cancel.set()
        server.server_close()
        manager.pool.shutdown(wait=False, cancel_futures=True)
