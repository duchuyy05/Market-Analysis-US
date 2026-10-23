"""Regressions for arbitrary periods, reproducible snapshots and the local job API."""
import calendar
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from market_radar.io import ROOT
from market_radar.local_app import Jobs, LocalServer, study_summary
from market_radar.__main__ import main
from market_radar.monthly_analysis import timing_profiles, review_tables
from market_radar.seasonal_data import monthly_top_five
from market_radar.seasonality import monthly_period, period_keyword_summary
from market_radar.settings import validate_config
from market_radar.study import new_config, model_json, write_insights


SETTINGS={"min_positive_week_points_per_period":3,"min_completed_years_for_timing":2,"ramp_up_profile_threshold_pct":40}
KEYWORD={"keyword_id":"K-test","keyword":"desk organizer","component_id":"test","id":"test","name":"Desk organizer",
         "demand_scope":"product_family","keyword_origin":"test fixture","tavily_source_count":0}


def fixture(months,years,values,cutoff="2026-10-22"):
    rows=[]
    for year in years:
        for month,value in zip(months,values):
            days=calendar.monthrange(year,month)[1]
            rows.append({"keyword_id":"K-test","year":year,"month":month,"observed_days":days,"calendar_days":days,
                "mean_interest_index":value,"positive_source_points":4,"source_url":"https://example.test/trend",
                "source_raw_file":"raw/test.json","observation_status":"complete_month"})
    return {"as_of_date":cutoff,"market":"US","history_years":years,"history_months":months,"trends":rows,
            "keywords":[KEYWORD],"reviews":[],"customer_needs":[]}


class FlexiblePeriods(unittest.TestCase):
    def test_dashboard_command_and_previous_serve_alias_use_the_same_server(self):
        for command in ("dashboard","serve"):
            with patch("market_radar.local_app.serve") as server:
                main([command,"--port","8766"])
                server.assert_called_once_with(8766)

    def test_csv_summary_uses_price_boundaries_and_counts_review_coverage_by_asin(self):
        products=[{"asin":str(i),"price_usd":value,"niche_ids":["g"]} for i,value in enumerate([9.99,10,20,30,None])]
        data={"products":products,"reviews":[{"asin":"0"},{"asin":"0"}],"keywords":[{},{}],"web_sources":[{}]}
        summary=study_summary(data,{"niches":[{"id":"g","name":"Group"}]})
        self.assertEqual([b["count"] for b in summary["price_bins"]],[1,1,1,1])
        self.assertEqual(summary["missing_prices"],1)
        self.assertEqual(summary["median_price_usd"],15)
        self.assertEqual(summary["reviewed_products"],1)
        self.assertEqual(summary["groups"][0]["reviews"],2)
        self.assertEqual(summary["groups"][0]["reviewed_products"],1)

    def test_completed_q1_of_current_year_is_used_and_peak_is_february(self):
        profiles=timing_profiles(fixture([1,2,3],[2023,2024,2025,2026],[10,100,5]),SETTINGS)
        feb=profiles[1]
        self.assertEqual(feb["completed_years_used"],[2023,2024,2025,2026])
        self.assertEqual(feb["timing_status"],"historical_period_peak")
        self.assertEqual(feb["historical_profile_pct_of_own_period_peak"],100)

    def test_current_q1_is_excluded_when_march_has_not_ended(self):
        p=timing_profiles(fixture([1,2,3],[2024,2025,2026],[10,100,5],"2026-02-10"),SETTINGS)
        self.assertEqual(p[1]["completed_years_used"],[2024,2025])

    def test_custom_nonconsecutive_months_do_not_invent_a_previous_month_ramp(self):
        p=timing_profiles(fixture([2,5],[2022,2023,2024],[10,10]),SETTINGS)
        self.assertEqual([r["month"] for r in p],[2,5])
        self.assertTrue(all(r["timing_status"]=="secondary_period" for r in p))

    def test_generic_monthly_table_keeps_future_blank_and_leap_february(self):
        rows=monthly_period([], [KEYWORD], [2024,2026],date(2026,2,10),[1,2,3])
        self.assertEqual(rows[1]["calendar_days"],29)
        self.assertEqual(rows[-1]["observation_status"],"not_yet_observed")
        self.assertIsNone(rows[-1]["mean_interest_index"])

    def test_review_summary_uses_selected_months(self):
        data=fixture([4,5,6],[2024,2025],[10,20,30])
        summary,_=review_tables(data)
        self.assertEqual({r["month"] for r in summary},{4,5,6})
        self.assertEqual(len(summary),6)

    def test_top_twenty_is_output_limit_independent_of_collection_size(self):
        rows=[{"month":2,"asin":f"P{i:09d}","timing_keyword_id":"K-test","current_purchase_band_lower_bound":100+i,
            "historical_profile_pct_of_own_period_peak":100,"timing_status":"historical_period_peak"} for i in range(23)]
        result=monthly_top_five({"product_month_opportunities":rows},{**SETTINGS,"months":[1,2,3],"top_n":20})
        self.assertEqual(len(result),20)
        self.assertEqual(result[0]["current_purchase_band_lower_bound"],122)

    def test_manual_plan_does_not_call_llm_and_preserves_input_scope(self):
        with tempfile.TemporaryDirectory() as tmp,patch("market_radar.study.model_json") as model:
            config,planning=new_config({"topic":"Desk accessories","keywords":"desk organizer\npencil case","months":[4,6],
                "years":[2021,2022,2023],"use_llm":True},Path(tmp),lambda m:None)
            model.assert_not_called()
        self.assertEqual(config["months"],[4,6])
        self.assertEqual(config["years"],[2021,2022,2023])
        self.assertEqual(planning["mode"],"manual")
        self.assertEqual(config["families"][0]["required_patterns"],["desk","organizer"])

    def test_invalid_model_plan_falls_back_with_explicit_warning(self):
        with tempfile.TemporaryDirectory() as tmp,patch("market_radar.study.model_json",return_value=({"niches":[],"families":[]},"test:free")):
            config,planning=new_config({"topic":"desk organizer","months":[1,2,3]},Path(tmp),lambda m:None)
        self.assertEqual(planning["mode"],"topic_fallback")
        self.assertTrue(planning["warnings"])
        self.assertEqual(len(config["families"]),1)

    def test_invalid_months_and_nested_quantifiers_are_rejected(self):
        config=json.loads((ROOT/"config/seasonal.json").read_text(encoding="utf-8"))
        validate_config(config)  # Existing Q4 patterns remain valid.
        config["months"]=[13]
        with self.assertRaises(ValueError):validate_config(config)
        config["months"]=[1,2,3]
        config["families"][0]["required_patterns"]=["(a+)+"]
        with self.assertRaises(ValueError):validate_config(config)

    def test_finished_period_summary_has_generic_year_columns(self):
        data=fixture([1,2,3],[2021,2022],[10,50,10])
        result=period_keyword_summary([KEYWORD],data["trends"],date(2026,10,22),[1,2,3],[])[0]
        self.assertIn("period_2021_mean_index",result)
        self.assertNotIn("q4_2021_mean_index",result)

    def test_paid_model_is_blocked_before_any_request(self):
        with patch("market_radar.study.load_env",return_value={"OPENROUTER_MODEL":"provider/paid-model"}),patch("market_radar.study.Client") as client:
            with self.assertRaises(RuntimeError):model_json(Path("unused"),"system",{},lambda m:None)
            client.assert_not_called()

    def test_model_commentary_rejects_unknown_evidence_and_numeric_claims(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            data={"category":"Fixture only","history_months":[1,2,3],"as_of_date":"2026-10-22",
                "products":[{"asin":"TEST000001","source_url":"https://example.test/product"}],"keywords":[],"trends":[],"reviews":[]}
            (output/"dataset.json").write_text(json.dumps(data),encoding="utf-8")
            (output/"monthly-analysis.json").write_text(json.dumps({"monthly_keyword_analysis":[]}),encoding="utf-8")
            result={"insights":[{"text":"Invented opinion","evidence_ids":["unknown"]},{"text":"Sales up 500%","evidence_ids":["TEST000001"]}]}
            with patch("market_radar.study.model_json",return_value=(result,"test:free")):
                with self.assertRaises(RuntimeError):write_insights(output,lambda m:None)
            self.assertFalse((output/"llm-insights.json").exists())


class LocalAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.manager=Jobs(Path(cls.temp.name))
        cls.server=LocalServer(("127.0.0.1",0),cls.manager)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def test_bootstrap_never_returns_api_key_values(self):
        with patch("market_radar.local_app.load_env",return_value={"SERPAPI_API_KEY":"private-test-value"}):
            with urlopen(self.base+"/api/bootstrap") as response:
                value=json.load(response)
        self.assertTrue(value["keys"]["SERPAPI_API_KEY"])
        self.assertNotIn("private-test-value",json.dumps(value))

    def test_javascript_has_browser_executable_mime_despite_windows_registry(self):
        with patch("market_radar.local_app.mimetypes.guess_type",return_value=("text/plain",None)):
            with urlopen(self.base+"/assets/workspace.js") as response:
                self.assertEqual(response.headers.get_content_type(),"text/javascript")
                self.assertEqual(response.headers["X-Content-Type-Options"],"nosniff")

    def test_hidden_development_studies_and_jobs_are_not_listed(self):
        config=json.loads((ROOT/"config/seasonal.json").read_text(encoding="utf-8"))
        folder=self.manager.folder("hidden-fixture")
        folder.mkdir(parents=True,exist_ok=True)
        (folder/"collection.json").write_text(json.dumps({"config":config}),encoding="utf-8")
        (folder/"study.json").write_text(json.dumps({"hidden":True}),encoding="utf-8")
        self.assertFalse(any(s["id"]=="hidden-fixture" for s in self.manager.studies()))
        with self.manager.lock:
            self.manager.jobs["hidden-test"]={"id":"hidden-test","status":"completed","hidden":True,"created_at_utc":"2026-10-22T00:00:00+00:00"}
        with urlopen(self.base+"/api/bootstrap") as response:
            body=json.load(response)
        self.assertFalse(any(j["id"]=="hidden-test" for j in body["jobs"]))

    def test_mutation_requires_token_and_same_origin(self):
        for headers in ({"Content-Type":"application/json"},
                        {"Content-Type":"application/json","X-Radar-Token":self.server.token,"Origin":"https://other.example"}):
            req=Request(self.base+"/api/plan",data=b"{}",headers=headers,method="POST")
            with self.assertRaises(HTTPError) as caught:urlopen(req)
            self.assertEqual(caught.exception.code,403)

    def test_private_files_and_traversal_cannot_be_downloaded(self):
        for path in ("/api/.env","/runs/seasonal-gifts-us/raw/anything.json","/runs/../.env","/runs/seasonal-gifts-us/collection.json"):
            with self.assertRaises(HTTPError) as caught:urlopen(self.base+path)
            self.assertEqual(caught.exception.code,404)
        with self.assertRaises(ValueError):self.manager.folder("../outside")

    def test_plan_runs_as_background_job_and_survives_manager_restart(self):
        body={"topic":"Desk accessories","keywords":"desk organizer","months":[1,2,3],"years":[2022,2023,2024],"use_llm":False}
        req=Request(self.base+"/api/plan",data=json.dumps(body).encode(),headers={"Content-Type":"application/json","X-Radar-Token":self.server.token},method="POST")
        with urlopen(req) as response:
            self.assertEqual(response.status,202)
            job=json.load(response)
        for _ in range(100):
            result=self.manager.get(job["id"])
            if result["status"] not in ("queued","running"):break
            time.sleep(.01)
        self.assertEqual(result["status"],"completed")
        self.assertEqual(result["result"]["config"]["months"],[1,2,3])
        restored=Jobs(Path(self.temp.name))
        self.assertEqual(restored.get(job["id"])["status"],"completed")


if __name__=="__main__":unittest.main()
