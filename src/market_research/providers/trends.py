"""One Trends contract with validated responses and bounded automatic recovery."""
import math
from urllib.parse import urlencode

from .client import SourceError, BudgetExceeded


def _log(client, event, message, **details):
    logger = getattr(client, "log", None)
    if callable(logger):
        logger(event, message, **details)


def _require_quality(client, envelope, queries, related, quality, label):
    reason = None
    try:
        if not _usable(envelope, queries, related):
            reason = label + " trả dữ liệu rỗng hoặc không đúng chuỗi truy vấn"
        elif quality is not None and not quality(envelope):
            reason = label + " chưa đủ độ phủ hoặc anchor chưa có tín hiệu để sàng lọc"
    except (ValueError, KeyError, TypeError, AttributeError):
        reason = label + " trả schema chuỗi dữ liệu không hợp lệ"
    if reason:
        invalidate = getattr(client, "invalidate", None)
        if callable(invalidate):
            invalidate(envelope, reason)
        raise SourceError(reason)


def _usable(envelope, queries, related=False):
    """An HTTP 200 or an empty widget is not a completed Trends observation."""
    body = envelope.get("response", {})
    if related:
        rows = body.get("related_queries") or {}
        return any(isinstance(item, dict) and isinstance(item.get("query"), str) and item["query"].strip()
                   for kind in ("top", "rising") for item in (rows.get(kind) or []))
    timeline = (body.get("interest_over_time") or {}).get("timeline_data") or []
    observed = set()
    for point in timeline:
        if not isinstance(point, dict):
            continue
        try:
            int(point["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        for item in point.get("values") or []:
            if not isinstance(item, dict) or item.get("query") not in queries or isinstance(item.get("extracted_value"), bool):
                continue
            try:
                value = float(item.get("extracted_value"))
            except (ValueError, TypeError):
                continue
            if math.isfinite(value) and value >= 0:
                observed.add(item["query"])
    return set(queries).issubset(observed)


def _fetch(client, queries, date_range, *, related=False, purpose, quality=None):
    if not 1 <= len(queries) <= 5:
        raise ValueError("Trends comparison cần 1–5 keyword")
    # Missing mode belongs to frozen pre-free runs and retains its paid adapter.
    mode = client.config.get("trends", {}).get("provider", "serpapi")
    free_error = None
    if mode in {"free", "auto"}:
        try:
            from .free_trends import fetch
            envelope = fetch(client, queries, date_range, related=related)
            _require_quality(client, envelope, queries, related, quality, "Trends miễn phí")
            _log(client, "trends_received", "Đã có dữ liệu Trends miễn phí", queries=queries, purpose=purpose, raw_file=envelope.get("raw_file"))
            return {**envelope, "requested_provider": mode, "selected_provider": "free", "recovered": False}
        except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
            if mode == "free":
                raise
            free_error = str(error)
            _log(client, "trends_recovery", "Trends miễn phí chưa có dữ liệu; kiểm tra nguồn SerpApi dự phòng", queries=queries, purpose=purpose, reason=free_error)
    if related and mode == "auto" and client.config["limits"].get("trends_related_requests", 0) <= 0:
        _log(client, "trends_optional_skipped", "Không dùng SerpApi cho related; giữ lượt cho phép đo và sản phẩm", queries=queries, reason=free_error)
        raise BudgetExceeded("Related miễn phí chưa có dữ liệu; trần Related trả phí bằng 0 để giữ lượt cho sàng lọc")
    params = {"engine": "google_trends", "q": ",".join(queries), "geo": "US", "hl": "en", "date": date_range,
              "data_type": "RELATED_QUERIES" if related else "TIMESERIES"}
    if not related:
        params["tz"] = 0
    try:
        envelope = client.request("serpapi", params, purpose=purpose)
        _require_quality(client, envelope, queries, related, quality, "SerpApi Trends")
        _log(client, "trends_recovered" if free_error else "trends_received", "Đã có dữ liệu Trends từ SerpApi", queries=queries,
             purpose=purpose, recovered_from=free_error, raw_file=envelope.get("raw_file"))
        return {**envelope, "requested_provider": mode, "selected_provider": "serpapi", "recovered": free_error is not None,
                "recovery_reason": free_error}
    except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
        _log(client, "trends_unavailable", "Nguồn Trends dự phòng chưa thành công", queries=queries, purpose=purpose,
             reason=str(error), free_reason=free_error)
        if free_error and not isinstance(error, BudgetExceeded):
            raise SourceError(f"Trends miễn phí: {free_error}; SerpApi dự phòng: {error}") from error
        raise


def related(client, query, cutoff, date_range=None):
    """Discover related designs within the supplied window when one is selected."""
    return _fetch(client, [query], date_range or f"{int(cutoff[:4])-1}-01-01 {cutoff}", related=True, purpose="trends_related")


def history(client, query, config):
    return history_many(client, [query], config)


def history_many(client, queries, config):
    return _fetch(client, queries, f"{min(config['history_years'])}-01-01 {config['as_of_date']}", purpose="trends_history")


def history_range(client, queries, config, date_range, quality=None):
    """One exact seasonal window; never broaden it to include other months."""
    return _fetch(client, queries, date_range, purpose="trends_history", quality=quality)


def compare(client, queries, config, date_range, quality=None):
    return _fetch(client, queries, date_range, purpose="trends_screen", quality=quality)


def public_url(query, parameters):
    return "https://trends.google.com/trends/explore?" + urlencode({"q": query, "geo": "US", "date": parameters["date"]})
