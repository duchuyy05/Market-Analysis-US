"""Conservative company-domain routing, not a claim of factory feasibility.

The profile concerns the actual product type. A cosmetic pouch is a bag and a
coffee graphic on a T-shirt is printed apparel; neither is a cosmetic/food.
Unknown types remain explicit rather than being treated as manufactured goods.
"""
import re
import unicodedata


CATEGORY_LABELS = {
    "apparel": "Áo thun, quần áo và phụ kiện vải có thể thiết kế/in/thêu",
    "bags_textiles": "Túi tote, túi/pouch và đồ vải gia dụng",
    "printed_paper": "Lịch, sách/sổ, thiệp, giấy gói và sản phẩm giấy in",
    "keychains": "Móc khóa, thẻ tên và phụ kiện khắc/in",
    "phone_accessories": "Ốp, dây, giá đỡ và phụ kiện thiết bị không cấp điện",
    "home_decor": "Decor nhà cửa, đồ treo và đồ trang trí có thể gia công",
    "gift_accessories": "Phụ kiện gói quà, quà cá nhân hóa và vật dụng in/khắc đơn giản",
}

_POSITIVE = {
    "apparel": r"\b(?:t[ -]?shirts?|shirts?|tees?|pocket\s+squares?|hoodies?|sweatshirts?|sweaters?|apparel|clothing|pajamas?|pyjamas?|bathrobes?|jerseys?|aprons?|socks?|scar(?:f|ves)|beanies?|caps?|hats?|bandanas?|mittens?|gloves?|tank\s+tops?|sweatpants?|joggers?|leggings?|jackets?|vests?|shorts?|onesies?|rompers?|bodysuits?|bibs?|headbands?|scrunchies?|(?:embroidered|embroidery|iron[ -]on|sew[ -]on|chenille)\s+patch(?:es)?|canvas\s+(?:shoes?|sneakers?)|slippers?)\b",
    "bags_textiles": r"\b(?:tote(?:\s+bags?)?|bags?|pouch(?:es)?|backpacks?|drawstring\s+sacks?|fabric|textile|tea\s+towels?|towels?|blankets?|throws?|pillows?|pillowcases?|pillow\s+covers?|cushion\s+covers?|table\s+runners?|placemats?|napkins?|stockings?|quilts?)\b",
    "printed_paper": r"\b(?:calendars?|planners?|notebooks?|notepads?|sticky\s+notes?|sticky\s+note\s+pads?|journals?|books?|bookmarks?|greeting\s+cards?|postcards?|cards?|wrapping\s+paper|gift\s+wrap|gift\s+tags?|labels?|stickers?|decals?|prints?|posters?|stationery|scrapbooks?|photo\s+albums?|paper|coloring\s+pages?|brochures?|flyers?|leaflets?|invitations?|certificates?|menus?|cardstock|cardboard|cartons?|paperboard|(?:bookbinding|binding)\s+(?:coils?|combs?|covers?)|(?:DTF|UV\s+DTF|sublimation|heat\s+(?:press\s+)?transfer|waterslide)\s+(?:(?:cup|tumbler)\s+)?(?:transfers?|sheets?|films?|wraps?))\b",
    "keychains": r"\b(?:key[ -]?chains?|keyrings?|key\s+rings?|key\s+fobs?|name\s+tags?|luggage\s+tags?|engraved\s+tags?)\b",
    "phone_accessories": r"\b(?:(?:phone|iphone|smartphone|cell\s*phone|mobile|tablet|airpods?|earbuds?|power\s*banks?|laptops?|e[ -]?readers?|kindle|airtags?|galaxy|samsung|pixel)\s+(?:(?:[a-z0-9+.-]+)\s+){0,5}(?:cases?|covers?|sleeves?|stands?|holders?|straps?|lanyards?|grips?|pouch(?:es)?|mounts?|screen\s+protectors?)|(?:cases?|covers?|sleeves?|stands?|holders?|straps?|grips?)\s+for\s+(?:phone|iphone|smartphone|tablet|airpods?|earbuds?|power\s*banks?|laptops?|e[ -]?readers?|kindle|airtags?|galaxy|samsung|pixel)|popsockets?|phone\s+charms?|(?:cable|cord)\s+(?:organizers?|clips?|holders?|tags?))\b",
    "home_decor": r"\b(?:decor|decorations?|ornaments?|photo\s+frames?|picture\s+frames?|wall\s+art|wall\s+hangings?|wall\s+scrolls?|display\s+stands?|easels?|(?:message|memo)\s+boards?|signs?|plaques?|wreaths?|garlands?|banners?|figurines?|statuettes?|sculptures?|wooden\s+toys?|desk\s+organizers?|trays?|vases?|candle\s+holders?|candles?|coasters?|doormats?|rugs?|pillow\s+inserts?|throw\s+pillows?|cushions?|standees?|cutouts?|door\s+hangers?|suncatchers?|sun\s+catchers?|shadow\s+box(?:es)?|plant\s+pots?|photo\s+slates?|(?:wood(?:en)?|plywood|MDF|acrylic|ceramic|alumini?um|metal|glass|slate|foam\s+board)\s+(?:(?:sublimation|printing|printable|engraving|replacement|laser[ -]cut)\s+)?(?:blanks?|panels?|sheets?|shapes?|discs?|rounds?|tiles?))\b",
    "gift_accessories": r"\b(?:mugs?|tumblers?|cups?|bottles?|drinkware|glassware|stemware|(?:wine|beer|whiskey|shot|drinking|can)\s+(?:can\s+)?glass(?:es)?|empty\s+(?:cosmetic|makeup)\s+compacts?|food\s+(?:storage\s+)?containers?|gift\s+(?:box(?:es)?|bags?|ribbons?|bows?|tags?)|ribbons?|bows?|magnets?|badges?|pins?|lanyards?|wallet\s+cards?|wallets?|bracelets?|necklaces?|pendants?|charms?|jewelry|jewellery|bottle\s+openers?|keepsakes?|acrylic\s+(?:blocks?|stands?)|pocket\s+mirrors?|mouse\s*(?:pads?|mats?)|desk\s+mats?|(?:pill|medicine)\s+(?:box(?:es)?|cases?|organizers?)|(?:heat\s+press|sublimation|UV[ -]?(?:DTF|print(?:ing)?)|printable|engraving|laser[ -]cut)\s+(?:[a-z]+\s+){0,2}blanks?)\b",
}

_BLOCKED = (
    ("complex_device", r"\b(?:digital|electronic|LED|LCD)\s+(?:message|memo|display|writing)\s+boards?\b", "Bảng điện tử dùng điện nằm ngoài domain sản phẩm công ty"),
    ("food_beverage", r"\b(?:foods?|edible|groceries|chocolates?|cand(?:y|ies)|snacks?|cookies?|biscuits?|cakes?|popcorn|sweets?|confectionery|gourmet|coffee\s+(?:beans?|samplers?|grounds?|pods?|bags?)|tea\s+(?:samplers?|bags?|leaves|gift\s+sets?)|cocoa|wine|beer|liquor|beverages?|juices?|honey|spices?|sauces?|protein\s+(?:powder|bars?)|food\s+baskets?)\b", "Thực phẩm/đồ uống nằm ngoài phạm vi gia công và thiết kế của công ty"),
    ("cosmetics_health", r"\b(?:cosmetics?|make[ -]?up|skin[ -]?care|hand\s+creams?|body\s+(?:lotions?|butters?|scrubs?|wash)|face\s+(?:creams?|serums?|masks?)|beauty\s+(?:serums?|products?|sets?)|moisturi[sz]ers?|perfumes?|colognes?|fragrances?|essential\s+oils?|shampoos?|conditioners?|lipsticks?|lip\s+balms?|bath\s+(?:bombs?|salts?)|supplements?|vitamins?|medicines?|medications?|pills?|pharmaceuticals?|(?:prescription|over[ -]the[ -]counter)\s+drugs?|antibiotics?|aspirin|ibuprofen|paracetamol|acetaminophen)\b", "Mỹ phẩm/dược phẩm/thực phẩm bổ sung nằm ngoài domain công ty"),
    ("complex_device", r"\b(?:blood\s+pressure\s+monitors?|thermometers?|medical\s+(?:devices?|equipment)|hearing\s+aids?|massagers?|electric\s+(?:kettles?|blankets?|toothbrushes?|razors?|shavers?|heaters?)|heated\s+(?:blankets?|throws?|pads?|jackets?|vests?|socks?|gloves?)|bluetooth\s+speakers?|(?:wireless\s+)?headphones?|earbuds?|smartwatches?|smart\s+watches?|power\s*banks?|phone\s+chargers?|wireless\s+charg(?:ers?|ing\s+(?:phone\s+)?(?:pads?|stations?|stands?))|charging\s+(?:cables?|pads?|stations?|stands?)|USB\s+chargers?|digital\s+(?:photo\s+frames?|cameras?)|projectors?|printers?|sewing\s+machines?|laser\s+cutters?|3d\s+printers?|kitchen\s+(?:appliances?|machines?)|coffee\s+(?:makers?|machines?)|air\s+(?:fryers?|purifiers?)|robot\s+vacuums?|(?:candle|mug|cup)\s+warmers?|(?:book|reading)\s+lights?|charging\s+(?:phone\s+)?cases?|LED\s+(?:lights?|lamps?|strips?|signs?|ornaments?|decorations?|displays?)|(?:string|fairy|christmas)\s+lights?|battery[ -]operated|USB[ -]powered|rechargeable|electronics?|machinery|equipment)\b", "Máy móc, thiết bị điện/điện tử hoặc y tế nằm ngoài domain công ty"),
    ("complex_device", r"\b(?:heated\s+(?:[a-z]+\s+){0,2}(?:blankets?|throws?|pads?|jackets?|vests?|socks?|gloves?)|heat\s+press(?:es)?|(?:engraving|printing|cutting|embroidery|sublimation|DTF|UV|CNC)\s+machines?|vinyl\s+cutters?|LED\s+light\s*box(?:es)?|smart\s+rings?|fitness\s+trackers?|GPS\s+trackers?|airtags?|NFC\s+(?:chips?|tags?|key\s*fobs?|keychains?)|RFID\s+(?:chips?|tags?|readers?|key\s*fobs?|keychains?))\b", "Máy in/gia công hoặc thiết bị công nghệ tích hợp nằm ngoài domain sản phẩm công ty"),
)

# Mask only a named accessory span, not everything else in the listing. A bag
# bundled with hand cream still retains the blocked hand-cream term afterwards.
_ACCESSORY = re.compile(r"\b(?:(?:cosmetics?|make[ -]?up|toiletr(?:y|ies)|bluetooth\s+speaker|headphones?|earbuds?|power\s*banks?|chargers?|charging\s+cables?|cameras?|laptops?|airtags?)\s+(?:travel\s+|storage\s+|carrying\s+)?(?:bags?|pouch(?:es)?|cases?|box(?:es)?|organizers?|holders?|covers?|sleeves?|stands?|straps?|clips?|keychains?))\b", re.I)
_DEPICTION = re.compile(r"\b(?:coffee|tea|chocolate|candy|food|wine|beer|perfume|lipstick|makeup|medicines?|medications?|pills?|pharmaceuticals?|aspirin|ibuprofen|paracetamol|acetaminophen|camera|headphones?|electronics?|sewing\s+machine)(?:[ -](?:themed|inspired|lover))?\s+(?:(?:graphic|illustration|pattern|design|art|motif|print|printed|novelty)\s+)*(?:t[ -]?shirt|shirt|hoodie|sweatshirt|poster|print|sticker|decal|tote\s+bag|mug|ornament|keychain)\b", re.I)
_BEVERAGE_ACCESSORY = re.compile(r"\b(?:(?:beer|wine|whiskey)\s+(?:(?:bottle|can|drinking)\s+)?(?:openers?|carriers?|bags?|stoppers?|holders?|mugs?|cups?|glass(?:es)?|tumblers?)|(?:coffee|tea)\s+(?:mugs?|cups?|towels?|tumblers?))\b", re.I)
_EMPTY_STORAGE = re.compile(r"\b(?:(?:food|snack|candy|chocolate|tea|coffee|perfume|cosmetic|makeup|skin[ -]?care|medicine|pill)\s+(?:empty|reusable|storage)\s+(?:bags?|pouch(?:es)?|box(?:es)?|containers?|bottles?|compacts?)|(?:empty|reusable|storage)\s+(?:food|snack|candy|chocolate|tea|coffee|perfume|cosmetic|makeup|skin[ -]?care|medicine|pill)\s+(?:bags?|pouch(?:es)?|box(?:es)?|containers?|bottles?|compacts?)|food\s+(?:storage\s+)?containers?)\b", re.I)
_DEVICE_CONTAINER = re.compile(r"\b(?:cases?|bags?|pouch(?:es)?|covers?|sleeves?|holders?|stands?)\s+for\s+(?:a\s+|an\s+)?(?:power\s*banks?|chargers?|bluetooth\s+speakers?|headphones?|earbuds?|cameras?|laptops?)\b", re.I)
_PASSIVE_WORKPIECE = re.compile(r"\b(?:(?:heat\s+press|DTF|UV\s+DTF|sublimation)\s+(?:transfer\s+)?(?:paper|sheets?|films?|decals?|transfers?|wraps?)|(?:pill|medicine)\s+(?:box(?:es)?|cases?|organizers?)|(?:acrylic|wood(?:en)?|metal|glass)\s+(?:replacement\s+)?panels?\s+for\s+(?:an?\s+)?LED\s+(?:lamps?|light\s*box(?:es)?))\b", re.I)
_PROCESS_WORKPIECE = re.compile(r"\b(?:heat\s+press|sublimation|UV\s+DTF|DTF)\s+(?:(?:blank|printable|custom|ceramic|wooden|acrylic|metal)\s+){0,2}(?:blanks?|coasters?|mugs?|cups?|tumblers?|panels?|ornaments?|keychains?|t[ -]?shirts?)\b(?!\s+(?:blanks?\s+)?(?:machines?|printers?|press(?:es)?))", re.I)
_MEDICINE_PAPER = re.compile(r"\b(?:pills?|medicines?|medications?|pharmaceuticals?)\s+(?:(?:tracking|tracker|log|record|dosage|schedule|motif|pattern|graphic)\s+){0,2}(?:planners?|journals?|notebooks?|books?|calendars?|charts?|labels?|stickers?)\b", re.I)


def selected_categories(config):
    business = config.get("business") or {}
    if business.get("profile", "general") != "custom_manufacturing":
        return []
    values = business.get("categories")
    return list(CATEGORY_LABELS) if values is None else [c for c in values if c in CATEGORY_LABELS]


def active(config):
    return (config.get("business") or {}).get("profile", "general") == "custom_manufacturing"


def _normalize(value):
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).casefold().replace("’", "'").split())


def classify(value, config):
    if not active(config):
        return {"status": "allowed", "category": None, "profile": "general", "reason": "Không áp dụng bộ lọc domain công ty"}
    body = _normalize(value)
    # The protected span still determines its physical product category below.
    inspected = _ACCESSORY.sub(" ", body)
    inspected = _DEPICTION.sub(" ", inspected)
    inspected = _BEVERAGE_ACCESSORY.sub(" ", inspected)
    inspected = _EMPTY_STORAGE.sub(" ", inspected)
    inspected = _DEVICE_CONTAINER.sub(" ", inspected)
    inspected = _PASSIVE_WORKPIECE.sub(" ", inspected)
    inspected = _PROCESS_WORKPIECE.sub(" ", inspected)
    inspected = _MEDICINE_PAPER.sub(" ", inspected)
    # Explicit graphic/illustration wording identifies a depiction, including
    # forms such as "T-shirt with chocolate graphic" rather than the food.
    for _, pattern, _ in _BLOCKED:
        inspected = re.sub(pattern + r"(?=\s+(?:graphic|illustration|pattern|design|art|motif|diagram|print)\b)", " ", inspected, flags=re.I)
        inspected = re.sub(r"\b(?:graphic|illustration|pattern|design|art|motif|diagram|print)\s+(?:of\s+)?" + pattern, " ", inspected, flags=re.I)
    for kind, pattern, reason in _BLOCKED:
        if re.search(pattern, inspected, re.I):
            return {"status": "excluded", "category": None, "profile": "custom_manufacturing", "reason": reason, "rule": kind}
    # Prefer explicit accessories over generic words such as "cover"/"card".
    order = ("phone_accessories", "keychains", "apparel", "bags_textiles", "printed_paper", "home_decor", "gift_accessories")
    matches = [category for category in order if re.search(_POSITIVE[category], body, re.I)]
    chosen = selected_categories(config)
    allowed = next((category for category in matches if category in chosen), None)
    if allowed:
        return {"status": "allowed", "category": allowed, "profile": "custom_manufacturing",
                "reason": "Loại hàng thuộc nhóm đã chọn: " + CATEGORY_LABELS[allowed], "rule": "supported_type",
                "limitation": "Phù hợp domain nghiên cứu; chưa xác minh năng lực xưởng, vật liệu, giá vốn hoặc thiết kế cụ thể"}
    if matches:
        return {"status": "excluded", "category": matches[0], "profile": "custom_manufacturing", "reason": "Loại hàng không thuộc các nhóm công ty đã chọn trên dashboard", "rule": "category_not_selected"}
    return {"status": "pending_verification", "category": None, "profile": "custom_manufacturing", "reason": "Chưa nhận diện được loại hàng có thể gia công/in/thiết kế; cần kiểm tra phạm vi công ty", "rule": "unknown_type"}


def classify_product(product, config):
    result = classify(product.get("title", ""), config)
    if active(config) and result["status"] != "excluded":
        # Only explicit included/integrated contents override an otherwise
        # supported accessory title. Compatibility and storage use cases are
        # not evidence that the device or cosmetic is part of the sold item.
        body = _normalize(product.get("title", "") + " " + product.get("description", ""))
        marker = re.compile(r"\b(?:includes?|contains?|comes\s+with|bundled\s+with|built[ -]in)\s+", re.I)
        modifiers = re.compile(r"^(?:(?:a|an|the|one|two|three|four|free|complimentary|actual|real|travel[ -]size|sample[ -]size|packet|pack|tube|jar|bottle|set|pair|of|\d+)\s+){0,5}", re.I)
        for match in marker.finditer(body):
            prefix = body[max(0, match.start()-35):match.start()]
            if re.search(r"(?:not|never|without|no)\s*$|(?:text|caption|quote|graphic|print|reads?|says?)\s*['\":]*\s*$", prefix, re.I):
                continue
            target = modifiers.sub("", body[match.end():match.end()+180])
            explicit_type = any(re.match(pattern, target, re.I) for _, pattern, _ in _BLOCKED)
            powered = "built" in match.group() and bool(re.match(r"(?:battery|power\s*bank|wireless\s+charging|charging\s+(?:module|circuit)|charger|motor|LED\s+light)", target, re.I))
            generic_content = bool(re.match(r"(?:creams?|lotions?|serums?)\b", target, re.I))
            if powered or generic_content:
                return {"status": "excluded", "category": result.get("category"), "profile": "custom_manufacturing", "reason": "Listing nêu thành phần mỹ phẩm/thực phẩm hoặc mô-đun điện tích hợp ngoài domain công ty", "rule": "explicit_included_content", "basis": "explicit_contents", "excerpt": match.group() + target[:100]}
            if explicit_type:
                included = classify(target, config)
                if included["status"] == "excluded":
                    return {**included, "basis": "explicit_contents", "excerpt": match.group() + target[:100]}
    # Marketing copy mentioning a compatible device does not change a case into
    # that device. Detailed text is used only to resolve an unknown title.
    if result["status"] == "pending_verification" and product.get("description"):
        detailed = classify(product["description"], config)
        if detailed["status"] != "pending_verification":
            return {**detailed, "basis": "description"}
    return {**result, "basis": "title"}


def prompt_context(config):
    if not active(config):
        return {"profile": "general", "instruction": "Follow the user's product scope; no company capability profile selected."}
    ids = selected_categories(config)
    return {"profile": "custom_manufacturing", "categories": ids, "category_labels": {key: CATEGORY_LABELS[key] for key in ids},
            "instruction": "Research physical goods a garment/design/printing/custom-manufacturing company can customize, fabricate or source as inert blanks within the selected capability categories. These are broad capabilities, not a closed product catalog. Print, embroidery, engraving, paper converting/binding, sewing, flat-pack structures, acrylic/wood/metal/ceramic decor and non-powered device accessories are examples, not mandatory material or technique filters. Explore shapes, formats, construction and artwork; preserve every explicit user constraint. Imported printable blanks and passive substrates may be hypotheses even if the company does not fabricate their base material. Never propose actual edible food/drinks, cosmetics/perfume/supplements/pharmaceuticals, medical devices, printing/production machinery or integrated electronic devices. A cosmetic pouch, empty pill box, coffee mug, inert panel or printed depiction of medicine/device is an accessory/printed item, not the excluded contents; an accessory bundled with actual cosmetics/drugs or powered modules remains excluded. Keep the actual physical product type explicit in English. Unknown objects still require capability verification. This is a capability hypothesis, not proof of factory feasibility or existing production."}
