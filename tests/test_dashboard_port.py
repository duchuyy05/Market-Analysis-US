"""A dashboard listener cannot coexist with another process on its port."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer as LegacyHTTPServer
import socket
import threading
from urllib.request import urlopen

import pytest

from market_research.ui.server import ThreadingHTTPServer


class HealthyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"first-server-still-healthy"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.mark.parametrize("second_type", [ThreadingHTTPServer, LegacyHTTPServer])
def test_second_dashboard_cannot_bind_and_first_keeps_serving(second_type):
    first = ThreadingHTTPServer(("127.0.0.1", 0), HealthyHandler)
    worker = threading.Thread(target=first.serve_forever, daemon=True)
    worker.start()
    try:
        with pytest.raises(OSError):
            second_type(first.server_address, HealthyHandler)
        with urlopen(f"http://127.0.0.1:{first.server_port}", timeout=5) as response:
            assert response.status == 200
            assert response.read() == b"first-server-still-healthy"
    finally:
        first.shutdown()
        first.server_close()
        worker.join(timeout=5)
    assert not worker.is_alive()


def test_dashboard_does_not_enable_reuse_and_sets_windows_exclusivity():
    server = ThreadingHTTPServer(("127.0.0.1", 0), HealthyHandler)
    try:
        assert server.allow_reuse_address is False
        assert server.allow_reuse_port is False
        assert server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            assert server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 1
    finally:
        server.server_close()
