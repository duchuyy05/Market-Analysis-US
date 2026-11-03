"""Filter weak public pages and retry focused searches only when useful data is missing."""
import re
import unicodedata
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from ..common import identity, safe_url, tokens
from ..providers import web
from ..providers.client import SourceError, BudgetExceeded
from ..llm.client import complete
from .trend_queries import measurement_query, research_period, research_focus, discovery_period_query, product_context, DISCOVERY_QUERY_VERSION
from ..business.domain import prompt_context, active, classify
from .design_content import content_mode, verified_source_design


def normalize(text):
    return " ".join(str(text).casefold().split())


def poor_page(item, product_words):
    parts = urlsplit(item["url"])
    title = str(item.get("title") or "")
    body = unicodedata.normalize("NFKC", title + " " + str(item.get("content") or ""))
    if parts.path in {"", "/"}:
        return "Trang chủ chung, chưa có mẫu hay ý tưởng sản phẩm cụ thể"
    if re.search(r"recalls?|angeltree|privacy|polic(?:y|ies)|guidelines|terms-of-service|careers", parts.path, re.I):
        return "Trang thu hồi/tổ chức/chính sách, không phải nguồn khám phá sản phẩm theo brief"
    if re.search(r"(?:for sale|pasalo).{0,45}(?:printing|business)|printing business.{0,35}(?:sale|pasalo)|\bpasabuy\b", body, re.I):
        return "Tin sang nhượng dịch vụ/kinh doanh hoặc mua hộ địa phương; không phải mẫu hàng cho nghiên cứu US"
    if re.search(r"\b(?:svg|dxf|digital download|digital products|print license|design bundle|drag & drop bundle)\b", body, re.I):
        return "File thiết kế/bundle số; chưa phải mẫu sản phẩm vật lý đối chiếu"
    overlap = product_words & set(re.findall(r"[a-z]+", body.lower()))
    if (parts.hostname or "").startswith("corporate.") and not overlap:
        return "Tin doanh nghiệp/PR chưa có loại sản phẩm liên quan; không dùng để tạo keyword"
    if re.search(r"bring.*(?:back|from|to)|living abroad|au pair|host family|buenos aires", title, re.I) and not overlap:
        return "Câu hỏi quà xuyên biên giới, thiếu liên hệ loại sản phẩm trong nghiên cứu US"
    score = item.get("score")
    if isinstance(score, (int, float)) and score < 0.12 and not overlap:
        return "Điểm tìm kiếm thấp và chưa thấy loại sản phẩm liên quan"
    return None


def literal_model_phrases(page, config):
    """Conservative source phrases when a model rewrites or repeats seeds.

    Every returned query is a contiguous phrase in the source (usually 2–4
    words, longer when preserving content names or actual slogan text). It is
    a new model mention, never a shortened measurement attached to an older,
    more specific candidate. No artist inference or word reordering occurs.
    """
    from ..business.domain import _POSITIVE
    from .keyword_expansion import product_key
    content = content_mode(config) == "designs"
    title = str(page.get("title") or "")
    if re.search(r"\b(?:svg|dxf|pdf|digital|download|template|printable)\b", title, re.I):
        return []
    texts = [title, str(page.get("excerpt") or "")]
    found, seen = [], set()
    leading = re.compile(r"^(?:(?:discover|explore|shop|find|buy|choose|our|your|a|an|the|unique|new|beautiful|stylish|timeless|custom|personalized|personalised)\s+|(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+(?=blank|different|unique|custom|printed)|create\s+your\s+own\s+)", re.I)
    for text in texts:
        for segment in re.split(r"[\n|:;,]|\s+[–—]\s+|\s+-\s+|(?<=[.!?])\s+", text):
            for category, pattern in _POSITIVE.items():
                if category == "phone_accessories":
                    pattern = r"\b(?:phone|iphone|smartphone|tablet)\s+(?:cases?|covers?|grips?|stands?|straps?|charms?)\b"
                for match in re.finditer(pattern, segment, re.I):
                    prefix = segment[:match.end()].strip()
                    # Marketing clauses before a product noun are not part of
                    # its search name. Preserve the literal remaining span.
                    before = segment[:match.start()]
                    stops = list(re.finditer(r"\b(?:for|with|including|features?|like)\s+", before, re.I))
                    if stops:
                        prefix = segment[stops[-1].end():match.end()].strip()
                    while leading.match(prefix):
                        prefix = leading.sub("", prefix, count=1)
                    phrase = " ".join(prefix.split()).strip(" .-'")
                    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", phrase, re.I)
                    if not phrase.isascii() or not 2 <= len(words) <= (12 if content else 4) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-/]*", phrase):
                        continue
                    if re.search(r"\b(?:svg|dxf|pdf|digital|download|template|printable|sale|price|review|best|top|viral|trending)\b", phrase, re.I):
                        continue
                    if re.match(r"\d+(?:in|inch|cm|mm)\b", phrase, re.I) or re.fullmatch(r"(?:uv|screen|sublimation|digital|dye|dtf|dtg|offset)\s+prints?", phrase, re.I):
                        continue
                    if re.fullmatch(r"(?:phone|iphone|smartphone|tablet)\s+(?:cases?|covers?|grips?|stands?|straps?|charms?)", phrase, re.I):
                        continue
                    # A source can list two separate products in one clause;
                    # do not concatenate them into a new search phrase.
                    joined = re.split(r"\b(?:and|or)\b", phrase, maxsplit=1, flags=re.I)
                    if len(joined) > 1 and any(re.search(p, joined[0], re.I) for p in _POSITIVE.values()):
                        continue
                    if product_context(phrase, config) or classify(phrase, config)["status"] != "allowed":
                        continue
                    key = product_key(phrase)
                    if key not in seen:
                        seen.add(key)
                        found.append({"keyword": phrase, "quote": phrase, "source_id": page.get("id")})
    return found[:3]


def harvest(run, client, config, niches, add):
    sites = config["discovery"]["sites"]
    if not config["sources"]["web"] or not sites:
        return [], [{"branch": "web", "status": "skipped"}], []
    bundles = [([s for s in sites if s in group], label) for group, label in
               (({"tiktok", "facebook"}, "social"), ({"etsy", "walmart", "ebay"}, "marketplaces"), ({"pinterest"}, "visual"))]
    bundles = [(ss, label) for ss, label in bundles if ss]
    contexts, excluded, seen = [], [], set()
    available = web.providers(client, config)
    blocked = {}
    provider_pages = {name: 0 for name in available}
    provider_queries = {name: 0 for name in available}
    if not available:
        return [], [{"branch": "web_provider", "status": "missing_key", "reason": "Thêm TAVILY_API_KEY hoặc EXA_API_KEY trong .env"}], []
    state = {s: {"branch": label, "sites": [s], "count": 0, "raw_count": 0, "filtered_count": 0, "queries": 0, "status": "empty"} for ss, label in bundles for s in ss}
    stop = {"gift", "gifts", "family", "parents", "christmas", "personalized", "custom", "for", "and", "the", "with"}
    product_words = {w for n in niches.values() for seed in n["seeds"] for w in re.findall(r"[a-z]+", seed.lower()) if len(w) > 3 and w not in stop}
    source_models = set()
    covered_niches = set()
    niche_words = {nid: set().union(*(tokens(seed) for seed in niche["seeds"])) - stop - {"custom", "printed", "design", "small", "mini", "logo", "name"}
                   for nid, niche in niches.items()}
    niche_categories = {nid: {classify(seed, config).get("category") for seed in niche["seeds"]} - {None}
                        for nid, niche in niches.items()}

    def collect(query, selected_sites, label, preferred=None):
        added = []
        order = sorted(available, key=lambda name: name != preferred) if preferred else available
        # Client checks cache before budget/key availability. Even a source at
        # its cap can replay an existing result without another HTTP request.
        candidates = [name for name in order if name not in blocked]
        envelope = None
        provider = None
        for name in candidates:
            try:
                envelope = web.search(client, query, selected_sites, provider=name) if name != "tavily" else web.search(client, query, selected_sites)
                provider = name
                provider_queries[name] += 1
                break
            except BudgetExceeded:
                continue
            except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
                blocked[name] = str(error)
                run.log("discover", "web_provider_fallback", "Nguồn chưa dùng được; chuyển nguồn khác trong trần còn lại", provider=name, reason=str(error), query=query)
        if envelope is None:
            reason = "; ".join(name + ": " + message for name, message in blocked.items()) or "Đã hết trần web của các nguồn đã chọn"
            for site in selected_sites:
                state[site].update(status="unavailable" if blocked else "limited", reason=reason)
            return []
        try:
            for site in selected_sites:
                state[site]["queries"] += 1
                state[site]["providers"] = sorted(set(state[site].get("providers", [])) | {provider})
            for item in envelope["response"].get("results", []):
                if not isinstance(item, dict) or not safe_url(item.get("url")):
                    continue
                source = web.source_for(item["url"])
                if source not in selected_sites:
                    continue
                state[source]["raw_count"] += 1
                if item["url"] in seen:
                    previous = next((page for page in contexts if page["url"] == item["url"]), None)
                    if previous:
                        previous["retrieval_providers"] = sorted(set(previous.get("retrieval_providers", [])) | {provider})
                        content = str(item.get("content") or "")[:4000]
                        if len(content) > len(previous["excerpt"]):
                            eid = run.add_evidence("public_web_discovery", item["url"], envelope["retrieved_at"], envelope["raw_file"], content,
                                platform=source, retrieval_provider=provider, audience_country="unverified", sales="unavailable")
                            previous["excerpt"] = content
                            previous["evidence_ids"] = sorted(set(previous["evidence_ids"]) | {eid})
                            previous["image"] = safe_url(item.get("image")) or previous.get("image")
                            previous["image_links"] = [url for url in item.get("image_links", []) if isinstance(url, str) and safe_url(url)][:3] if isinstance(item.get("image_links"), list) else previous.get("image_links", [])
                            added.append(previous)
                            provider_pages[provider] += 1
                    continue
                seen.add(item["url"])
                published = item.get("published_date")
                try:
                    stamp = str(published)[:10] if str(published)[:4].isdigit() else parsedate_to_datetime(published).date().isoformat()
                except (TypeError, ValueError, IndexError):
                    stamp = None
                reason = "Trang xuất bản sau ngày chốt" if stamp and stamp > config["as_of_date"] else poor_page(item, product_words)
                if reason:
                    state[source]["filtered_count"] += 1
                    excluded.append({"url": item["url"], "title": item.get("title"), "reason": reason, "kind": "web_page"})
                    run.log("discover", "web_page_filtered", reason, url=item["url"], title=item.get("title"))
                    continue
                title, excerpt = str(item.get("title") or "")[:300], str(item.get("content") or "")[:4000]
                eid = run.add_evidence("public_web_discovery", item["url"], envelope["retrieved_at"], envelope["raw_file"], excerpt,
                    platform=source, retrieval_provider=provider, published_at=published, audience_country="unverified", sales="unavailable")
                page = {"id": identity("W", item["url"]), "title": title, "excerpt": excerpt, "url": item["url"], "platform": source,
                        "published_at": published, "score": item.get("score"), "evidence_ids": [eid], "audience_country": "unverified",
                        "retrieval_providers": [provider], "image": safe_url(item.get("image")),
                        "image_links": [url for url in item.get("image_links", []) if isinstance(url, str) and safe_url(url)][:3] if isinstance(item.get("image_links"), list) else []}
                contexts.append(page)
                added.append(page)
                state[source]["count"] += 1
                provider_pages[provider] += 1
        except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
            run.warn(f"Khám phá web / {label}: {error}")
            for site in selected_sites:
                state[site].update(status="unavailable", reason=str(error))
        return added

    def extract(pages, use_llm=True):
        count = 0
        from .keyword_expansion import product_key
        literal_count = 0
        for page in pages:
            for item in literal_model_phrases(page, config):
                text = item["keyword"]
                category = classify(text, config).get("category")
                matches = [(len(tokens(text) & niche_words[nid]), bool(category and category in niche_categories[nid]), nid) for nid in niches
                           if not (category and niche_categories[nid] and category not in niche_categories[nid])]
                score, same_category, nid = max(matches, default=(0, False, None))
                broad_models = research_focus(config)["multiple_product_families"]
                if nid is None or not (score or (same_category and broad_models)) or product_key(text) in source_models:
                    continue
                if add(text, niches[nid], "public_web", page["evidence_ids"]):
                    source_models.add(product_key(text))
                    page.setdefault("literal_model_phrases", []).append({**item, "niche_id": nid, "query_version": DISCOVERY_QUERY_VERSION})
                    count += 1
                    literal_count += 1
                    covered_niches.add(nid)
        if literal_count:
            run.log("discover", "literal_model_phrases_extracted", "Giữ cụm mẫu sản phẩm ngắn có nguyên văn trong nguồn; đây là đề cập sản phẩm, chưa phải độ hot hoặc doanh số", accepted=literal_count)
        if use_llm and pages and config["llm"]["enabled"]:
            try:
                result = complete(client, "extract", {"theme": config["category"], "research_brief": config["brief"],
                    "research_period": research_period(config), "business_context": prompt_context(config),
                    "research_focus": research_focus(config),
                    "niches": list(niches.values()), "pages": pages, "maximum": config["limits"]["candidate_keywords"]})
                by_id = {p["id"]: p for p in pages}
                for item in result.get("candidates", [])[:100]:
                    if not isinstance(item, dict):
                        continue
                    text, quote, nid, sid = (item.get(k) for k in ("keyword", "quote", "niche_id", "source_id"))
                    page = by_id.get(sid) if isinstance(sid, str) else None
                    body = normalize(page["title"] + " " + page["excerpt"]) if page else ""
                    design = verified_source_design(item, page) if page else None
                    verbatim = isinstance(text, str) and isinstance(quote, str) and len(quote.strip()) >= 2 and normalize(quote) in body and normalize(text) in normalize(quote)
                    if not isinstance(nid, str) or nid not in niches or not isinstance(text, str) or not (design or verbatim):
                        excluded.append({"keyword": text, "reason": "LLM trích keyword không có nguyên văn trong trang nguồn"})
                        continue
                    if product_context(text, config):
                        excluded.append({"keyword": text, "kind": "product_context", "reason": "Nguồn mới mô tả phôi/loại hàng; thiếu hình, chủ đề hoặc câu chữ cần tìm"})
                        continue
                    if product_key(text) in source_models and not design:
                        continue
                    # Old verbatim consumers need no new metadata argument.
                    accepted = add(text, niches[nid], "public_web", page["evidence_ids"], source_design=design) if design else add(text, niches[nid], "public_web", page["evidence_ids"])
                    if accepted:
                        source_models.add(product_key(text))
                        count += 1
                        covered_niches.add(nid)
            except (SourceError, ValueError, KeyError, TypeError, AttributeError) as error:
                run.warn(f"Trích keyword từ web: {error}; giữ trang tham khảo, không tự bịa keyword")
        run.log("discover", "web_keywords_extracted", "Kết quả trích keyword có câu nguồn", pages=len(pages), accepted=count)
        return count

    words = [w for w in config["category"].split() if w.lower() not in {"for", "and", "the", "in", "with", "of"}][:9]
    focus = research_focus(config)
    content = content_mode(config) == "designs"
    dimensions = "character illustration slogan pattern designs" if content else "specific designs graphics patterns" if focus["level"] == "exact_motif" else "product models shapes formats finishes printable blanks" if focus["level"] == "product_models" else "physical product types ideas"

    def family_query(niche):
        from ..business.domain import _POSITIVE
        # Search one physical family at a time, not an AND of unrelated seeds
        # such as photo keychain + wallet phone case + all production methods.
        for seed in niche["seeds"]:
            for pattern in _POSITIVE.values():
                match = re.search(pattern, seed, re.I)
                if match:
                    return match.group(0)
        return niche.get("name_en") or niche["seeds"][0]
    initial_queries = []
    for index, (selected_sites, label) in enumerate(bundles):
        query = " ".join(words) + " " + dimensions + " " + discovery_period_query(config)
        if active(config):
            groups = list(niches.values())
            # Rotate across product families within the same source-request
            # count; an apparel example must not consume every web query.
            selected = [groups[(index * 2 + offset) % len(groups)] for offset in range(min(2, len(groups)))]
            concrete = family_query(groups[index % len(groups)]) if content else " ".join(measurement_query(n["seeds"][0]) for n in selected)
            query = concrete + " " + dimensions + " " + discovery_period_query(config)
        initial_queries.append(query)
        collect(query, selected_sites, label)
    if config["discovery"].get("web_provider") == "combined" and initial_queries:
        # Combining sources deliberately samples both indexes even if one
        # already yielded a subject. Auto remains the gap-filling economy mode.
        complement_sites = [site for site in sites if site in {"etsy", "walmart", "ebay", "pinterest"}] or sites
        for name in available:
            if not provider_queries[name] and name not in blocked and web.remaining(client, name) > 0:
                run.log("discover", "web_provider_complement", "Bổ sung chỉ mục tìm kiếm thứ hai để tăng độ đa dạng nội dung trong trần đã chọn", provider=name)
                collect(initial_queries[0], complement_sites, "complement", preferred=name)
    count = extract(contexts)
    remaining = sum(web.remaining(client, name) for name in available if name not in blocked)
    missing = [niche for nid, niche in niches.items() if nid not in covered_niches] if content else list(niches.values()) if not count else []
    if missing and remaining > 0:
        retry_pages = []
        for index, niche in enumerate(missing):
            if index >= min(5 if content else 3, remaining):
                break
            if content and niche["id"] in covered_niches:
                continue
            # Prefer actual marketplaces/visual pages for missing print content;
            # one social mention must not stop exploration of other families.
            preferred = [bundle for bundle in bundles if bundle[1] in {"marketplaces", "visual"}] or bundles
            selected_sites, label = preferred[index % len(preferred)]
            head = family_query(niche) if content else " ".join(measurement_query(seed) for seed in niche["seeds"][:2])
            run.log("discover", "web_focused_retry", "Tìm tiếp nhóm hàng chưa có nội dung mẫu từ nguồn trong ngân sách Tavily", query=head, sites=selected_sites)
            fresh = collect(head + " " + dimensions + " " + discovery_period_query(config), selected_sites, label,
                preferred="exa" if "exa" in available else None)
            retry_pages.extend(fresh)
            # Literal subjects can close gaps immediately without another LLM
            # call. Any composed subjects are extracted once for the batch.
            extract(fresh, use_llm=False)
        count += extract(retry_pages)
    for record in state.values():
        if record["count"]:
            record["status"] = "available"
        elif record["filtered_count"] and record["status"] != "unavailable":
            record["status"] = "low_quality"
    provider_status = [{"branch": "web_provider", "provider": name, "count": provider_pages[name],
        "used": sum(u["provider"] == name for u in run.manifest["usage"]), "cap": config["limits"].get(name + "_requests", 0),
        "queries": provider_queries[name],
        "status": "available" if provider_pages[name] else "unavailable" if name in blocked else "limited" if not web.remaining(client, name) else "empty",
        **({"reason": blocked[name]} if name in blocked else {})} for name in available]
    return contexts, list(state.values()) + provider_status, excluded
