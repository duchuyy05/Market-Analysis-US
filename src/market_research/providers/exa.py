"""Exa search + source text/images in one bounded request; no generated summary."""
from copy import deepcopy

from .client import SourceError
from .web import SOURCE_DOMAINS
from ..common import safe_url


def search(client, query, sites=None, cutoff=None):
    params = {"query": query, "type": "auto", "numResults": 8, "userLocation": "US",
        "contents": {"text": {"maxCharacters": 4000}, "extras": {"imageLinks": 3}}}
    if sites:
        params["includeDomains"] = [SOURCE_DOMAINS[site] for site in sites]
    if cutoff:
        params["endPublishedDate"] = cutoff + "T23:59:59Z"
    envelope = client.request("exa", params, purpose="web_discovery")
    rows = envelope["response"].get("results")
    if not isinstance(rows, list):
        client.invalidate(envelope, "Exa thiếu danh sách results")
        raise SourceError("Exa thiếu danh sách results", provider="exa")
    # Keep raw provider fields/cache intact; normalize a separate extraction view.
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or not safe_url(row.get("url")):
            continue
        highlights = row.get("highlights") or []
        content = row.get("text")
        if not isinstance(content, str) or not content.strip():
            content = "\n".join(h for h in highlights if isinstance(h, str)) if isinstance(highlights, list) else ""
        extras = row.get("extras") or {}
        images = extras.get("imageLinks", []) if isinstance(extras, dict) else []
        normalized.append({"url": row["url"], "title": row.get("title"), "content": content,
            "published_date": row.get("publishedDate"), "score": row.get("score"),
            "image": safe_url(row.get("image")), "image_links": [u for u in images if isinstance(u, str) and safe_url(u)][:3]})
    result = deepcopy(envelope)
    result["response"]["results"] = normalized
    return result
