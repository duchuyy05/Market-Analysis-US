"""LLM interpretations retain evidence and failures without extra report exports."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from market_radar.io import ROOT
from market_radar.llm_report import (evidence_pack, paragraph_digest, parse_answer, request_payload,
                                     review_saved_report, run_llm_report, validate_paragraph)


class FakeClient:
    responses=[]
    requests=[]

    def __init__(self, output, env, event=None):
        self.output=output
        self.calls=[]
        self.max_calls={}

    def request(self, provider, params, *, cache=True):
        assert provider=="openrouter"
        assert self.max_calls["serpapi"]==self.max_calls["tavily"]==0
        assert cache is False
        self.calls.append(provider)
        self.requests.append(params)
        response=self.responses.pop(0)
        if isinstance(response,Exception):
            raise response
        return {"raw_file":"raw/fixture.json","response":{"model":"fixture:free", "usage":{"cost":0},
                "choices":[{"message":{"content":json.dumps({"paragraphs":response},ensure_ascii=False)}}]}}


class LLMReport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.output=Path(self.temp.name)
        for name in ("dataset.json","monthly-analysis.json","collection.json"):
            shutil.copyfile(ROOT/"data/seasonal-gifts-us"/name,self.output/name)
        (self.output/"report.md").write_text("Original Python report",encoding="utf-8")
        (self.output/"report.html").write_text("Original Python HTML",encoding="utf-8")
        self.pack=evidence_pack(self.output)
        self.env={"OPENROUTER_API_KEY":"fixture-private-key","OPENROUTER_MODEL":"fixture:free"}
        FakeClient.requests=[]

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def paragraphs(task):
        cards=task["evidence"]
        review=next(c for c in cards.values() if c["type"]=="review" and len(c["text"])>=40)
        product=cards[review["product_id"]]
        return [
            {"section":"observations","text":"Mẫu thu thập có sản phẩm thuộc nhóm đang khảo sát. Cần đọc nhãn mua tại thời điểm lấy dữ liệu.",
             "evidence_ids":[product["id"]],"quote":None},
            {"section":"reviews","text":"Một nhận xét trong mẫu cần được đọc cùng nội dung trích dẫn. Đây là ý kiến cá nhân về sản phẩm được dẫn.",
             "evidence_ids":[review["id"],product["id"]],"quote":{"id":review["id"],"text":review["text"][:80]}},
            {"section":"recommendations","text":"Nên đối chiếu thông tin trên listing trước khi chọn mẫu thử. Dữ liệu hiện tại chưa xác nhận hiệu quả kinh doanh.",
             "evidence_ids":[product["id"]],"quote":None}]

    def invoke(self,responses,max_calls=6):
        FakeClient.responses=copy.deepcopy(responses)
        with patch("market_radar.llm_report.load_env",return_value=self.env), \
             patch("market_radar.llm_report.Client",FakeClient):
            return run_llm_report(self.output,max_calls=max_calls,event=lambda _:None)

    def test_model_payload_has_short_ids_and_scoped_evidence_only(self):
        for task in self.pack["tasks"]:
            payload=request_payload(task)
            self.assertTrue(payload["evidence"])
            for identifier,card in payload["evidence"].items():
                self.assertEqual(identifier,card["id"])
                self.assertNotIn("source_id",card)
                self.assertNotIn("source_url",card)
                self.assertNotIn("asin",card)
                self.assertIn(task["id"],task["evidence"][identifier]["niche_ids"])
                self.assertIn("source_id",self.pack["evidence"][identifier])

    def test_validator_rejects_wrong_ids_quotes_numbers_and_cross_product_evidence(self):
        cards=self.pack["evidence"]
        valid=self.paragraphs(self.pack["tasks"][0])[1]
        self.assertEqual(validate_paragraph(valid,cards),[])
        for field,value in (("evidence_ids",["R-invented"]),("text","Sản phẩm này đã bán được 100000 đơn tại Mỹ."),
                            ("section",[]),("quote",{"id":valid["quote"]["id"],"text":"This sentence is completely made up."})):
            item=copy.deepcopy(valid); item[field]=value
            self.assertTrue(validate_paragraph(item,cards))
        item=copy.deepcopy(valid)
        other=next(c for c in cards.values() if c["type"]=="product" and c["id"] not in item["evidence_ids"])
        item["evidence_ids"]=[valid["quote"]["id"],other["id"]]
        self.assertTrue(any("ASIN" in e for e in validate_paragraph(item,cards)))
        item=copy.deepcopy(valid)
        timing=next(c for c in cards.values() if c["type"]=="timing" and c["family_id"] not in cards[valid["quote"]["id"]]["family_ids"])
        item["evidence_ids"]=[valid["quote"]["id"],timing["id"]]
        self.assertTrue(any("Trends" in e for e in validate_paragraph(item,cards)))

    def test_repairs_preserve_good_paragraphs_checks_and_baseline_without_recollection(self):
        tasks=self.pack["tasks"]
        first=self.paragraphs(tasks[0]); wrong=copy.deepcopy(first[1]); wrong["evidence_ids"]=["R-invented"]
        # Some models repeat the good paragraphs instead of repairing only the bad one.
        answers=[[first[0],wrong,first[2]],first]
        answers.extend(self.paragraphs(t) for t in tasks[1:])
        answers.append([first[0]])
        original={name:(self.output/name).read_bytes() for name in ("dataset.json","report.md","report.html")}
        result=self.invoke(answers)
        self.assertEqual(result["status"],"generated_needs_reading")
        self.assertEqual(result["calls"],5)
        self.assertEqual(result["accepted_paragraphs"],10)
        self.assertEqual(result["rejected_paragraphs"],3)
        self.assertEqual(result["reported_cost_usd"],0)
        self.assertIn("repair_only_rejected_paragraphs",json.loads(FakeClient.requests[1]["messages"][1]["content"]))
        for name,content in original.items():
            self.assertEqual((self.output/name).read_bytes(),content)
        checks=json.dumps(result["attempts"],ensure_ascii=False)
        self.assertIn("Cần một đến ba mã ngắn",checks)
        self.assertIn("bỏ đoạn lặp",checks)
        sections=json.loads((self.output/result["run_directory"]/"sections.json").read_text(encoding="utf-8"))
        paragraphs=[p for s in sections for p in s["paragraphs"]]
        self.assertIn(first[0],paragraphs)
        self.assertIn(first[1],paragraphs)
        self.assertEqual(sorted(p.name for p in self.output.glob("report*")),["report.html","report.md"])
        self.assertFalse(list((self.output/result["run_directory"]).glob("*.md")))
        self.assertFalse(list((self.output/result["run_directory"]).glob("*.html")))
        self.assertTrue((self.output/result["run_directory"]/"prompt.txt").exists())
        self.assertTrue((self.output/result["run_directory"]/"input.json").exists())

    def test_reserves_first_attempt_for_later_niches_and_overview(self):
        first=self.paragraphs(self.pack["tasks"][0])
        answers=[[first[0]]]
        answers.extend(self.paragraphs(t) for t in self.pack["tasks"][1:])
        answers.append([first[0]])
        result=self.invoke(answers,max_calls=4)
        self.assertEqual(result["calls"],4)
        self.assertEqual(result["status"],"partial")
        self.assertEqual([json.loads(r["messages"][1]["content"])["id"] for r in FakeClient.requests],
                         [t["id"] for t in self.pack["tasks"]]+["overview"])

    def test_quota_error_stops_and_retains_explicit_failure_metadata(self):
        result=self.invoke([RuntimeError("HTTP 429; no retry")])
        self.assertEqual(result["calls"],1)
        self.assertEqual(result["status"],"failed")
        self.assertEqual(result["accepted_paragraphs"],0)
        self.assertIn("HTTP 429",(self.output/"llm-report-evaluation.json").read_text(encoding="utf-8"))
        self.assertEqual((self.output/"report.md").read_text(encoding="utf-8"),"Original Python report")

    def test_paid_model_or_stale_input_rejected_before_api_call(self):
        with patch("market_radar.llm_report.load_env",return_value=self.env), \
             patch("market_radar.llm_report.Client") as client:
            with self.assertRaises(ValueError):
                run_llm_report(self.output,model="paid/model")
            (self.output/"dataset.json").write_bytes((self.output/"dataset.json").read_bytes()+b"\n")
            with self.assertRaises(RuntimeError):
                run_llm_report(self.output)
            client.assert_not_called()
        self.assertFalse((self.output/"llm-reports").exists())

    def test_malformed_json_is_an_explicit_parse_failure(self):
        for envelope in ({},{"response":{"choices":[{"message":{"content":"not json"}}]}}):
            with self.assertRaises(RuntimeError):
                parse_answer(envelope)

    def test_empty_completion_at_token_limit_is_distinguished_from_bad_json(self):
        with self.assertRaisesRegex(RuntimeError,"hết ngân sách token"):
            parse_answer({"response":{"choices":[{"finish_reason":"length","message":{"content":None}}]}})

    def test_manual_reading_removes_prose_without_rewriting_or_losing_originals(self):
        answers=[self.paragraphs(t) for t in self.pack["tasks"]]
        answers.append([answers[0][0]])
        result=self.invoke(answers)
        run=self.output/result["run_directory"]
        original_sections=(run/"sections.json").read_bytes()
        original_input=(run/"input.json").read_bytes()
        sections=json.loads(original_sections)
        decisions=[{"task":s["id"],"paragraph_sha256":paragraph_digest(p),"decision":"keep",
                    "reason":"Đã đọc đối chiếu nội dung với nguồn được dẫn."} for s in sections for p in s["paragraphs"]]
        # An incorrect checksum must fail before changing files.
        wrong=copy.deepcopy(decisions); wrong[0]["paragraph_sha256"]="wrong"
        with self.assertRaises(ValueError):
            review_saved_report(self.output,result["run_directory"],wrong)
        decisions[0].update(decision="reject",reason="Lý do đối chiếu được ghi rõ, không sửa văn bản model.")
        reviewed=review_saved_report(self.output,result["run_directory"],decisions)
        self.assertEqual(reviewed["status"],"partial")
        self.assertEqual(reviewed["accepted_paragraphs"],9)
        self.assertEqual(reviewed["automatic_accepted_paragraphs"],10)
        self.assertEqual(reviewed["manual_review"]["rejected_paragraphs"],1)
        self.assertEqual((run/"sections.json").read_bytes(),original_sections)
        self.assertEqual((run/"input.json").read_bytes(),original_input)
        self.assertTrue((run/"automatic-evaluation.json").exists())
        latest=json.loads((self.output/"llm-report-evaluation.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["manual_review"]["reviewed_paragraphs"],10)
        self.assertFalse(list(run.glob("*.md")))
        self.assertFalse(list(run.glob("*.html")))
        self.assertEqual((self.output/"report.md").read_text(encoding="utf-8"),"Original Python report")


if __name__=="__main__":
    unittest.main()
