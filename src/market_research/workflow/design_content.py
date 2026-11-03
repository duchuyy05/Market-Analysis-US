"""Separate what goes ON a product from the printable substrate itself.

This is a query classifier, not image recognition or a popularity model. Names
and slogans come from literal source text or remain explicit hypotheses.
"""
import re


def content_mode(config):
    chosen = config.get("discovery", {}).get("focus", "auto")
    if chosen in {"designs", "models"}:
        return chosen
    brief = str(config.get("brief") or "").casefold()
    primary = re.split(r"ví dụ|chẳng hạn|\bfor example\b|\bfor instance\b|\bsuch as\b", brief, maxsplit=1)[0]
    limit = re.search(r"chỉ\s+(?:tìm|nghiên cứu|phân tích|cần|lấy|chọn|tập trung|hình|họa tiết|hoạ tiết)|\bonly\s+(?:research|find|print|search|study)\b", brief)
    if limit:
        primary = brief[limit.start():]
    # An example must not turn a general physical-model request into only art.
    requested = re.search(r"in gì|in hình|hình in|hình gì|hình nào|nhân vật|câu chữ|chữ gì|họa tiết|hoạ tiết|mẫu in|print on|prints? on|which.*(?:image|character|slogan|singer.*print)|(?:artwork|motif|slogan|fandom)", primary)
    return "designs" if requested else "models"


def subject_terms(query):
    """Literal remaining query words; no entity names or hot topics hardcoded.

    Physical-model-only details cannot answer which picture or words to print.
    Unknown product vocabulary is left unclassified rather than invented.
    """
    from .trend_queries import _model_details
    remainder = _model_details(query, exact_motif=True)
    if remainder is None:
        return None
    substrate = set("""blank blanks plain printable engravable sublimation sublimated dtf dtg
        uv screen transfer transfers heat press laser engraved engraving embossed debossed
        monogram monogrammed embroidered embroidery customisable customizable cotton polyester
        linen canvas fabric textile woven felt nylon ripstop leather leatherette vegan acrylic
        clear pvc tpu silicone rubber plastic metal steel stainless aluminum aluminium anodized
        brass bamboo wood wooden mdf cork ceramic glass resin enamel kraft satin matte glossy waxed
        gloss textured coating finish coated premium soft flexible hard rigid transparent
        lightweight durable small medium large mini pocket portable travel desk desktop table
        tabletop wall stand perpetual calendar calendars journal journals notebook notebooks notepad
        notepads planner planners spiral bound binding wire ring flip tear off away tent easel
        lined ruled grid daily weekly monthly yearly cover covers hardcover softcover page pages
        long short sleeve sleeved raglan crew neck v neck crewneck vneck fit slim oversized boxy vintage retro
        cropped longline dropped drop shoulder side slits apparel tee tees shirt shirts hoodie hoodies
        zipper zip flap elastic band stitched ribbon bookmark strap straps drawstring crossbody tote pouch
        pouches bag bags wallet wallets fold folding foldable book style case cases phone iphone
        samsung pixel card slot slots bumper magnetic closure contrast trim pull tag hook
        charm charms tassel tassels keyring keychain keychains rounded edge double single sided
        rotating swivel textured grip plate photo slot collage frame frames ready with without
        print printed graphic graphics image images picture pictures text words name names
        design designs pattern patterns motif motifs theme themes shape shaped style type
        format layout size inch inches cm mm oz pack set count and or for on in to of a an the
        with by from gift gifts men women womens mens kids children adult adults unisex
        color colors colour colours white black blue red green yellow pink purple grey gray
        3d 2d""".split())
    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", remainder.casefold())
    return " ".join(word for word in words if word not in substrate and not word.isdigit())


def describes_content(query):
    return bool(subject_terms(query))


def design_metadata(query, config):
    terms = subject_terms(query)
    return {"content_focus": content_mode(config),
            "design_subject_terms": terms,
            "design_content_status": "query_subject" if terms else "substrate_only" if terms == "" else "unclassified"}


def verified_source_design(item, page):
    """Allow natural query composition only from two spans in ONE source.

    Example source: 'T-shirt ... print reads Not a morning person'. The natural
    query 'not a morning person shirt' is composed, not a verbatim source query.
    It must receive its own exact Trends measurement; source mentions prove no
    demand. Legacy verbatim extraction still goes through its existing guard.
    """
    design = item.get("design")
    if not isinstance(design, dict):
        return None
    subject, product = design.get("subject"), design.get("product")
    kind = design.get("kind", "unspecified")
    if kind not in {"character", "person", "slogan", "image", "pattern", "theme", "unspecified"}:
        return None
    if not all(isinstance(value, str) and value.strip() and value.isascii() and len(value) <= 120 for value in (subject, product)):
        return None
    quote = item.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    normalize = lambda value: " ".join(value.casefold().split())
    body = normalize(str(page.get("title") or "") + " " + str(page.get("excerpt") or ""))
    # Whole spans, not substrings such as 'cat' inside 'educational'.
    contains = lambda whole, part: bool(re.search(r"(?<!\w)" + re.escape(normalize(part)) + r"(?!\w)", normalize(whole)))
    if normalize(quote) not in body or not contains(quote, subject) or not contains(quote, product):
        return None
    from ..business.domain import _POSITIVE
    if not any(re.fullmatch(pattern, product.strip(), re.I) for pattern in _POSITIVE.values()):
        return None
    # No extra artist/character/material/year may be introduced by composition.
    if not isinstance(item.get("keyword"), str):
        return None
    query = normalize(item["keyword"])
    expected = {normalize(subject + " " + product), normalize(product + " " + subject)}
    if query not in expected or not describes_content(query):
        return None
    return {"subject": subject.strip(), "kind": kind, "product": product.strip(),
            "source_id": page["id"], "quote": quote.strip(),
            "query_origin": "verbatim" if contains(quote, query) else "composed_from_source_spans",
            "status": "source_text_observed", "evidence_ids": list(page.get("evidence_ids", []))}
