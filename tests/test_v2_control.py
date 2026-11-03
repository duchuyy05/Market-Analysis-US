import threading

from market_research.common import read_json
from market_research.config import validate_config
from market_research.pipeline import execute
from test_v2_workflow import fixture_transport


def test_stop_retains_received_response_and_resume_reuses_it(tmp_path):
    calls = []
    cancel = threading.Event()
    base = fixture_transport(calls)

    def request(provider, params):
        response = base(provider, params)
        if params.get("engine") == "amazon":
            cancel.set()
        return response

    config = validate_config({"brief": "Desk organizers", "niches": [{"name": "Desk", "seeds": ["desk organizer"]}],
                              "discovery": {"enabled": False}, "trends": {"provider": "serpapi"}, "llm": {"enabled": False}, "sources": {"web": False}})
    stopped = execute(config, root=tmp_path, run_id="stop-resume", cancel_event=cancel, transport=request, event=lambda _: None)
    assert stopped.manifest["status"] == "cancelled"
    assert stopped.manifest["errors"] == []
    assert stopped.manifest["stages"]["search"]["status"] == "cancelled"
    assert not (stopped.path / ".running.lock").exists()
    assert any(read_json(path).get("response", {}).get("organic_results") for path in (stopped.path / "raw/serpapi").glob("*.json"))
    resumed = execute(root=tmp_path, run_id=stopped.id, transport=base, event=lambda _: None)
    assert resumed.manifest["status"] in {"partial", "complete"}
    assert (resumed.output / "report.html").exists()
    assert sum(params.get("engine") == "amazon" for _, params in calls) == 1


def test_stop_before_first_stage_uses_no_provider_requests(tmp_path):
    cancel = threading.Event()
    cancel.set()
    calls = []
    run = execute(validate_config({"brief": "Stop before start"}), root=tmp_path, run_id="stop-first", cancel_event=cancel,
                  transport=fixture_transport(calls), event=lambda _: None)
    assert run.manifest["status"] == "cancelled"
    assert run.manifest["usage"] == []
    assert "input" in run.manifest
    assert calls == []


def test_server_shutdown_signals_active_work_to_stop(tmp_path, monkeypatch):
    from market_research.ui import server as ui_server
    manager = ui_server.Manager(tmp_path)
    cancel = threading.Event()
    manager.cancellations["active"] = cancel

    class Server:
        server_port = 8765
        closed = False

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            self.closed = True

    server = Server()
    monkeypatch.setattr(ui_server, "Manager", lambda: manager)
    monkeypatch.setattr(ui_server, "ThreadingHTTPServer", lambda *args: server)
    ui_server.serve()
    assert cancel.is_set()
    assert server.closed
