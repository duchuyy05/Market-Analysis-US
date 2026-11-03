"""SQLite is the primary structured store; JSON/CSV remain portable exports.

Connections are short-lived so HTTP/background threads never share a connection.
Whole-run and dataset updates are transactions. Historical products are actual
captured snapshots, not reconstructed prices or sales from Google Trends.
"""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import RLock

from ..common import ROOT, canonical_url, identity, now, read_json

_SCHEMA_LOCK = RLock()
_READY = set()
_RUN_ID = re.compile(r"[a-zA-Z0-9_-]{1,100}")


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def decode(value, default=None):
    return json.loads(value) if value is not None else default


def numeric(value):
    return value if type(value) in {int, float} and math.isfinite(value) else None


def product_identity(product):
    asin = product.get("asin")
    if isinstance(asin, str) and re.fullmatch(r"[a-zA-Z0-9]{10}", asin):
        return "amazon:" + asin.upper()
    source = str(product.get("source") or "unknown")
    provider_id = product.get("provider_product_id") or product.get("listing_id")
    if provider_id:
        return source + ":" + str(provider_id)
    url = canonical_url(product.get("url"))
    return source + ":url:" + url if url else source + ":local:" + str(product.get("product_id", "unknown"))


def merged_histories(data):
    """Keep candidate-wide observations; selected-direction revisions take precedence."""
    by_direction = {row["direction_id"]: row for row in data.get("keyword_histories", [])}
    by_direction.update({row["direction_id"]: row for row in data.get("histories", [])})
    return list(by_direction.values())


class Database:
    SCHEMA_VERSION = 2

    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.path = self.root / "data/market_research.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _SCHEMA_LOCK:
            if str(self.path) not in _READY or not self.path.exists():
                self._initialize()
                _READY.add(str(self.path))

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self):
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > self.SCHEMA_VERSION:
                raise RuntimeError("Database được tạo bởi phiên bản mới hơn; không tự hạ schema")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT,
                    status TEXT NOT NULL, mode TEXT, category TEXT, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS stages (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL, status TEXT, started_at TEXT, finished_at TEXT,
                    elapsed_seconds REAL, attempts INTEGER, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,stage)
                );
                CREATE TABLE IF NOT EXISTS api_calls (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL, provider TEXT, engine TEXT, purpose TEXT,
                    requested_at TEXT, status TEXT, cost_usd REAL, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,ordinal)
                );
                CREATE TABLE IF NOT EXISTS evidence (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    evidence_id TEXT NOT NULL, kind TEXT, url TEXT, retrieved_at TEXT,
                    raw_file TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(run_id,evidence_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    stage TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,stage)
                );
                CREATE TABLE IF NOT EXISTS datasets (
                    run_id TEXT PRIMARY KEY REFERENCES runs(run_id) ON DELETE CASCADE,
                    updated_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    at TEXT, stage TEXT, event TEXT, message TEXT, payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workspace_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS keywords (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    keyword_id TEXT NOT NULL, niche_id TEXT, keyword TEXT, measurement_query TEXT,
                    origin TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(run_id,keyword_id)
                );
                CREATE TABLE IF NOT EXISTS niches (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    niche_id TEXT NOT NULL, name TEXT, customer_hypothesis TEXT,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id,niche_id)
                );
                CREATE TABLE IF NOT EXISTS directions (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    direction_id TEXT NOT NULL, niche_id TEXT, keyword_id TEXT,
                    keyword TEXT, measurement_query TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,direction_id)
                );
                CREATE TABLE IF NOT EXISTS keyword_screening (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    keyword_id TEXT NOT NULL, measurement_query TEXT, status TEXT,
                    relative_interest REAL, growth_pct REAL, score REAL, rank INTEGER,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id,keyword_id)
                );
                CREATE TABLE IF NOT EXISTS product_snapshots (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    product_id TEXT NOT NULL, identity_key TEXT NOT NULL, source TEXT,
                    asin TEXT, provider_product_id TEXT, observed_at TEXT, title TEXT, url TEXT,
                    price REAL, currency TEXT, rating REAL, review_count INTEGER,
                    purchase_lower_bound REAL, variant_json TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,product_id)
                );
                CREATE TABLE IF NOT EXISTS offer_snapshots (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    offer_id TEXT NOT NULL, product_id TEXT, identity_key TEXT,
                    observed_at TEXT, price REAL, currency TEXT, merchant TEXT,
                    variant_json TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(run_id,offer_id)
                );
                CREATE TABLE IF NOT EXISTS reviews (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    review_id TEXT NOT NULL, product_id TEXT, asin TEXT, kind TEXT,
                    rating REAL, published_at TEXT, body TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,review_id)
                );
                CREATE TABLE IF NOT EXISTS trend_observations (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    direction_id TEXT NOT NULL, measurement_query TEXT, year INTEGER NOT NULL,
                    month INTEGER NOT NULL, value REAL, status TEXT, observed_days INTEGER,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id,direction_id,year,month)
                );
                CREATE TABLE IF NOT EXISTS forecast_backtests (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    direction_id TEXT NOT NULL, fold_id TEXT NOT NULL, test_year INTEGER,
                    mae REAL, baseline_mae REAL, train_years_json TEXT, payload_json TEXT NOT NULL,
                    PRIMARY KEY(run_id,direction_id,fold_id)
                );
                CREATE TABLE IF NOT EXISTS forecast_values (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    direction_id TEXT NOT NULL, year INTEGER NOT NULL, month INTEGER NOT NULL,
                    prediction REAL, observed REAL, observation_status TEXT,
                    payload_json TEXT NOT NULL, PRIMARY KEY(run_id,direction_id,year,month)
                );
                CREATE TABLE IF NOT EXISTS imports (
                    source_key TEXT PRIMARY KEY, imported_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_stage ON events(run_id,stage,at);
                CREATE INDEX IF NOT EXISTS idx_product_identity ON product_snapshots(identity_key,observed_at);
                CREATE INDEX IF NOT EXISTS idx_product_asin ON product_snapshots(asin,observed_at);
                CREATE INDEX IF NOT EXISTS idx_offer_identity ON offer_snapshots(identity_key,observed_at);
                CREATE INDEX IF NOT EXISTS idx_trends_query ON trend_observations(measurement_query,year,month);
                CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(run_id,product_id);
                CREATE INDEX IF NOT EXISTS idx_api_provider ON api_calls(run_id,provider,engine);
            """)
            conn.execute("PRAGMA user_version=" + str(self.SCHEMA_VERSION))

    def _get(self, table, run_id, default=None):
        if table not in {"runs", "datasets"}:
            raise ValueError("Unknown database collection")
        with self.connection() as conn:
            row = conn.execute("SELECT payload_json FROM " + table + " WHERE run_id=?", (run_id,)).fetchone()
        return decode(row[0], default) if row else default

    def get_manifest(self, run_id, default=None):
        return self._get("runs", run_id, default)

    def list_runs(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT payload_json FROM runs ORDER BY created_at DESC,run_id DESC").fetchall()
        return [decode(row[0]) for row in rows]

    def save_run(self, manifest, evidence=None):
        run_id = manifest.get("run_id")
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("Mã nghiên cứu không hợp lệ")
        with self.connection() as conn:
            conn.execute("""INSERT INTO runs(run_id,created_at,updated_at,status,mode,category,payload_json)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET
                created_at=excluded.created_at,updated_at=excluded.updated_at,status=excluded.status,
                mode=excluded.mode,category=excluded.category,payload_json=excluded.payload_json""",
                (run_id, manifest.get("created_at"), manifest.get("updated_at"), manifest.get("status", "pending"), manifest.get("mode"),
                 manifest.get("summary", {}).get("category"), encode(manifest)))
            conn.execute("DELETE FROM stages WHERE run_id=?", (run_id,))
            for stage, state in manifest.get("stages", {}).items():
                conn.execute("INSERT INTO stages VALUES(?,?,?,?,?,?,?,?)", (run_id, stage, state.get("status"), state.get("started_at"),
                    state.get("finished_at"), numeric(state.get("elapsed_seconds")), state.get("attempts"), encode(state)))
            conn.execute("DELETE FROM api_calls WHERE run_id=?", (run_id,))
            for ordinal, event in enumerate(manifest.get("usage", [])):
                conn.execute("INSERT INTO api_calls VALUES(?,?,?,?,?,?,?,?,?)", (run_id, ordinal, event.get("provider"), event.get("engine"),
                    event.get("purpose"), event.get("requested_at"), event.get("status"), numeric(event.get("cost_usd")), encode(event)))
            if evidence is not None:
                self._save_evidence(conn, run_id, evidence)

    def _save_evidence(self, conn, run_id, evidence):
        conn.execute("DELETE FROM evidence WHERE run_id=?", (run_id,))
        for eid, row in evidence.items():
            conn.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?)", (run_id, eid, row.get("kind"), row.get("url"), row.get("retrieved_at"), row.get("raw_file"), encode(row)))

    def get_evidence(self, run_id, default=None):
        with self.connection() as conn:
            exists = conn.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            rows = conn.execute("SELECT evidence_id,payload_json FROM evidence WHERE run_id=?", (run_id,)).fetchall()
        return {r[0]: decode(r[1]) for r in rows} if exists else default

    def save_checkpoint(self, run_id, stage, data):
        with self.connection() as conn:
            conn.execute("INSERT INTO checkpoints VALUES(?,?,?,?) ON CONFLICT(run_id,stage) DO UPDATE SET updated_at=excluded.updated_at,payload_json=excluded.payload_json",
                         (run_id, stage, now(), encode(data)))

    def get_checkpoint(self, run_id, stage, default=None):
        with self.connection() as conn:
            row = conn.execute("SELECT payload_json FROM checkpoints WHERE run_id=? AND stage=?", (run_id, stage)).fetchone()
        return decode(row[0], default) if row else default

    def append_event(self, run_id, record):
        event_id = str(record.get("id") or identity("event", run_id, record))
        with self.connection() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)", (event_id, run_id, record.get("at"), record.get("stage"),
                record.get("event"), record.get("message"), encode(record)))
            return cursor.rowcount > 0

    def list_events(self, run_id, stage=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Giới hạn log phải từ 1 đến 1000")
        sql, params = "SELECT payload_json FROM events WHERE run_id=?", [run_id]
        if stage is not None:
            sql += " AND stage=?"
            params.append(stage)
        sql += " ORDER BY at DESC,rowid DESC LIMIT ?"
        params.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [decode(row[0]) for row in reversed(rows)]

    def save_workspace(self, value):
        with self.connection() as conn:
            conn.execute("INSERT INTO workspace_state VALUES(1,?,?) ON CONFLICT(singleton) DO UPDATE SET updated_at=excluded.updated_at,payload_json=excluded.payload_json", (now(), encode(value)))

    def get_workspace(self, default=None):
        with self.connection() as conn:
            row = conn.execute("SELECT payload_json FROM workspace_state WHERE singleton=1").fetchone()
        return decode(row[0], default) if row else default

    def get_dataset(self, run_id, default=None):
        return self._get("datasets", run_id, default)

    def save_dataset(self, run_id, data, evidence=None):
        stamp = now()
        with self.connection() as conn:
            conn.execute("INSERT INTO datasets VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET updated_at=excluded.updated_at,payload_json=excluded.payload_json", (run_id, stamp, encode(data)))
            if evidence is not None:
                self._save_evidence(conn, run_id, evidence)
            for table in ("niches", "directions", "keywords", "keyword_screening", "product_snapshots", "offer_snapshots", "reviews", "trend_observations", "forecast_backtests", "forecast_values"):
                conn.execute("DELETE FROM " + table + " WHERE run_id=?", (run_id,))
            for index, row in enumerate(data.get("config", {}).get("niches", [])):
                conn.execute("INSERT INTO niches VALUES(?,?,?,?,?)", (run_id, row.get("id") or str(index), row.get("name"), row.get("customer_hypothesis"), encode(row)))
            for row in data.get("directions", []):
                conn.execute("INSERT INTO directions VALUES(?,?,?,?,?,?,?)", (run_id, row["id"], row.get("niche_id"), row.get("keyword_id"), row.get("keyword"), row.get("measurement_query") or row.get("keyword"), encode(row)))
            measures = {r.get("keyword_id"): r for r in data.get("keyword_screening", [])}
            for row in data.get("keywords", []):
                query = measures.get(row.get("id"), {}).get("measurement_query") or row.get("text")
                conn.execute("INSERT INTO keywords VALUES(?,?,?,?,?,?,?)", (run_id, row["id"], row.get("niche_id"), row.get("text"), query, row.get("origin"), encode(row)))
            for row in data.get("keyword_screening", []):
                conn.execute("INSERT OR REPLACE INTO keyword_screening VALUES(?,?,?,?,?,?,?,?,?)", (run_id, row["keyword_id"], row.get("measurement_query", row.get("keyword")), row.get("status"),
                    numeric(row.get("relative_interest")), numeric(row.get("growth_pct")), numeric(row.get("score")), row.get("rank"), encode(row)))
            products = {p["product_id"]: p for p in data.get("products", [])}
            for pid, row in products.items():
                conn.execute("INSERT INTO product_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (run_id, pid, product_identity(row), row.get("source"),
                    row.get("asin"), row.get("provider_product_id"), row.get("observed_at"), row.get("title"), row.get("url"), numeric(row.get("price")),
                    row.get("currency"), numeric(row.get("rating")), numeric(row.get("review_count")), numeric(row.get("purchase_lower_bound")), encode(row.get("variant")), encode(row)))
            for ordinal, row in enumerate(data.get("offers", [])):
                product = products.get(row.get("product_id"), row)
                conn.execute("INSERT OR REPLACE INTO offer_snapshots VALUES(?,?,?,?,?,?,?,?,?,?)", (run_id, row.get("offer_id") or str(ordinal), row.get("product_id"), product_identity(product),
                    row.get("observed_at"), numeric(row.get("price")), row.get("currency"), row.get("merchant"), encode(row.get("variant")), encode(row)))
            for ordinal, row in enumerate(data.get("reviews", [])):
                conn.execute("INSERT OR REPLACE INTO reviews VALUES(?,?,?,?,?,?,?,?,?)", (run_id, row.get("id") or str(ordinal), row.get("product_id"), row.get("asin"), row.get("kind"), numeric(row.get("rating")), row.get("published_at"), row.get("text"), encode(row)))
            directions = {d["id"]: d for d in data.get("directions", [])}
            for history in merged_histories(data):
                did = history["direction_id"]
                direction = directions.get(did, {})
                query = history.get("measurement_query") or direction.get("measurement_query") or direction.get("keyword")
                for row in history.get("monthly", []):
                    observation = {**row, "measurement_query": query, "keyword_id": history.get("keyword_id") or direction.get("keyword_id"),
                                   "evidence_ids": history.get("evidence_ids", []), "normalization_context": history.get("normalization_context", {})}
                    conn.execute("INSERT OR REPLACE INTO trend_observations VALUES(?,?,?,?,?,?,?,?,?)", (run_id, did, query, row["year"], row["month"], numeric(row.get("value")), row.get("status"), row.get("observed_days"), encode(observation)))
                for row in history.get("forecast", []):
                    conn.execute("INSERT OR REPLACE INTO forecast_values VALUES(?,?,?,?,?,?,?,?)", (run_id, did, row["year"], row["month"], numeric(row.get("prediction")), numeric(row.get("observed")), row.get("observation_status"), encode(row)))
                backtest = history.get("backtest") or {}
                if backtest:
                    self._backtest(conn, run_id, did, "summary", backtest)
                    for index, fold in enumerate(backtest.get("folds", [])):
                        self._backtest(conn, run_id, did, str(index), fold)
                validation = history.get("validation") or {}
                if validation:
                    self._backtest(conn, run_id, did, "validation-summary", validation)
                    for index, fold in enumerate(validation.get("folds", [])):
                        self._backtest(conn, run_id, did, "validation-" + str(index), fold)

    def _backtest(self, conn, run_id, direction_id, fold_id, row):
        # The rolling validation keeps metrics in nested dictionaries; legacy
        # one-year backtests store the same values directly on the fold.
        metrics = row.get("metrics") or {}
        baseline = row.get("baseline_metrics") or {}
        conn.execute("INSERT INTO forecast_backtests VALUES(?,?,?,?,?,?,?,?)", (run_id, direction_id, fold_id, row.get("test_year"), numeric(metrics.get("mae", row.get("mae"))),
            numeric(baseline.get("mae", row.get("seasonal_naive_mae", row.get("baseline_mae")))), encode(row.get("train_years", [])), encode(row)))

    def product_history(self, identity_key, *, limit=200, before=None):
        if isinstance(identity_key, str) and re.fullmatch(r"[a-zA-Z0-9]{10}", identity_key):
            identity_key = "amazon:" + identity_key.upper()
        if type(limit) is not int or not 1 <= limit <= 5000:
            raise ValueError("Giới hạn lịch sử sản phẩm không hợp lệ")
        sql, args = "SELECT run_id,payload_json FROM product_snapshots WHERE identity_key=?", [identity_key]
        if before:
            sql += " AND observed_at<=?"
            args.append(before + "T23:59:59.999999Z" if isinstance(before, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", before) else before)
        sql += " ORDER BY observed_at,run_id LIMIT ?"
        args.append(limit)
        with self.connection() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [{**decode(r[1]), "run_id": r[0], "identity_key": identity_key} for r in rows]

    def product_stability(self, product, *, before=None):
        key = product_identity(product) if isinstance(product, dict) else product
        rows = self.product_history(key, before=before)
        dates = {str(p.get("observed_at", ""))[:10] for p in rows if p.get("observed_at")}
        years = sorted({int(value[:4]) for value in dates if re.match(r"^\d{4}-", value)})
        price_groups = {}
        for row in rows:
            if row.get("price") is None or not row.get("currency"):
                continue
            signature = encode([row.get("currency"), row.get("variant"), row.get("merchant")])
            group = price_groups.setdefault(signature, {"currency": row["currency"], "variant": row.get("variant"), "merchant": row.get("merchant"), "values": []})
            group["values"].append(row["price"])
        prices = [{"currency": g["currency"], "variant": g["variant"], "merchant": g["merchant"], "observations": len(g["values"]), "min": min(g["values"]), "max": max(g["values"])} for g in price_groups.values()]
        return {"identity_key": key, "status": "available" if len(years) >= 2 else "insufficient_history",
                "snapshot_count": len(rows), "distinct_dates": len(dates), "observed_years": years,
                "first_observed_at": rows[0].get("observed_at") if rows else None,
                "last_observed_at": rows[-1].get("observed_at") if rows else None, "price_groups": prices,
                "note": "Chỉ dùng snapshot sản phẩm đã thu thập thật. Chưa có bản ghi năm trước không đồng nghĩa sản phẩm biến mất; Trends không tạo lại giá/doanh số Amazon quá khứ. Nhóm giá tách tiền tệ/biến thể/người bán; không tự kết luận ổn định thương mại."}

    def migrate_legacy(self, force=False):
        """Idempotent copy into SQLite. Source files are never deleted or mutated."""
        counts = {"runs": 0, "datasets": 0, "checkpoints": 0, "events": 0, "workspace": 0, "errors": []}
        for path in sorted((self.root / "data/runs").glob("*/manifest.json")):
            try:
                result = self.import_run(path.parent, force=force)
                for key in ("runs", "datasets", "checkpoints", "events"):
                    counts[key] += result[key]
            except (ValueError, OSError, sqlite3.Error) as error:
                counts["errors"].append({"run_id": path.parent.name, "reason": type(error).__name__ + ": " + str(error)[:200]})
        workspace = self.root / "data/workspace/state.json"
        if workspace.is_file() and (force or self.get_workspace() is None):
            self.save_workspace(read_json(workspace))
            counts["workspace"] = 1
        return counts

    def import_run(self, path, force=False):
        path = Path(path).resolve()
        boundary = (self.root / "data/runs").resolve()
        if not path.is_relative_to(boundary) or not _RUN_ID.fullmatch(path.name):
            raise ValueError("Đường dẫn import run không hợp lệ")
        result = {"runs": 0, "datasets": 0, "checkpoints": 0, "events": 0}
        manifest = read_json(path / "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("run_id") != path.name:
            raise ValueError("Manifest import không khớp run_id")
        exists = self.get_manifest(path.name)
        if force or exists is None:
            self.save_run(manifest, read_json(path / "evidence.json", {}))
            result["runs"] = 1
        # Existing DB records take precedence; fill only missing legacy parts.
        for checkpoint in (path / "checkpoints").glob("*.json"):
            if force or self.get_checkpoint(path.name, checkpoint.stem) is None:
                self.save_checkpoint(path.name, checkpoint.stem, read_json(checkpoint))
                result["checkpoints"] += 1
        dataset = path / "dataset.json"
        if dataset.is_file() and (force or self.get_dataset(path.name) is None):
            legacy_evidence = read_json(path / "evidence.json", {})
            imported_evidence = legacy_evidence if force else {**legacy_evidence, **self.get_evidence(path.name, {})}
            self.save_dataset(path.name, read_json(dataset), imported_evidence)
            result["datasets"] = 1
        log = path / "events.jsonl"
        if log.is_file():
            with log.open(encoding="utf-8-sig") as stream, self.connection() as conn:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict):
                        eid = str(event.get("id") or identity("event", path.name, event))
                        cursor = conn.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)", (eid, path.name, event.get("at"), event.get("stage"), event.get("event"), event.get("message"), encode(event)))
                        result["events"] += cursor.rowcount > 0
        with self.connection() as conn:
            conn.execute("INSERT INTO imports VALUES(?,?,?) ON CONFLICT(source_key) DO UPDATE SET imported_at=excluded.imported_at,payload_json=excluded.payload_json", ("run:" + path.name, now(), encode(result)))
        return result


def migrate_legacy(root=ROOT, force=False):
    return Database(root).migrate_legacy(force=force)
