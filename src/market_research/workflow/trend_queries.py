"""Preserve the actual design query and describe its requested research period."""
import calendar
import re
from datetime import date

DISCOVERY_QUERY_VERSION = "source_design_content_v3"


def search_phrase_issue(text):
    """Reject generated catalog specifications; never rewrite a measured term.

    Human-supplied and source-quoted phrases keep their literal wording. This
    check is only for newly generated hypotheses before any paid measurement.
    """
    words = re.findall(r"[a-z0-9]+(?:['-][a-z0-9]+)*", str(text).casefold())
    if len(words) > 6:
        return "Seed cần cụm tìm kiếm tự nhiên, thường 2–4 từ; tách thông số sản xuất khỏi keyword"
    if re.search(r"\bsmall size\b|\blarge size\b|\b(?:custom|custom printed)\s+(?:logo|text|name|graphic|design)\s*$|\b(?:holiday|seasonal|christmas)\s+(?:pattern|design|theme|graphic)\s*$|\bmonthly layout\s*$|\bshape\s*$", str(text), re.I):
        return "Keyword là chuỗi mô tả catalog; dùng tên mẫu theo cách người mua tìm kiếm, giữ hình dạng/định dạng chính và đưa thông số phụ vào mô tả"
    return None


def measurement_query(text):
    """A generic shirt series cannot verify a particular artist/character print.

    Only normalize whitespace. Even a ``for`` suffix may contain the design's
    subject (for example a singer's fan community), so never remove it silently.
    Sparse exact queries remain missing evidence rather than borrowing a broad
    product type's popularity.
    """
    return " ".join(text.split())


def research_focus(config):
    """Infer family/model/motif scope without treating examples as restrictions.

    Structural and material models need no named character. An explicitly
    focused print-subject question still needs its actual subject measured.
    """
    from ..business.domain import _POSITIVE, active, selected_categories
    brief = str(config.get("brief") or "").casefold()
    parts = re.split(r"ví dụ|chẳng hạn|\bfor example\b|\bfor instance\b|\bsuch as\b|\be\.g\.", brief, maxsplit=1)
    primary = parts[0].strip()
    limit = re.search(r"chỉ\s+(?:tìm|nghiên cứu|phân tích|so sánh|xét|cần|lấy|chọn|tập trung|áo|họa tiết|hoạ tiết|hình|mẫu)|(?:giới hạn|tập trung)\s+(?:vào|ở)|\bonly\s+(?:research|analy\w*|compare|find|consider|focus|search|study|want|need|print|singer|shirt|pattern|character|artwork|motif)\b|\bfocus only\b", brief)
    if limit:
        # A real restriction can follow company background or an example;
        # "chỉ là ví dụ" is deliberately not a restriction marker.
        primary = re.split(r"[.;\n]", brief[limit.start():], maxsplit=1)[0]
    structural = bool(re.search(r"hình dạng|kiểu dáng|cấu trúc|định dạng|đóng gáy|bố cục|khổ|kích thước|chất liệu|hoàn thiện|phôi|\b(?:shapes?|forms?|formats?|binding|layouts?|finishes|finish|materials?|blanks?|cuts?|sizes?|dimensions?)\b", primary))
    model_request = structural or bool(re.search(r"mẫu|kiểu|nóng|\b(?:models?|styles?|variants?|designs?|hot)\b", primary))
    families = set()
    for category, pattern in _POSITIVE.items():
        for match in re.finditer(pattern, primary, re.I):
            phrase = match.group(0)
            if phrase in {"print", "prints", "paper", "fabric", "textile", "gift", "gifts"}:
                continue
            family = "calendars" if category == "printed_paper" and re.search(r"calendar", phrase) else "wrapping" if category == "printed_paper" and re.search(r"wrapp|gift wrap", phrase) else category
            families.add(family)
    # Vietnamese family mentions inform breadth, not an exhaustive catalog or
    # an allow-list. The actual English query remains untouched for sources.
    family_aliases = {"apparel": r"áo thun|áo phông|quần áo|\báo\b", "keychains": r"móc kh[oóòỏõọ]a|móc khoá",
        "calendars": r"\blịch\b|sổ tay|sổ ghi", "wrapping": r"giấy gói|vỏ quà|gói quà",
        "home_decor": r"đồ trang trí|đồ decor|\bdecor\b", "bags_textiles": r"túi tote|túi vải|túi xách", "phone_accessories": r"ốp điện thoại|ốp lưng"}
    families.update(key for key, pattern in family_aliases.items() if re.search(pattern, primary))
    # A company constraint may follow several examples. Scan the whole brief
    # for explicit breadth/capabilities while keeping incidental subjects out
    # of the main focus decision.
    capabilities = sum(bool(re.search(pattern, brief)) for pattern in
        (r"in ấn|\bprinting\b", r"khắc|\bengraving\b", r"gia công|\bfabrication\b", r"nhập.*phôi|\b(?:import|importing)\b"))
    broad = len(families) > 1 or bool(re.search(r"nhiều nhóm|các nhóm|tất cả.*(?:nhóm|mặt hàng)|đa dạng.*(?:sản phẩm|mặt hàng)|\bacross\b.*\b(?:categories|families)\b|\bselected categories\b|\bbroad\b.*\b(?:company|product)\b", brief)) or (active(config) and capabilities >= 2)
    subject = re.search(r"ca sĩ|nghệ sĩ|nhân vật|\b(?:singers?|artists?|celebrit(?:y|ies)|characters?)\b", primary)
    printing = re.search(r"in\s+(?:áo|hình|ấn|lên|mẫu)|hình|mẫu|\b(?:prints?|printed|printing|designs?|graphics?|images?)\b", primary)
    question = re.search(r"\b(?:which|what)\b.{0,25}\b(?:singer|artist|celebrity|character)\b", primary)
    motif = bool(re.search(r"họa tiết|hoạ tiết|in hình|hình in|in gì|in mẫu nào|hình nào|hình gì|\b(?:patterns?|motifs?|slogans?|illustrations?|portraits?|fandoms?)\b", primary)) or bool(subject and (printing or question))
    family_request = bool(re.search(r"nhóm hàng nào|loại hàng nào|ngành hàng nào|\b(?:which|what)\b.*\b(?:categories|product types|product families)\b|\bcompare\b.*\bcategories\b", primary))
    level = "exact_motif" if motif and not structural and (not broad or limit) else "product_models" if (model_request or broad or motif) and not (family_request and not structural) else "product_families"
    from .design_content import content_mode
    return {"level": level, "content_focus": content_mode(config), "multiple_product_families": len(families) > 1 or (broad and not bool(limit)), "incidental_examples": len(parts) > 1,
            "explicit_limit": bool(limit),
            "selected_categories": selected_categories(config),
            "model_dimensions": ["shape/form", "format/binding/layout", "cut/structure/size", "material/finish/process", "printable blank", "motif/character/graphic"]}


def design_intent(config):
    """Compatibility name: only a focused motif question requires a motif."""
    return research_focus(config)["level"] == "exact_motif"


def _model_details(text, exact_motif=False):
    """Find literal model details without a list of artists or popular models.

    Recognized physical types and print-process words are context. A name,
    pattern, slogan or other remaining literal concept identifies a design.
    """
    from ..business.domain import _POSITIVE
    remainder = str(text)
    preserved = []
    physical = False
    for category, pattern in _POSITIVE.items():
        if re.search(pattern, remainder, re.I):
            physical = True
            if not exact_motif:
                # Some domain spans include a material ("acrylic stand",
                # "wooden toy"); it remains a meaningful physical model.
                preserved.extend(word for match in re.finditer(pattern, remainder, re.I)
                                 for word in re.findall(r"[a-z0-9]+", match.group(0).casefold())
                                 if word in {"acrylic", "wooden", "wood", "bamboo", "metal", "ceramic", "glass", "resin", "silicone", "enamel", "mdf", "cork", "leather"})
                # The domain vocabulary contains both parent families and
                # already-concrete forms such as photo slate or shadow box.
                # Do not erase an entire compound form merely because the
                # domain router recognizes it. Only obvious compound parent
                # terms remain context, alongside one-word parent families.
                parents = {"t shirt", "t shirts", "tote bag", "tote bags", "phone case", "phone cases", "phone cover", "phone covers",
                    "wrapping paper", "gift wrap", "gift box", "gift boxes", "gift bag", "gift bags"}
                for match in re.finditer(pattern, remainder, re.I):
                    words = re.findall(r"[a-z0-9]+", match.group(0).casefold())
                    if len(words) > 1 and " ".join(words) not in parents:
                        preserved.extend(words)
            if category == "phone_accessories":
                # The domain router allows model/subject words between phone
                # and case. Those interior words can identify the print.
                pattern = r"\b(?:phones?|iphone|smartphones?|cell\s*phones?|mobiles?|tablets?|airpods?|earbuds?|galaxy|samsung|pixel|cases?|covers?|sleeves?|stands?|holders?|straps?|lanyards?|grips?|pouch(?:es)?|mounts?|screen\s+protectors?|popsockets?|charms?)\b"
            remainder = re.sub(pattern, " ", remainder, flags=re.I)
    if not physical:
        return None  # Unknown product wording needs evidence, not a context-only verdict.
    context = {"a", "an", "the", "and", "or", "of", "on", "in", "for", "with", "by", "to", "from",
        "custom", "customized", "customised", "personalized", "personalised", "printed", "print", "prints", "printing",
        "graphic", "graphics", "design", "designs", "pattern", "patterns", "patterned", "motif", "motifs", "themed", "theme",
        "image", "images", "picture", "pictures", "photo", "photos", "portrait", "portraits", "illustration", "illustrations",
        "singer", "singers", "artist", "artists", "character", "characters", "celebrity", "celebrities", "famous", "popular",
        "fan", "fans", "fandom", "basic", "simple", "ordinary", "product", "products", "sample", "samples",
        "men", "mens", "women", "womens", "kids", "children", "adults", "unisex", "boys", "girls", "gift", "gifts"}
    if exact_motif:
        context |= {"blank", "blanks", "plain"}
    return " ".join(dict.fromkeys(preserved + [word for word in re.findall(r"[a-z0-9]+", remainder.casefold()) if word not in context]))


def design_subject(text):
    return _model_details(text, exact_motif=True)


def candidate_level(text, config):
    """Expose whether a phrase describes a parent family or a concrete model."""
    level = research_focus(config)["level"]
    details = _model_details(text, exact_motif=level == "exact_motif")
    return "unclassified_product" if details is None else "product_family" if details == "" else "exact_motif" if level == "exact_motif" else "product_model"


def product_context(text, config):
    """Do not rank a parent-family series as evidence for a requested model."""
    from .design_content import content_mode, subject_terms
    if content_mode(config) == "designs" and subject_terms(text) == "":
        return True
    return research_focus(config)["level"] != "product_families" and candidate_level(text, config) == "product_family"


def research_period(config):
    """Shared month/year context for discovery prompts and public-web queries."""
    trends = config.get("trends", {})
    months = config.get("selling_months") or (trends.get("history_months") if trends.get("history_scope") == "seasonal" else None) or list(range(1, 13))
    months = sorted(set(months))
    from .planning import analysis_windows
    windows = analysis_windows(config) if trends.get("history_scope") == "seasonal" else []
    return {"months": months, "month_names": [calendar.month_name[month] for month in months],
            "analysis_year": trends.get("analysis_year"), "analysis_windows": windows,
            "history_years": config.get("history_years", []), "target_year": config.get("target_year"),
            "as_of_date": config.get("as_of_date"), "history_scope": trends.get("history_scope", "full")}


def discovery_period_query(config):
    period = research_period(config)
    months = " ".join(period["month_names"]) if len(period["months"]) < 12 else "all months"
    observed_years = sorted({window["year"] for window in period["analysis_windows"]})
    year = period["analysis_year"] or (observed_years[-1] if observed_years else period["target_year"] or str(period["as_of_date"])[:4])
    return f"United States {months} {year}"


def signal(series, start, end):
    points = [p for p in series if not p.get("partial") and p.get("value") is not None
              and date.fromisoformat(p["start"]) < end and date.fromisoformat(p["end"]) > start]
    positive = sum(p["value"] > 0 for p in points)
    # A single daily spike must not be sold as a robust hot keyword. Weekly
    # observations have fewer points; require two independent positive buckets.
    spans = [(date.fromisoformat(p["end"])-date.fromisoformat(p["start"])).days for p in points]
    minimum = 2 if spans and max(spans) >= 7 else 3
    return {"positive_points": positive, "observed_points": len(points), "minimum_positive_points": minimum,
            "has_signal": positive >= minimum}
