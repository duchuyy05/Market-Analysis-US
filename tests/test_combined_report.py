"""Combined reports preserve deterministic tables and never pass stale/unreviewed fragments as approved."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from market_radar.io import ROOT,save_json
from market_radar.combined_context import enrich_pack
from market_radar.combined_report import generate_combined_report,run_combined_report
from market_radar.llm_report import evidence_pack,paragraph_digest,request_payload,review_saved_report
from market_radar.seasonal_report import make_blocks,block_render
from test_llm_report import FakeClient


class CombinedReport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.output=Path(self.temp.name)
        for name in ("dataset.json","monthly-analysis.json","collection.json"):
            shutil.copyfile(ROOT/"data/seasonal-gifts-us"/name,self.output/name)
        self.data=json.loads((self.output/"dataset.json").read_text(encoding="utf-8"))
        self.analysis=json.loads((self.output/"monthly-analysis.json").read_text(encoding="utf-8"))
        self.config=json.loads((self.output/"collection.json").read_text(encoding="utf-8"))["config"]
        self.pack=enrich_pack(evidence_pack(self.output),self.data,self.analysis)
        (self.output/"report.md").write_text("Original Python report",encoding="utf-8")
        (self.output/"report.html").write_text("Original Python HTML",encoding="utf-8")
        FakeClient.requests=[]
        self.env={"OPENROUTER_API_KEY":"fixture-private-key","OPENROUTER_MODEL":"fixture:free"}

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def answer(task):
        review=next(c for c in task["evidence"].values() if c["type"]=="review" and len(c["text"])>40)
        pid=review["product_id"]
        paragraph=lambda kind,text,ids=None,quote=None:{"section":kind,"text":text,"evidence_ids":ids or [pid],"quote":quote}
        quote={"id":review["id"],"text":review["text"][:80]}
        return [paragraph("observations","Dữ liệu lịch sử được dùng để đối chiếu mùa vụ trong kỳ khảo sát. Nhãn mua hiện tại cần được đọc riêng."),
            paragraph("observations","Sản phẩm được dẫn là một trường hợp trong mẫu thu thập. Cần đọc thông tin nguồn trước khi chọn thử."),
            paragraph("reviews","Một nội dung nhận xét có trong dữ liệu được trích bên dưới. Ý kiến này gắn với sản phẩm được dẫn.",[review["id"]],quote),
            paragraph("reviews","Đoạn trích cần được hiểu trong phạm vi một phản hồi. Nội dung này chưa đại diện cho mọi khách hàng.",[review["id"]],quote),
            paragraph("recommendations","Nên đọc mô tả sản phẩm và đối chiếu nhận xét trước khi chọn mẫu thử. Chưa có kết luận hiệu quả kinh doanh."),
            paragraph("gaps","Dữ liệu hiện tại chưa phải khảo sát đại diện thị trường. Chưa có cơ sở dự báo doanh số trong tương lai.")]

    def invoke(self,responses):
        FakeClient.responses=copy.deepcopy(responses)
        with patch("market_radar.llm_report.load_env",return_value=self.env),patch("market_radar.llm_report.Client",FakeClient):
            return run_combined_report(self.output,ai=True,max_calls=4,event=lambda _:None)

    def complete_answers(self):
        answers=[self.answer(t) for t in self.pack["tasks"]]
        first=answers[0]
        answers.append([first[0],first[4],first[5]])
        return answers

    def assert_tables_preserved(self):
        report=(self.output/"report-combined.md").read_text(encoding="utf-8")
        for block in make_blocks(self.data,self.analysis,self.config,combined=True):
            if block["kind"]=="table":
                self.assertIn(block_render([block])[0],report)
        for family in self.config["families"]:
            self.assertNotIn(family["idea_vi"],report)
        return report

    def test_enriched_input_has_exact_ranks_history_and_scoped_bounded_review_sample(self):
        for task in self.pack["tasks"]:
            payload=request_payload(task)
            self.assertNotIn("idea_vi",json.dumps(payload))
            self.assertIn("monthly_shortlist",payload["computed"])
            for row in payload["computed"]["monthly_shortlist"]:
                product=task["evidence"][row["product_id"]]
                original=next(r for r in self.analysis["monthly_top5"] if r["asin"]==product["asin"] and r["month"]==row["month"])
                self.assertEqual(row["rank_in_month"],original["rank_in_month"])
                self.assertEqual(row["snapshot_purchase_badge"],original["current_purchase_badge"])
                self.assertIn(row["timing_id"],payload["evidence"])
            self.assertLessEqual(sum(c["type"]=="review" for c in payload["evidence"].values()),12)
            for card in payload["evidence"].values():
                if card["type"]=="timing":
                    original=[r for r in self.data["trends"] if r["keyword_id"]==task["evidence"][card["id"]]["source_id"]]
                    self.assertEqual([r["mean_interest_index"] for r in card["history"]],[r["mean_interest_index"] for r in original])

    def test_live_mode_uses_only_openrouter_and_places_prose_next_to_niche_tables(self):
        original={p.name:p.read_bytes() for p in self.output.iterdir() if p.is_file()}
        result=self.invoke(self.complete_answers())
        self.assertEqual(result["mode"],"combined_with_llm")
        self.assertEqual(result["llm_paragraphs"],21)
        self.assertFalse(result["config_ideas_included"])
        self.assertFalse(result["manual_review_recorded"])
        for name,content in original.items(): self.assertEqual((self.output/name).read_bytes(),content)
        report=self.assert_tables_preserved()
        for task in self.pack["tasks"]:
            start=report.index(task["title"],report.index("## 3."))
            end=report.index("#### Sản phẩm đối chiếu",start)
            self.assertIn(self.answer(task)[0]["text"],report[start:end])
        payload=json.loads(FakeClient.requests[-1]["messages"][1]["content"])
        self.assertEqual(payload["request_type"],"overview")
        self.assertEqual(len(payload["computed"]["niches"]),len(self.pack["tasks"]))
        self.assertIn("chưa có lượt đọc đối chiếu",report)
        self.assertFalse(list(self.output.glob("report-llm*")))
        run=self.output/result["llm_run"]
        self.assertFalse(list(run.glob("*.html")))
        self.assertFalse(list(run.glob("*.md")))
        self.assertNotIn("report-llm-draft",report)

    def test_offline_without_llm_still_has_full_tables_and_never_calls_an_api(self):
        with patch("market_radar.llm_report.Client") as client:
            result=run_combined_report(self.output,event=lambda _:None)
            client.assert_not_called()
        self.assertEqual(result["mode"],"python_only")
        self.assertEqual(result["llm_paragraphs"],0)
        self.assert_tables_preserved()

    def test_rate_limit_leaves_complete_python_report_with_explicit_missing_ai(self):
        result=self.invoke([RuntimeError("HTTP 429; no retry")])
        self.assertEqual(len(FakeClient.requests),1)
        self.assertEqual(result["mode"],"python_only")
        self.assertIn("chưa có diễn giải LLM",self.assert_tables_preserved())

    def test_failed_rewrite_preserves_last_usable_llm_and_records_failed_attempt(self):
        original=self.invoke(self.complete_answers())
        result=self.invoke([RuntimeError("HTTP 404; no retry")])
        self.assertEqual(result["llm_run"],original["llm_run"])
        self.assertEqual(result["llm_paragraphs"],21)
        self.assertEqual(result["last_ai_attempt"]["status"],"failed")
        self.assertEqual(result["last_ai_attempt"]["calls"],1)
        self.assertNotEqual(result["last_ai_attempt"]["run_directory"],result["llm_run"])
        self.assert_tables_preserved()

    def test_stale_llm_is_not_merged_into_current_numbers(self):
        self.invoke(self.complete_answers())
        path=self.output/"llm-report-evaluation.json"
        evaluation=json.loads(path.read_text(encoding="utf-8")); evaluation["input_sha256"]="old-checksum"
        save_json(path,evaluation)
        result=generate_combined_report(self.output,event=lambda _:None)
        self.assertEqual(result["mode"],"python_only")
        self.assertTrue(any("phiên bản dữ liệu cũ" in w for w in result["warnings"]))
        self.assert_tables_preserved()

    def test_reader_rejected_paragraphs_stay_out_even_when_original_passed_automatic_checks(self):
        self.invoke(self.complete_answers())
        evaluation=json.loads((self.output/"llm-report-evaluation.json").read_text(encoding="utf-8"))
        run=self.output/evaluation["run_directory"]
        sections=json.loads((run/"sections.json").read_text(encoding="utf-8"))
        decisions=[{"task":s["id"],"paragraph_sha256":paragraph_digest(p),"decision":"keep","reason":"Đã đọc đối chiếu."}
                   for s in sections for p in s["paragraphs"]]
        decisions[0].update(decision="reject",reason="Không đủ bằng chứng cho đoạn này.")
        review_saved_report(self.output,evaluation["run_directory"],decisions,reviewer="Fixture reader")
        result=generate_combined_report(self.output,event=lambda _:None)
        self.assertTrue(result["manual_review_recorded"])
        self.assertEqual(result["llm_paragraphs"],20)
        # Tampering with the reviewed file cannot reintroduce a rejected original.
        save_json(run/"reviewed-sections.json",sections)
        result=generate_combined_report(self.output,event=lambda _:None)
        self.assertEqual(result["llm_paragraphs"],20)
        self.assertTrue(any("quyết định giữ" in w for w in result["warnings"]))


if __name__=="__main__":
    unittest.main()
