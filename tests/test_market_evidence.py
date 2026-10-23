"""Source-type boundaries, exact ASIN joins and bounded free-quota collection."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_radar.io import save_json
from market_radar.normalize import normalize_product, deduplicate_review_rows
from market_radar.market_evidence import build_market_evidence
from market_radar.supplement import SupplementRun, free_searches_left, supplement_targets
from market_radar.study import select_review_evidence


class MarketEvidenceTests(unittest.TestCase):
    def test_ai_review_sample_covers_products_and_opposing_ratings_before_repetition(self):
        row=lambda asin,rid,rating,kind="full":{"asin":asin,"review_id":rid,"rating_out_of_5":rating,"review_text_kind":kind,"review_date":"2026-10-01","review_text":"Source text","verified_purchase":True}
        data={"products":[{"asin":a} for a in "ABC"],"reviews":[row("A","A-low",1),row("A","A-high",5),
            row("A","A-other",2),row("B","B-full",4),row("B","B-excerpt",None,"excerpt"),row("C","C-excerpt",None,"excerpt")]}
        selected=select_review_evidence(data,limit=4)
        self.assertEqual([r["asin"] for r in selected[:3]],list("ABC"))
        self.assertEqual([r["review_id"] for r in selected],["A-low","B-full","C-excerpt","A-high"])

    def test_full_review_suppresses_same_quote_from_another_source_without_merging_asins(self):
        quote="These beautiful lights are easy to use and look very nice"
        rows=[{"asin":"A","review_id":"snippet-A","review_text_kind":"excerpt","review_text":"..."+quote+"..."},
              {"asin":"A","review_id":"hash-A","review_text_kind":"full","review_text":quote+" in the garden."},
              {"asin":"B","review_id":"snippet-B","review_text_kind":"excerpt","review_text":quote}]
        self.assertEqual([r["review_id"] for r in deduplicate_review_rows(rows)],["hash-A","snippet-B"])

    def test_linked_quotes_are_not_ai_summary_or_full_reviews(self):
        quote={"snippet":"The lights look lovely.","link":"https://www.amazon.com/portal/customer-reviews/srp/-/R123ABC"}
        response={"product_results":{"title":"Christmas lights"},"reviews_information":{
            "authors_reviews":None,"summary":{"text":"AI GENERATED: Everyone loves these", "insights":[
                {"examples":[quote,quote,{"snippet":"Bad origin","link":"https://example.test/customer-reviews/R444"},
                             {"snippet":"No evidence link"}]}]},
            "other_countries_reviews":[{"language":{"code":"de"},"text":"Deutsch"},
                {"language":{"code":"en"},"country":{"name":"Canada"},"text":"Lovely gift","rating":4}]}}
        envelope={"response":response,"parameters":{"asin":"B000000001"},"raw_file":"raw/test.json","fetched_at_utc":"2026-10-22T00:00:00+00:00"}
        _,reviews=normalize_product(envelope,{"item":{},"search_sources":[]},"P1")
        self.assertEqual(len(reviews),2)
        self.assertEqual(reviews[0]["review_country_explicit"],"Canada")
        excerpt=reviews[1]
        self.assertEqual(excerpt["review_text_kind"],"excerpt")
        self.assertEqual(excerpt["review_id"],"R123ABC")
        self.assertIsNone(excerpt["star_rating"])
        self.assertIsNone(excerpt["review_date"])
        self.assertIsNone(excerpt["verified_purchase"])
        self.assertNotIn("AI GENERATED",str(reviews))

    def test_keyword_join_keeps_search_badges_separate_and_missing_values_unknown(self):
        families=[{"id":"lights","niche_id":"gifts","keyword":"Christmas lights","amazon_query":"Christmas lights","required_patterns":["Christmas","lights"]},
                  {"id":"empty","niche_id":"gifts","keyword":"empty","amazon_query":"empty","required_patterns":["empty"]}]
        product=lambda asin:{"asin":asin,"family_ids":["lights"],"product_name":"Christmas lights","price_usd":9,"source_url":"https://www.amazon.com/dp/"+asin}
        data={"products":[product("B000000001"),product("B000000002")],"reviews":[]}
        analysis={"monthly_keyword_analysis":[{"keyword_id":"K-lights","month":12,"timing_status":"historical_period_peak","timing_supported":True}]}
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            save_json(output/"raw/search.json",{"parameters":{"engine":"amazon","amazon_domain":"amazon.com","k":"Christmas lights"},"fetched_at_utc":"2026-10-22T00:00:00Z","response":{"organic_results":[
                {"asin":"B000000001","title":"Christmas lights","bought_last_month":"2K+ bought in past month"},
                {"asin":"B000000099","title":"Christmas lights","bought_last_month":"90K+ bought in past month"}]}})
            manifest={"sources":{"search_lights":"raw/search.json"},"config":{"families":families}}
            evidence,linked,summary=build_market_evidence(output,data,analysis,manifest)
            self.assertEqual(len(evidence),1)
            self.assertEqual(linked[0]["purchase_source_type"],"search_listing")
            self.assertEqual(linked[0]["purchase_lower_bound"],2000)
            self.assertIsNone(linked[1]["purchase_lower_bound"])
            self.assertEqual(summary[1]["coverage_status"],"no_products_collected")
            save_json(output/"raw/detail.json",{"parameters":{"engine":"amazon_product","amazon_domain":"amazon.com","asin":"B000000001"},"fetched_at_utc":"2026-10-22T01:00:00Z","response":{"product_results":{"title":"Christmas lights","bought_last_month":"1K+ bought in past month"}}})
            manifest["sources"]["product_B000000001"]="raw/detail.json"
            evidence,linked,_=build_market_evidence(output,data,analysis,manifest)
            self.assertEqual(len(evidence),2)
            self.assertEqual(linked[0]["purchase_source_type"],"product_listing")
            self.assertEqual(linked[0]["purchase_lower_bound"],1000)  # source priority, not largest badge

    def test_quota_rejects_paid_unknown_and_exhausted_plans(self):
        for value in ({"plan_monthly_price":10,"plan_searches_left":90},
                      {"plan_searches_left":90}, {"plan_monthly_price":0,"plan_searches_left":0}):
            with self.subTest(value=value),patch("market_radar.supplement.urlopen",return_value=io.StringIO(json.dumps(value))):
                with self.assertRaises(RuntimeError):
                    free_searches_left({"SERPAPI_API_KEY":"fake-key"})

    def test_reserved_quota_stops_before_any_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            save_json(output/"collection.json",{})
            save_json(output/"dataset.json",{})
            with patch("market_radar.supplement.free_searches_left",return_value=50),patch("market_radar.supplement.Client") as client:
                with self.assertRaisesRegex(RuntimeError,"50"):
                    SupplementRun(output,45,event=lambda _:None).collect()
                client.assert_not_called()

    def test_only_untried_devices_and_one_matching_extra_product_per_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            save_json(output/"raw/desktop.json",{"parameters":{"device":"desktop"}})
            save_json(output/"raw/mobile.json",{"parameters":{"device":"mobile"}})
            save_json(output/"raw/search.json",{"parameters":{"k":"Christmas lights"},"response":{"organic_results":[
                {"asin":"B000000001","title":"Christmas lights","bought_last_month":"10K+ bought in past month"},
                {"asin":"B000000002","title":"Christmas lights","bought_last_month":"9K+ bought in past month","sponsored":True},
                {"asin":"B000000003","title":"Halloween lights","bought_last_month":"8K+ bought in past month"},
                {"asin":"B000000004","title":"Christmas lights","bought_last_month":"2K+ bought in past month"}]}})
            manifest={"config":{"families":[{"id":"lights","required_patterns":["Christmas","lights"]}]},
                "sources":{"product_B000000001":"raw/desktop.json","reviews_mobile_B000000001":"raw/mobile.json","search_lights":"raw/search.json"}}
            targets=supplement_targets(output,manifest,{"products":[{"asin":"B000000001"}],"reviews":[]})
            self.assertEqual([(p["asin"],p["device"]) for p in targets],[("B000000001","tablet"),("B000000004","desktop")])

    def test_supplement_caps_calls_and_appends_without_overwriting_originals(self):
        class FakeClient:
            def __init__(self,output,env,event=None):
                self.output=output; self.calls=[]; self.max_calls={}
            def request(self,provider,params,cache=True):
                self.calls.append({"provider":provider})
                raw={"parameters":params,"response":{"product_results":{"asin":params["asin"],"title":"Christmas lights"}},
                     "fetched_at_utc":"2026-10-22T01:00:00Z","raw_file":"raw/new.json"}
                save_json(self.output/"raw/new.json",raw)
                return raw
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            save_json(output/"raw/original.json",{"original":True})
            original=(output/"raw/original.json").read_bytes()
            save_json(output/"collection.json",{"sources":{},"request_history":[]})
            save_json(output/"dataset.json",{"products":[{"asin":"B000000001"},{"asin":"B000000002"}],"reviews":[]})
            with patch("market_radar.supplement.free_searches_left",return_value=1),patch("market_radar.supplement.load_env",return_value={}),patch("market_radar.supplement.Client",FakeClient):
                result=SupplementRun(output,12,event=lambda _:None,reserve_searches=0).collect()
            self.assertEqual(result["requests_made"],1)
            self.assertEqual(result["max_requests"],1)
            self.assertEqual((output/"raw/original.json").read_bytes(),original)
            manifest=json.loads((output/"collection.json").read_text(encoding="utf-8"))
            path=manifest["supplement_sources"]["B000000001"][0]
            self.assertTrue(path.startswith("supplements/"))
            self.assertEqual(json.loads((output/path).read_text(encoding="utf-8"))["raw_file"],path)


if __name__=="__main__":
    unittest.main()
