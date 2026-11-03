"""Small shared helpers; no provider or workflow dependencies."""
import hashlib
import json
import math
import re
from threading import RLock
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[2]
_JSON_LOCK = RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def today():
    return datetime.now(timezone(timedelta(hours=7))).date()


def identity(prefix, *values):
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return f"{prefix}-{digest}"


def read_json(path, default=None):
    path = Path(path)
    # A Windows reader can prevent os.replace while its file handle is open.
    with _JSON_LOCK:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    with _JSON_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        try:
            for attempt in range(5):
                try:
                    temporary.replace(path)
                    break
                except PermissionError as error:
                    # Also tolerate brief locks held by another local process.
                    if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 4:
                        raise
                    time.sleep(0.01 * 2**attempt)
        finally:
            temporary.unlink(missing_ok=True)


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def text(value):
    if value is None:
        return ""
    if isinstance(value, dict):
        return "; ".join(f"{k}: {text(v)}" for k, v in value.items())
    if isinstance(value, list):
        return "; ".join(text(v) for v in value)
    return re.sub(r"\s+", " ", str(value)).strip()


def safe_url(value):
    try:
        parts = urlsplit(value or "")
        return value if parts.scheme in {"http", "https"} and parts.hostname and not parts.username else None
    except ValueError:
        return None


def canonical_url(value):
    if not safe_url(value):
        return None
    parts = urlsplit(value)
    asin = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", parts.path, re.I)
    if asin and (parts.hostname or "").lower() in {"amazon.com", "www.amazon.com", "m.amazon.com"}:
        return "https://www.amazon.com/dp/" + asin[1].upper()
    # Keep identity-bearing query parameters; remove tracking only.
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k.lower() not in {"ref", "tag", "gclid", "fbclid"}]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def tokens(value):
    return set(re.findall(r"[a-z0-9]+", value.lower())) - {"the", "for", "with", "and", "of", "a", "an", "best", "new", "2026"}
