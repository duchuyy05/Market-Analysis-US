"""Optional qualitative commentary, validated independently of the main report."""
import re
from ..llm.client import complete
from ..providers.client import SourceError


def generate(run, client, config, data):
    output = {}
    if config["mode"] == "offline" or not config["llm"]["enabled"] or not config["llm"]["commentary"]:
        return output
    for niche in config["niches"]:
        dids = {d["id"] for d in data["directions"] if d["niche_id"] == niche["id"]}
        products = [p for p in data["products"] if dids.intersection(p["direction_ids"])]
        pids = {p["product_id"] for p in products}
        reviews = sorted([r for r in data["reviews"] if r["product_id"] in pids], key=lambda r: (r["kind"] != "full", r["rating"] is None, r["rating"] or 0))[:6]
        ids = {e for p in products[:4] for e in p["evidence_ids"]} | {e for r in reviews for e in r["evidence_ids"]}
        cards = {eid: {k: run.evidence[eid].get(k) for k in ("kind", "excerpt", "asin")} for eid in ids}
        try:
            result = complete(client, "commentary", {"niche": niche["name"], "evidence": cards})
            accepted = []
            for item in result.get("insights", [])[:3]:
                if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not 30 <= len(item["text"]) <= 1200 or re.search(r"\d|https?://|<[^>]+>", item["text"]):
                    continue
                refs = item.get("evidence_ids")
                if not isinstance(refs, list) or not 1 <= len(refs) <= 3 or any(e not in cards for e in refs):
                    continue
                quote = item.get("quote")
                review_refs = [e for e in refs if cards[e]["kind"] == "review"]
                if review_refs and (not isinstance(quote, dict) or quote.get("id") not in review_refs or not isinstance(quote.get("text"), str) or len(quote["text"]) < 18 or quote["text"] not in cards[quote["id"]]["excerpt"]):
                    continue
                if not review_refs and quote is not None:
                    continue
                accepted.append({"text": item["text"], "evidence_ids": refs, "quote": quote})
            output[niche["id"]] = accepted
            if not accepted:
                run.warn("LLM không có nhận định hợp lệ cho " + niche["name"] + "; báo cáo Python vẫn đầy đủ bảng và idea")
        except (SourceError, ValueError, TypeError, AttributeError) as error:
            run.warn(f"Diễn giải / {niche['name']}: {error}")
    return output
