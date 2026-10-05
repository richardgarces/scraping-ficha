import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from retail.http import HttpError, HttpSession
from retail.flaresolverr import is_challenge, solve
from retail.offer_screenshot import _capture_with_solver


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
            if result["status"] == "ok":
                if "/botcheck" in payload["url"]:
                    result["solution"]["response"] = (
                        "<html><title>Robot or human?</title><main id='px-captcha'>"
                        "Activate and hold to confirm that you're human. PRESS & HOLD</main></html>"
                    )
                if "/passive-jsd" in payload["url"]:
                    result["solution"]["response"] = (
                        "<html><title>Café Colombia | Falabella</title><h1>Café Colombia</h1>"
                        "<script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"
                    )
                if payload.get("returnScreenshot"):
                    from PIL import Image

                    buffer = io.BytesIO()
                    Image.new("RGB", (640, 480), "white").save(buffer, format="PNG")
                    result["solution"]["screenshot"] = base64.b64encode(
                        buffer.getvalue()
                    ).decode()
                    if "/corrupt-image" in payload["url"]:
                        result["solution"]["screenshot"] = base64.b64encode(
                            b"not a PNG"
                        ).decode()
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


def test_solver_ok_with_robot_page_is_rejected(solver_service):
    _, endpoint, _ = solver_service
    with pytest.raises(RuntimeError, match="antibot sin resolver"):
        solve(endpoint + "/botcheck", endpoint)


def test_solver_screenshot_validated_and_saved(solver_service, tmp_path):
    _, endpoint, calls = solver_service
    destination = tmp_path / "offer.png"
    assert _capture_with_solver(endpoint + "/html", destination) is True
    assert destination.read_bytes().startswith(b"\x89PNG")
    assert calls[-1]["returnScreenshot"] is True


@pytest.mark.parametrize("path", ["/botcheck", "/corrupt-image", "/error"])
def test_bad_solver_capture_discarded(solver_service, tmp_path, path):
    _, endpoint, _ = solver_service
    destination = tmp_path / "offer.png"
    destination.write_bytes(b"old blocked capture")
    assert _capture_with_solver(endpoint + path, destination) is False
    assert not destination.exists()


def test_falabella_capture_with_passive_js_detection(solver_service, tmp_path):
    _, endpoint, _ = solver_service
    destination = tmp_path / "falabella.png"
    assert _capture_with_solver(endpoint + "/passive-jsd", destination) is True
    assert destination.is_file()
    html = solve(endpoint + "/passive-jsd", endpoint)["response"]
    assert is_challenge(200, {"Server": "cloudflare"}, html) is False
