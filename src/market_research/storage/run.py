"""Transactional run state, evidence and checkpoints with portable file mirrors."""
import csv
import json
import re
import secrets
from threading import RLock
from pathlib import Path

from ..common import ROOT, now, identity, read_json, write_json, safe_url
from .database import Database


class Run:
    def __init__(self, run_id=None, root=ROOT):
        self.root = Path(root).resolve()
        self.id = run_id or "run-" + now()[:19].replace(":", "").replace("-", "") + "-" + secrets.token_hex(3)
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", self.id):
            raise ValueError("run_id không hợp lệ")
        self.path = self.root / "data/runs" / self.id
        self.output = self.root / "outputs" / self.id
        self.path.mkdir(parents=True, exist_ok=True)
        self.output.mkdir(parents=True, exist_ok=True)
        self.db = Database(self.root)
        existing = self.db.get_manifest(self.id)
        if existing is None and (self.path / "manifest.json").is_file():
            self.db.import_run(self.path)
            existing = self.db.get_manifest(self.id)
        self.manifest = existing if existing is not None else {
            "run_id": self.id, "created_at": now(), "status": "pending", "stages": {}, "errors": [], "warnings": [], "usage": [],
        }
        self.evidence = self.db.get_evidence(self.id, {})
        if existing is None:
            self.db.save_run(self.manifest, self.evidence)
        self._log_lock = RLock()

    def log(self, stage, event, message, **details):
        """Append bounded observable events, never credentials or model reasoning."""
        from ..providers.client import environment, scrub
        if not hasattr(self, "_log_secrets"):
            self._log_secrets = [v for k, v in environment(self.root).items() if k.endswith("KEY") and v]
        remaining = [18000]
        def bounded(value, depth=0):
            if remaining[0] <= 0 or depth > 8:
                return "[rút gọn; xem checkpoint]"
            if isinstance(value, dict):
                return {str(k)[:100]: bounded(v, depth+1) for k, v in list(value.items())[:100]
                        if str(k).lower() not in {"reasoning", "reasoning_details", "analysis", "headers"}}
            if isinstance(value, (list, tuple)):
                return [bounded(v, depth+1) for v in value[:100]]
            if isinstance(value, str):
                text = value[:min(3000, remaining[0])]
                remaining[0] -= len(text)
                return text
            if value is None or isinstance(value, (int, float, bool)):
                return value
            return str(value)[:300]
        record = scrub({"id": "event-" + secrets.token_hex(12), "at": now(), "stage": stage or "workflow", "event": event,
                        "message": str(message)[:1500], "details": bounded(details)}, self._log_secrets)
        # A reader may observe a final incomplete line; API readers ignore that line.
        with self._log_lock:
            self.db.append_event(self.id, record)
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")

    def save(self):
        self.manifest["updated_at"] = now()
        self.db.save_run(self.manifest, self.evidence)
        write_json(self.path / "manifest.json", self.manifest)
        write_json(self.path / "evidence.json", self.evidence)

    def warn(self, message):
        if message not in self.manifest["warnings"]:
            self.manifest["warnings"].append(message)
            self.log(self.manifest.get("current_stage"), "warning", message)
        self.save()

    def add_evidence(self, kind, url, retrieved_at, raw_file=None, excerpt=None, **fields):
        if not safe_url(url):
            raise ValueError("Bằng chứng cần URL http/https hợp lệ")
        key = identity("E", kind, url, retrieved_at, raw_file, excerpt, fields)
        self.evidence[key] = {"id": key, "kind": kind, "url": url, "retrieved_at": retrieved_at,
                              "raw_file": raw_file, "excerpt": excerpt, **fields}
        return key

    def stage_data(self, name, default=None):
        missing = object()
        data = self.db.get_checkpoint(self.id, name, missing)
        if data is missing:
            data = read_json(self.path / "checkpoints" / f"{name}.json", missing)
            if data is not missing:
                self.db.save_checkpoint(self.id, name, data)
        return default if data is missing else data

    def checkpoint(self, name, data):
        self.db.save_checkpoint(self.id, name, data)
        write_json(self.path / "checkpoints" / f"{name}.json", data)

    def save_dataset(self, data):
        self.db.save_dataset(self.id, data, self.evidence)
        write_json(self.path / "dataset.json", data)

    def load_dataset(self, default=None):
        missing = object()
        data = self.db.get_dataset(self.id, missing)
        if data is missing:
            data = read_json(self.path / "dataset.json", missing)
            if data is not missing:
                self.db.save_dataset(self.id, data, self.evidence)
        return default if data is missing else data

    def table(self, name, rows):
        write_json(self.output / "tables" / f"{name}.json", rows)
        path = self.output / "tables" / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(dict.fromkeys(k for row in rows for k in row)) or ["status"]
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                normalized = {}
                for k, v in row.items():
                    v = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                    # Prevent formula execution when downloaded CSVs are opened in Excel.
                    normalized[k] = "'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v
                writer.writerow(normalized)
