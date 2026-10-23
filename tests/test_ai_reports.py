"""AI reports reuse the saved dataset; errors must not relabel an old report as new AI."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from market_radar.io import ROOT, save_json
from market_radar.local_app import Jobs, LocalServer, report_status
from market_radar.seasonal_report import generate_report


class AIReports(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Jobs(Path(self.temp.name))
        self.output = self.manager.folder("report-fixture")
        self.output.mkdir()
        for name in ("dataset.json", "monthly-analysis.json", "collection.json"):
            shutil.copyfile(ROOT/"data/seasonal-gifts-us"/name, self.output/name)
        save_json(self.output/"study.json", {"status":"completed", "display_name":"Report fixture"})
        generate_report(self.output)
        self.server = LocalServer(("127.0.0.1",0), self.manager)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request_report(self):
        request = Request(self.base+"/api/report", data=b'{"study_id":"report-fixture"}',
                          headers={"Content-Type":"application/json", "X-Radar-Token":self.server.token}, method="POST")
        with urlopen(request) as response:
            self.assertEqual(response.status,202)
            job = json.load(response)
        for _ in range(300):
            job = self.manager.get(job["id"])
            if job["status"] not in {"queued","running"}:
                break
            time.sleep(.01)
        self.assertNotIn(job["status"], {"queued","running"})
        return job

    def test_ai_job_calls_model_without_collection_or_rebuilding_and_exports_both_formats(self):
        original = (self.output/"dataset.json").read_bytes()
        asin = json.loads(original)["products"][0]["asin"]
        answer = {"insights":[{"text":"Cần đối chiếu kích cỡ và nhận xét trước khi chọn mẫu thử.","evidence_ids":[asin]}]}
        with patch("market_radar.local_app.load_env",return_value={"OPENROUTER_API_KEY":"private-fixture", "OPENROUTER_MODEL":"test:free"}), \
             patch("market_radar.study.model_json",return_value=(answer,"test:free")) as model, \
             patch("market_radar.seasonal.SeasonalRun") as collector, \
             patch("market_radar.seasonal_data.build_seasonal_data") as rebuild, \
             patch("market_radar.seasonal_data.verify_seasonal_data"):
            job = self.request_report()
        self.assertEqual(job["status"],"completed")
        self.assertTrue(job["result"]["llm_updated"])
        model.assert_called_once()
        collector.assert_not_called()
        rebuild.assert_not_called()
        self.assertEqual(original,(self.output/"dataset.json").read_bytes())
        status = report_status(self.output)
        self.assertEqual(status["mode"],"rules_plus_llm")
        self.assertEqual(status["llm"]["model"],"test:free")
        self.assertEqual(status["llm"]["insight_count"],1)
        self.assertTrue(status["current"])
        self.assertEqual(self.manager.studies()[0]["report"],status)
        facts = json.loads((self.output/"ai-input.json").read_text(encoding="utf-8"))
        self.assertEqual(facts["months"],[10,11,12])
        self.assertEqual(len(facts["monthly_ranking"]),15)
        self.assertTrue(facts["web_context"])
        self.assertIn("not representative",facts["input_scope"])
        for name in ("report.html","report.md"):
            with urlopen(self.base+f"/runs/report-fixture/{name}?download=1") as response:
                self.assertEqual(response.headers["Content-Disposition"],f'attachment; filename="{name}"')
                self.assertIn("Phân tích AI",response.read().decode("utf-8"))
        self.assertIn("URLSearchParams(location.search)",(self.output/"report.html").read_text(encoding="utf-8"))

    def test_model_failure_keeps_report_available_and_does_not_claim_ai_was_written(self):
        with patch("market_radar.local_app.load_env",return_value={"OPENROUTER_API_KEY":"private-fixture", "OPENROUTER_MODEL":"test:free"}), \
             patch("market_radar.study.model_json",side_effect=RuntimeError("HTTP 429; no retry")), \
             patch("market_radar.seasonal_data.verify_seasonal_data"):
            job = self.request_report()
        self.assertEqual(job["status"],"completed_with_warnings")
        self.assertFalse(job["result"]["llm_updated"])
        self.assertEqual(job["result"]["report"]["mode"],"deterministic_source_backed_no_llm")
        self.assertIsNone(job["result"]["report"]["llm"])
        self.assertTrue(job["result"]["report"]["available"])
        self.assertEqual(self.manager.studies()[0]["status"],"completed")
        self.assertIn("HTTP 429",self.manager.studies()[0]["report_warnings"][0])

    def test_changed_dataset_or_stale_insights_cannot_show_ai_status(self):
        checksum = hashlib.sha256((self.output/"dataset.json").read_bytes()).hexdigest()
        save_json(self.output/"llm-insights.json", {"input_sha256":checksum,"model":"test:free","insights":[{}]})
        build = json.loads((self.output/"report-build.json").read_text(encoding="utf-8"))
        build["mode"] = "rules_plus_llm"
        save_json(self.output/"report-build.json",build)
        self.assertIsNotNone(report_status(self.output)["llm"])
        with (self.output/"dataset.json").open("a",encoding="utf-8") as stream:
            stream.write("\n")
        self.assertFalse(report_status(self.output)["current"])
        self.assertIsNone(report_status(self.output)["llm"])

    def test_ai_report_rejects_missing_key_or_paid_model_before_starting(self):
        for env in ({}, {"OPENROUTER_API_KEY":"private-fixture","OPENROUTER_MODEL":"paid/model"}):
            before = len(self.manager.jobs)
            with patch("market_radar.local_app.load_env",return_value=env):
                with self.assertRaises(HTTPError) as error:
                    self.request_report()
                self.assertEqual(error.exception.code,400)
                self.assertEqual(len(self.manager.jobs),before)

    def test_keyword_only_commentary_cannot_pass_as_product_review_evidence(self):
        from market_radar.study import write_insights
        data=json.loads((self.output/"dataset.json").read_text(encoding="utf-8"))
        answer={"insights":[{"text":"Đề xuất sản phẩm chung chung.","evidence_ids":[data["keywords"][0]["keyword_id"]]}]}
        with patch("market_radar.study.model_json",return_value=(answer,"test:free")):
            with self.assertRaises(RuntimeError):
                write_insights(self.output,lambda _:None)
        self.assertFalse((self.output/"llm-insights.json").exists())


if __name__ == "__main__":
    unittest.main()
