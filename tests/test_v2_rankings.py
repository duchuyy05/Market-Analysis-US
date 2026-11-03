from market_research.ranking.engine import build


def records():
    config = {"niches": [{"id": "N", "name": "Niche"}]}
    directions = [{"id": "D", "niche_id": "N", "keyword_id": "K"}]
    products = [{"product_id": "P1", "direction_ids": ["D"], "purchase_lower_bound": 100, "purchase_scope": "amazon_product_page", "observed_at": "2026-10-22", "evidence_ids": ["E1"]}, {"product_id": "P2", "direction_ids": ["D"], "purchase_lower_bound": 100, "purchase_scope": "amazon_product_page", "observed_at": "2026-10-22", "evidence_ids": ["E2"]}, {"product_id": "P3", "direction_ids": ["D"], "purchase_lower_bound": None, "purchase_scope": "amazon_product_page", "observed_at": "2026-10-22", "evidence_ids": ["E3"]}]
    assessment = {"directions": [{"direction_id": "D", "niche_id": "N", "status": "shortlist", "growth_pct": None, "season_fit_pct": None, "season": "unknown", "demand": "unknown", "purchase": "positive", "differentiation": "unknown", "business_fit": "positive", "product_ids": ["P1", "P2", "P3"], "review_ids": [], "evidence_ids": ["E1"]}]}
    return config, directions, {"products": products, "offers": []}, assessment


def test_same_purchase_band_ties_and_missing_is_not_zero():
    args = records()
    result = build(*args, [], [])
    ranked = [r for r in result["items"] if r["ranking_id"] == "amazon_purchase_signal"]
    assert {r["entity_id"] for r in ranked} == {"P1", "P2"}
    assert {r["rank"] for r in ranked} == {1}


def test_unknown_criteria_are_not_ordered_against_negative_criteria():
    config, directions, collected, assessment = records()
    directions.append({"id": "D2", "niche_id": "N", "keyword_id": "K2"})
    assessment["directions"].append({**assessment["directions"][0], "direction_id": "D2", "demand": "negative"})
    result = build(config, directions, collected, assessment, [], [])
    ranked = [r for r in result["items"] if r["ranking_id"] == "direction_opportunity"]
    assert len({r["group"] for r in ranked}) == 2
    assert {r["rank"] for r in ranked} == {1}


def test_price_ranking_unavailable_without_verified_comparable_variants():
    config, directions, collected, assessment = records()
    collected["offers"] = [{"offer_id": "O1", "product_id": "P1", "price": 10, "currency": "USD", "variant": None, "observed_at": "2026-10-22", "evidence_ids": ["E1"]}, {"offer_id": "O2", "product_id": "P1", "price": 20, "currency": "USD", "variant": None, "observed_at": "2026-10-22", "evidence_ids": ["E2"]}]
    result = build(config, directions, collected, assessment, [], [])
    assert next(d for d in result["definitions"] if d["id"] == "comparable_price")["status"] == "unavailable"
