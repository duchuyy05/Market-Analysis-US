"""Clean and deduplicate the Tavily sources used by the current collector."""
import html
import json
import re
from urllib.parse import urlsplit, urlunsplit


def canonical_url(url):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip('/'), '', ''))


def visible_web_text(value):
    """Keep page text, excluding terms that occur only in image URLs/markup."""
    value = html.unescape(value or "")
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value.replace("**", "").replace("\u200b", "")).strip()


def web_records(output, manifest):
    records = {}
    for label, path in manifest["sources"].items():
        if not label.startswith("tavily_"):
            continue
        envelope = json.loads((output / path).read_text(encoding="utf-8"))
        for result in envelope["response"].get("results", []):
            url = result.get("url", "")
            if not url.startswith("https://"):
                continue
            key = canonical_url(url)
            if key not in records:
                records[key] = {"source_id": f"W{len(records) + 1}", "title": result.get("title"), "source_url": url,
                    "snippet": result.get("content"), "page_content": result.get("raw_content"),
                    "published_date_estimated": result.get("published_date"), "discovery_queries": [],
                    "source_raw_files": [], "collected_at_utc": envelope["fetched_at_utc"],
                    "source_role": "Web discovery/context; not automatically a customer review or sales statistic"}
            record = records[key]
            record["discovery_queries"].append(envelope["parameters"]["query"])
            record["source_raw_files"].append(path)
            if not record["page_content"] and result.get("raw_content"):
                record["page_content"] = result["raw_content"]
    return list(records.values())
