import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from retail.http import HttpError, HttpSession


@pytest.fixture
def solver_service(monkeypatch):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path.startswith("/plain"):
                status, body = 200, '{"plain": true}'
            elif self.path.startswith("/denied"):
                status, body = 403, "Access denied"
            elif self.path.startswith(
                "/protected"
            ) and "cf_clearance=test" in self.headers.get("Cookie", ""):
                status, body = 200, '{"resolved": true}'
            else:
                status, body = 403, "challenge"
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if body == "challenge":
                self.send_header("cf-mitigated", "challenge")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(payload)
            self.send_response(200)
            self.end_headers()
            if "/error" in payload["url"]:
                result = {"status": "error", "message": "timeout"}
            else:
                result = {
                    "status": "ok",
                    "solution": {
                        "status": 200,
                        "response": "<html>resolved</html>",
                        "userAgent": "solver-browser",
                        "cookies": [
                            {
                                "name": "cf_clearance",
                                "value": "test",
                                "domain": "127.0.0.1",
                                "path": "/",
                            }
                        ],
                    },
                }
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("FLARESOLVERR_URL", endpoint)
    session = HttpSession()
    try:
        yield session, endpoint, calls
    finally:
        session.close()
        server.shutdown()
        thread.join()
        server.server_close()


def test_normal_http_does_not_use_solver(solver_service):
    session, endpoint, calls = solver_service
    assert session.get(endpoint + "/plain")[0] == 200
    assert session.get(endpoint + "/denied")[0] == 403
    assert calls == []


def test_clearance_replays_api_with_query(solver_service):
    session, endpoint, calls = solver_service
    status, content_type, body = session.get(
        endpoint + "/protected", params={"page": 2}
    )
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body) == {"resolved": True}
    assert calls[0]["url"].endswith("/protected?page=2")
    assert session._client.headers["User-Agent"] == "solver-browser"
    session.get(endpoint + "/protected")
    assert len(calls) == 1


def test_html_fallback(solver_service):
    session, endpoint, _ = solver_service
    assert session.get(endpoint + "/html") == (
        200,
        "text/html; charset=utf-8",
        "<html>resolved</html>",
    )


def test_solver_error_is_reported(solver_service):
    session, endpoint, _ = solver_service
    with pytest.raises(HttpError, match="timeout"):
        session.get(endpoint + "/error")


def test_disabled_solver(solver_service, monkeypatch):
    session, endpoint, calls = solver_service
    monkeypatch.delenv("FLARESOLVERR_URL")
    assert session.get(endpoint + "/protected")[0] == 403
    assert calls == []
