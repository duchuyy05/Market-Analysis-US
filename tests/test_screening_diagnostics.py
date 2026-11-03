"""Sparse measured series and source failures require different recovery."""
from copy import deepcopy

from market_research.config import validate_config
from market_research.reporting.screening_diagnostic import export_screening_diagnostic
from market_research.workflow.diagnostics import screening_diagnostics


def fixture():
    config = validate_config({"brief": "Compact holiday gift models", "as_of_date": "2026-11-02",
        "trends": {"history_scope": "seasonal", "history_months": [10, 11, 12]},
        "limits": {"serpapi_requests": 30, "trends_serpapi_requests": 8}})
    rows = [{"keyword": "model " + str(index), "status": "low_signal", "rank": None, "observed_days": 92,
             "analysis_observations": [{"positive_points": 1}], "reason": "Tín hiệu thưa"} for index in range(32)]
    rows += [{"keyword": "pending " + str(index), "status": "unavailable", "rank": None} for index in range(6)]
    screening = {"rows": rows, "selection_months": [10, 11, 12], "analysis_year": 2025}
    usage = [{"provider": "serpapi", "engine": "google_trends", "purpose": "trends_history", "status": "received"} for _ in range(8)]
    usage += [{"provider": "google_trends_free", "status": "HTTP 429"}]
    return config, screening, usage


def test_real_failure_shape_explains_sparse_queries_and_exhausted_subcap_without_mutating_input():
    config, screen, usage = fixture()
    before = deepcopy((config, screen, usage))
    result = screening_diagnostics(config, screen, usage)
    assert result["cause"] == "sparse_queries"
    assert (result["measured"], result["low_signal"], result["unavailable"], result["valid"]) == (32, 32, 6, 0)
    assert "32/38" in result["summary"] and "8/8" in result["summary"] and "429" in result["summary"]
    assert result["retry_kind"] == "free_only" and result["paid_remaining"] == 0
    assert (config, screen, usage) == before


def test_cached_low_signal_is_not_an_actionable_same_query_retry():
    config, screen, usage = fixture()
    screen["rows"] = screen["rows"][:32]
    result = screening_diagnostics(config, screen, usage)
    assert not result["can_retry"] and result["retry_kind"] == "none"
    assert "số 0 chuẩn hóa không chứng minh" in result["explanation"]


def test_unavailable_provider_is_not_misdiagnosed_as_a_zero_interest_query():
    config, screen, usage = fixture()
    screen["rows"] = screen["rows"][32:]
    result = screening_diagnostics(config, screen, usage)
    assert result["cause"] == "source_unavailable" and result["measured"] == 0
    assert "Chưa nhận đủ dữ liệu nguồn" in result["explanation"]


def test_resolved_free_rate_limit_does_not_remain_a_current_error():
    config, screen, usage = fixture()
    usage.append({"provider": "google_trends_free", "status": "received"})
    assert not screening_diagnostics(config, screen, usage)["free_rate_limited"]


def test_diagnostic_artifact_is_available_without_a_fabricated_product_report(tmp_path):
    config, screen, usage = fixture()
    export_screening_diagnostic(tmp_path, config, screen, usage)
    text = (tmp_path / "screening-diagnostic.html").read_text(encoding="utf-8")
    assert "32/38" in text and "8/8" in text
    assert (tmp_path / "screening-diagnostic.json").is_file()
    assert not (tmp_path / "report.html").exists()
