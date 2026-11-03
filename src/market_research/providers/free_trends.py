"""Small unofficial, keyless Trends HTTP adapter. No paid fallback or block bypass.

Each logical operation uses explore + one widget request. Client counts both HTTP
requests separately, shares a fresh cache and stops the branch on any HTTP error.
The public endpoint may change or reject requests; callers retain missing data.
"""
import json
import time
from http.cookiejar import CookieJar
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

from ..control import check_cancel
from .client import SourceError

BASE = "https://trends.google.com/trends/api/"


def decode(body):
    text = body.decode("utf-8-sig").lstrip()
    if text.startswith(")]}'"):
        text = text[4:].lstrip(",\n\r ")
    return json.loads(text)


def send(client, params):
    if not hasattr(client, "_trends_opener"):
        client._trends_opener = build_opener(HTTPCookieProcessor(CookieJar()))
    delay = max(0, 2 - (time.monotonic() - getattr(client, "_trends_last", 0)))
    if delay:
        if client.cancel_event is None:
            time.sleep(delay)
        else:
            client.cancel_event.wait(delay)
    check_cancel(client.cancel_event)
    payload = {"hl": "en-US", "tz": 0, "req": json.dumps(params["req"], separators=(",", ":"))}
    if params.get("widget_code"):
        payload["token"] = params["widget_code"]
    request = Request(BASE + params["endpoint"] + "?" + urlencode(payload), headers={"Accept-Language": "en-US,en;q=0.9", "User-Agent": "Mozilla/5.0", "Referer": "https://trends.google.com/trends/explore"})
    client._trends_last = time.monotonic()
    with client._trends_opener.open(request, timeout=client.config["limits"]["timeout_seconds"]) as response:
        return decode(response.read())


def fetch(client, queries, date_range, related=False):
    if not 1 <= len(queries) <= 5:
        raise ValueError("Trends comparison cần 1–5 keyword")
    req = {"comparisonItem": [{"keyword": q, "geo": "US", "time": date_range} for q in queries], "category": 0, "property": ""}
    explored = client.request("google_trends_free", {"endpoint": "explore", "req": req})
    widgets = explored["response"].get("widgets") or []
    if not isinstance(widgets, list):
        client.invalidate(explored, "Google Trends trả danh sách widget sai định dạng")
        raise SourceError("Google Trends trả danh sách widget sai định dạng")
    widget = next((w for w in widgets if isinstance(w, dict) and str(w.get("id", "")).startswith("RELATED_QUERIES" if related else "TIMESERIES")), None)
    if not widget or not isinstance(widget.get("request"), dict) or not widget.get("widget_code"):
        client.invalidate(explored, "Google Trends không trả widget hợp lệ")
        raise SourceError("Google Trends không trả widget hợp lệ")
    received = client.request("google_trends_free", {"endpoint": "widgetdata/relatedsearches" if related else "widgetdata/multiline", "req": widget["request"], "widget_code": widget["widget_code"]})
    response = received["response"].get("default", {})
    if not isinstance(response, dict):
        client.invalidate({**received, "request_raw_files": [explored["raw_file"]]}, "Google Trends trả widget sai định dạng")
        raise SourceError("Google Trends trả widget sai định dạng")
    if related:
        lists = response.get("rankedList", [])
        body = {"related_queries": {kind: [{"query": r.get("query"), "value": r.get("formattedValue", r.get("value"))} for r in (lists[index].get("rankedKeyword", []) if len(lists) > index else [])] for index, kind in enumerate(("top", "rising"))}}
    else:
        timeline = []
        for row in response.get("timelineData", []):
            partial = row.get("isPartial", False)
            timeline.append({"timestamp": row.get("time"), "date": row.get("formattedTime"), "isPartial": any(partial) if isinstance(partial, list) else bool(partial),
                             "values": [{"query": q, "extracted_value": row.get("value", [])[i]} for i, q in enumerate(queries) if len(row.get("value", [])) > i]})
        body = {"interest_over_time": {"timeline_data": timeline}}
    return {**received, "request_raw_files": [explored["raw_file"], received["raw_file"]],
            "parameters": {"q": ",".join(queries), "date": date_range, "geo": "US", "data_type": "RELATED_QUERIES" if related else "TIMESERIES"}, "response": body}
