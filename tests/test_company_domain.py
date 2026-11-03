"""Company capability routing uses actual physical types, not gift popularity."""
import pytest

from market_research.business.domain import CATEGORY_LABELS, classify, classify_product, prompt_context
from market_research.config import validate_config
from market_research.llm.plan import validate_plan, seasonal_months
from market_research.providers.client import Client
from market_research.storage.run import Run
from market_research.workflow import broad, products
from market_research.workflow import understand, ideas
from market_research.analysis.opportunities import constraints


def company(**updates):
    return {"business": {"profile": "custom_manufacturing", "categories": list(CATEGORY_LABELS)}, **updates}


@pytest.mark.parametrize("term", [
    "Christmas graphic t-shirt", "personalized tote bag", "wall calendar", "printed notebook",
    "photo keychain", "gift wrapping paper", "engraved wooden ornament", "phone case",
    "ESR for iPhone 16 Pro Case", "adjustable phone stand", "phone strap", "cosmetic bag",
    "coffee mug", "tea towel", "wine bottle opener", "chocolate graphic t-shirt",
    "T-shirt with chocolate graphic", "vintage sewing machine graphic T-shirt", "photo frame",
    "Power bank case", "protective case for power bank",
    "graphic tee cotton", "silk pocket square", "notepad with cover", "sticky note pad custom",
    "wooden display stand", "mini easel display", "printed wall scroll", "desktop message board",
])
def test_supported_manufacturing_types_and_depictions(term):
    result = classify(term, company())
    assert result["status"] == "allowed", result
    assert result["category"] in CATEGORY_LABELS


@pytest.mark.parametrize("term", [
    "sublimation blanks", "UV printing blanks", "engraving blanks", "acrylic sheet blanks",
    "MDF laser-cut shapes", "ceramic sublimation tiles", "aluminum printing panels", "photo slate",
    "flat-pack acrylic standee", "wooden door hanger", "layered shadow box", "glass suncatcher",
    "spiral-bound tent calendar", "tear-off wall calendar", "die-cut cardstock", "folding paperboard carton",
    "bookbinding coils", "heat press transfer sheets", "UV DTF cup wraps", "DTF transfers",
    "machine embroidered patch", "sublimation baby onesie", "printed bib", "chenille patches",
    "printed desk mat", "mouse pad blank", "pocket mirror", "empty pill box", "medicine organizer",
    "Airtag keychain holder", "laptop stand", "charging cable holder",
    "acrylic replacement panel for LED lamp", "pill graphic t shirt", "medicine motif tote bag",
    "ibuprofen illustration mug", "T-shirt with pharmaceutical pattern", "heat press coaster blank",
    "DTF transfer film", "pill tracking planner", "medicine motif journal", "medication log book",
    "heat press blank", "beer can glass", "wine glass", "empty perfume bottle", "empty cosmetic compact",
])
def test_broad_passive_forms_blanks_and_design_depictions_remain_in_company_scope(term):
    fit = classify(term, company())
    assert fit["status"] == "allowed", (term, fit)


@pytest.mark.parametrize("term", [
    "pharmaceuticals", "prescription drugs", "ibuprofen pills", "medicine gift set", "aspirin tablets",
    "heat press", "laser engraving machine", "DTF printer", "UV printing machine", "vinyl cutter",
    "fitness tracker bracelet", "smart ring", "NFC keychain", "RFID tag", "Apple Airtag",
    "LED lightbox with acrylic panel", "rechargeable pocket mirror", "heated printable jacket",
    "printable mug bundled with pills", "pill graphic t shirt with free ibuprofen",
    "heat press with coaster blanks", "DTF printer with transfer film", "pill tracking planner with real pills",
    "heat press blank machine", "heat press coaster blank machine", "perfume bottle",
    "LED message board", "LCD writing board",
])
def test_actual_drugs_powered_goods_and_production_machines_stay_excluded(term):
    fit = classify(term, company())
    assert fit["status"] == "excluded", (term, fit)


@pytest.mark.parametrize(("term", "category"), [
    ("sublimation baby onesie", "apparel"), ("UV DTF cup wraps", "printed_paper"),
    ("flat-pack acrylic standee", "home_decor"), ("sublimation blanks", "gift_accessories"),
    ("charging cable holder", "phone_accessories"),
])
def test_new_manufacturing_forms_still_respect_selected_capability_categories(term, category):
    only = {"business": {"profile": "custom_manufacturing", "categories": [category]}}
    assert classify(term, only)["status"] == "allowed"
    excluded = {"business": {"profile": "custom_manufacturing", "categories": ["keychains"]}}
    assert classify(term, excluded)["status"] == "excluded"


def test_capability_context_is_broad_without_inventing_factory_feasibility():
    instruction = prompt_context(company())["instruction"]
    assert "broad capabilities" in instruction and "not a closed product catalog" in instruction
    assert "not mandatory material or technique filters" in instruction
    assert "Imported printable blanks" in instruction and "Unknown objects still require" in instruction
    assert classify("mysterious novel object", company())["status"] == "pending_verification"


@pytest.mark.parametrize(("title", "description", "expected"), [
    ("Empty pill box", "Comes with ibuprofen pills", "excluded"),
    ("Medicine organizer", "Includes aspirin tablets", "excluded"),
    ("Pill graphic t shirt", "Includes an ibuprofen illustration printed on cotton", "allowed"),
    ("Acrylic panel", "For an LED lamp; powered base not included", "allowed"),
    ("Acrylic panel", "Includes LED lamp and rechargeable battery", "excluded"),
    ("Pill tracking planner", "Notebook bundled with real pills", "excluded"),
])
def test_expanded_forms_keep_actual_included_contents_distinct_from_prints_and_compatibility(title, description, expected):
    fit = classify_product({"title": title, "description": description}, company())
    assert fit["status"] == expected, fit


@pytest.mark.parametrize("term", [
    "hand cream", "skin care gift set", "perfume", "vitamin supplements", "gourmet coffee sampler",
    "chocolate gift box", "tea gift set", "blood pressure monitor", "electric kettle",
    "Bluetooth speaker", "wireless headphones", "phone charger", "wireless charging phone stand",
    "power bank", "digital photo frame", "sewing machine", "LED light sign", "rechargeable lamp",
    "Christmas string lights", "coffee maker",
])
def test_food_cosmetics_devices_do_not_enter_company_research(term):
    assert classify(term, company())["status"] == "excluded"


def test_profile_category_selection_is_binding_and_unknown_is_explicit():
    only_paper = {"business": {"profile": "custom_manufacturing", "categories": ["printed_paper"]}}
    assert classify("wall calendar", only_paper)["status"] == "allowed"
    assert classify("phone case", only_paper)["status"] == "excluded"
    assert classify("unidentified surprise item", company())["status"] == "pending_verification"
    assert classify("hand cream", {})["status"] == "allowed"  # frozen/general runs
    assert "instruction" in prompt_context(company())


def test_accessory_does_not_hide_a_bundle_of_actual_cosmetics():
    assert classify("cosmetic pouch", company())["status"] == "allowed"
    assert classify("cosmetic pouch with hand cream", company())["status"] == "excluded"
    case = {"title": "Phone Case for iPhone 16", "description": "Compatible with wireless charging; charger not included."}
    assert classify_product(case, company())["status"] == "allowed"
    assert classify_product({"title": "Unknown item", "description": "Electronic blood pressure monitor"}, company())["status"] == "excluded"


@pytest.mark.parametrize("term", ["tea bags", "coffee bags", "candy bag", "chocolate bag", "cosmetic bag with tea bags", "coffee mug with chocolate"])
def test_food_packaging_words_do_not_hide_actual_contents(term):
    assert classify(term, company())["status"] == "excluded"


def test_explicit_empty_storage_remains_a_manufacturable_accessory():
    assert classify("empty candy bags", company())["status"] == "allowed"
    assert classify("reusable tea storage bag", company())["status"] == "allowed"
    assert classify("food storage container", company())["status"] == "allowed"


@pytest.mark.parametrize(("title", "description"), [
    ("Phone case", "Includes a power bank"),
    ("Phone case", "Case with built-in rechargeable battery"),
    ("Phone case", "Built-in wireless charging module"),
    ("Cosmetic bag", "Contains three hand creams and perfume"),
    ("Cosmetic bag", "Contains cream"),
    ("Coffee mug", "Comes with a packet of tea bags"),
])
def test_explicit_included_contents_override_a_supported_accessory_title(title, description):
    fit = classify_product({"title": title, "description": description}, company())
    assert fit["status"] == "excluded", fit
    assert fit["basis"] == "explicit_contents"


@pytest.mark.parametrize(("title", "description"), [
    ("Phone case", "Compatible with iPhone and power banks; charger not included."),
    ("Phone case", "Built-in magnetic ring compatible with wireless charging"),
    ("Cosmetic bag", "Compatible for skincare bottles and hand cream storage"),
    ("Cosmetic bag", "Does not include hand cream"),
    ("T-shirt", "Includes chocolate graphic printed on cotton"),
])
def test_compatibility_negated_contents_and_depictions_are_not_actual_devices(title, description):
    assert classify_product({"title": title, "description": description}, company())["status"] == "allowed"


def test_business_constraint_is_checked_in_llm_effective_plan():
    payload = {"brief": "Christmas gifts", "business": company()["business"], "validation_context": {"as_of_date": "2026-10-30", "history_years": [2023, 2024, 2025], "target_year": 2026}}
    bad = {"category": "Gifts", "niches": [{"name": "Gifts", "seeds": ["hand cream"]}]}
    with pytest.raises(ValueError, match="domain"):
        validate_plan(bad, payload)
    valid = validate_plan({"category": "Gifts", "niches": [{"name": "Gifts", "seeds": ["photo calendar", "phone case"]}]}, payload)
    assert valid["niches"][0]["seeds"] == ["photo calendar", "phone case"]


def test_mixed_model_seeds_keep_valid_niche_and_audit_exclusions(tmp_path, monkeypatch):
    cfg = validate_config({"brief": "Christmas gifts", **company(), "sources": {"trends": False, "web": False}})
    payload = {"brief": cfg["brief"], "business": cfg["business"], "validation_context": {"as_of_date": "2026-10-30", "history_years": [2023, 2024, 2025], "target_year": 2026}}
    seeds = ["photo calendar", "phone case", "unidentified surprise item", "hand cream"]
    plan = validate_plan({"category": "Gifts", "niches": [{"name": "Gifts", "seeds": seeds}]}, payload)
    # Validation does not trigger repair for an otherwise usable niche; the
    # next stage retains the excluded hypotheses for the dashboard audit.
    assert plan["niches"][0]["seeds"] == seeds
    monkeypatch.setattr(understand, "complete", lambda *_args, **_kwargs: plan)
    run = Run("mixed-model-seeds", tmp_path)
    result = understand.interpret(run, None, cfg)
    assert result["niches"][0]["seeds"] == ["photo calendar", "phone case"]
    assert {row["keyword"] for row in result["business_exclusions"]} == {"unidentified surprise item", "hand cream"}
    assert run.manifest["usage"] == []


def test_inferred_selling_window_respects_selected_collection_months():
    seasonal = {"history_scope": "seasonal", "history_months": [10, 11, 12]}
    assert seasonal_months(list(range(1, 13)), None, seasonal, "Quà Giáng sinh") == [11, 12]
    assert seasonal_months([9, 10, 11, 12], None, seasonal, "Holiday gifts") == [10, 11, 12]
    assert seasonal_months([1], [1], seasonal, "Explicit January") == [1]  # validation, not inference, rejects it later


def test_discovery_filters_company_domain_before_any_trends_calls(tmp_path):
    cfg = validate_config({"brief": "Christmas gifts", **company(), "sources": {"trends": False, "web": False}, "llm": {"enabled": False},
        "niches": [{"name": "Gifts", "seeds": ["phone case", "hand cream", "coffee sampler"]}], "limits": {"candidate_keywords": 5}})
    cfg["niches"][0]["id"] = "N"
    run = Run("company-keywords", tmp_path)
    run.manifest["input"] = cfg
    class NoRequests:
        def request(self, *args, **kwargs):
            pytest.fail("Discovery must not contact a provider in this fixture")
    result = broad.discover(run, NoRequests(), cfg)
    assert [row["text"] for row in result["keywords"]] == ["phone case"]
    assert len([x for x in result["exclusions"] if x.get("kind") == "company_domain"]) == 2


def test_known_forbidden_product_is_removed_before_detail_api(tmp_path):
    cfg = validate_config({"brief": "Phone accessory gifts", **company(), "sources": {"trends": False, "web": False}, "llm": {"enabled": False},
        "niches": [{"name": "Accessories", "seeds": ["phone accessory"]}], "limits": {"candidate_keywords": 5, "product_details": 3}})
    cfg["niches"][0]["id"] = "N"
    calls = []
    def send(provider, params):
        calls.append(params)
        if params["engine"] == "amazon":
            return {"organic_results": [
                {"asin": "B000000001", "title": "Phone accessory case", "extracted_price": 15, "sponsored": False},
                {"asin": "B000000002", "title": "Phone accessory wireless charger", "extracted_price": 25, "sponsored": False}]}
        assert params["asin"] == "B000000001"
        return {"product_results": {"title": "Phone case", "extracted_price": 15}}
    run = Run("company-products", tmp_path)
    client = Client(run, cfg, send)
    directions = [{"id": "D", "niche_id": "N", "keyword": "phone accessory", "search_query": "phone accessory"}]
    collected = products.collect(run, client, cfg, directions)
    assert [p["asin"] for p in collected["products"]] == ["B000000001"]
    assert len(collected["search_occurrences"]) == 2
    assert any(row.get("kind") == "company_domain" for row in collected["exclusions"])
    products.enrich(run, client, cfg, collected, directions)
    assert [p["asin"] for p in calls if p["engine"] == "amazon_product"] == ["B000000001"]


def test_company_domain_is_part_of_product_eligibility():
    cfg = {**company(), "price_range": None, "required_features": [], "excluded_features": []}
    product = {"title": "Hand cream", "price": 10, "currency": "USD"}
    assert constraints(product, cfg)["status"] == "excluded"
    product["title"] = "Mystery gift"
    assert constraints(product, cfg)["status"] == "pending_verification"


def test_unknown_or_forbidden_company_type_cannot_bypass_idea_guard():
    from test_idea_market_evidence import product
    direction = {"id": "D", "niche_id": "N", "name": "Gift", "customer_hypothesis": "Student buyer"}
    samples = [product("P1", title="Hand cream"), product("P2", title="Unidentified surprise gift")]
    # Even a stale or untrusted upstream assessment claiming eligibility cannot
    # make a business-incompatible sample into a suggested company product.
    assessed = {"directions": [{"direction_id": "D", "status": "shortlist"}], "product_checks": [{"product_id": p["product_id"], "status": "eligible", "pending": []} for p in samples]}
    assert ideas.generate({**company(), "selling_months": [11, 12]}, [direction], {"products": samples, "reviews": []}, assessed, []) == []


def test_manual_seed_set_outside_company_domain_fails_without_provider_calls(tmp_path):
    cfg = validate_config({"brief": "Gifts", **company(), "sources": {"trends": False, "web": False}, "llm": {"enabled": False}, "niches": [{"name": "Unsupported", "seeds": ["hand cream", "Bluetooth speaker"]}]})
    run = Run("unsupported-manual", tmp_path)
    with pytest.raises(ValueError, match="không còn seed"):
        understand.interpret(run, None, cfg)
    assert run.manifest["usage"] == []
