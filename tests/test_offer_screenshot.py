"""Capturas de oferta: sin navegador real; Playwright se mockea."""

from __future__ import annotations

from pathlib import Path

import retail.offer_screenshot as shots


def test_disabled_returns_fallback_image(monkeypatch, tmp_path):
    monkeypatch.delenv("OFFER_SCREENSHOTS", raising=False)
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    assert shots.resolve_alert_image(
        {"url": "https://tienda.cl/p/1", "image_url": "https://cdn.example/a.jpg"},
    ) == "https://cdn.example/a.jpg"


def test_page_url_prefers_store_then_ficha(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.test")
    assert shots.page_url_for_offer({"url": "https://tienda.cl/sku/9"}) == "https://tienda.cl/sku/9"
    assert shots.page_url_for_offer(
        {"store": "lider", "product_id": "abc"},
    ) == "https://precios.test/producto?store=lider&id=abc"


def test_missing_playwright_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)

    import builtins
    import sys

    sys.modules.pop("playwright", None)
    sys.modules.pop("playwright.sync_api", None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert shots.resolve_alert_image(
        {"url": "https://tienda.cl/p/1", "image_url": "https://cdn.example/a.jpg"},
    ) == "https://cdn.example/a.jpg"


def _install_fake_playwright(monkeypatch, sync_playwright_factory):
    import sys
    import types

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = sync_playwright_factory
    pkg = types.ModuleType("playwright")
    pkg.__path__ = []
    pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def test_capture_writes_png_with_mocked_playwright(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setenv("OFFER_SCREENSHOT_TIMEOUT_MS", "5000")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)

    class FakePage:
        def goto(self, url, wait_until=None, timeout=None):
            self.url = url

        def wait_for_timeout(self, ms):
            pass

        def screenshot(self, path, full_page=False, type="png"):
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

    class FakeBrowser:
        def new_page(self, viewport=None):
            return FakePage()

        def close(self):
            pass

    class FakeChromium:
        def launch(self, headless=True):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    _install_fake_playwright(monkeypatch, lambda: FakePlaywright())

    path = shots.capture_offer_screenshot(
        {"store": "lider", "product_id": "p1", "url": "https://tienda.cl/p/1"},
    )
    assert path
    assert Path(path).is_file()
    assert Path(path).read_bytes().startswith(b"\x89PNG")


def test_capture_failure_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)

    class Boom:
        def __enter__(self):
            raise RuntimeError("browser down")

        def __exit__(self, *args):
            return False

    _install_fake_playwright(monkeypatch, lambda: Boom())

    assert shots.resolve_alert_image(
        {"url": "https://tienda.cl/p/1", "image_url": "https://cdn.example/a.jpg"},
    ) == "https://cdn.example/a.jpg"


def test_cleanup_removes_old_files(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOT_RETENTION_DAYS", "7")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    old = tmp_path / "old.png"
    new = tmp_path / "new.png"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    import os
    import time

    old_mtime = time.time() - 10 * 86_400
    os.utime(old, (old_mtime, old_mtime))
    assert shots.cleanup_old_screenshots() == 1
    assert not old.exists()
    assert new.exists()


def test_apply_offer_screenshot_updates_payload(monkeypatch):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(
        shots,
        "capture_offer_screenshot",
        lambda payload: "/tmp/shot.png",
    )
    monkeypatch.setattr(shots, "is_local_image", lambda value: str(value) == "/tmp/shot.png")
    payload = {"url": "https://tienda.cl/p/1", "image_url": "https://cdn.example/a.jpg"}
    shots.apply_offer_screenshot(payload)
    assert payload["image_url"] == "/tmp/shot.png"


def test_telegram_sends_local_photo_via_multipart(monkeypatch, tmp_path):
    from retail.batch import alerts

    photo = tmp_path / "offer.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    calls = []

    def fake_photo_file(token, *, chat_id, path, caption):
        calls.append(("file", chat_id, str(path), caption))
        return {"ok": True, "result": {}}

    monkeypatch.setattr(alerts, "_telegram_api_photo_file", fake_photo_file)
    monkeypatch.setattr(
        alerts,
        "_telegram_api",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no URL sendPhoto")),
    )
    assert alerts._send_telegram("token", "99", "Oferta", image_url=str(photo)) is True
    assert calls[0][0] == "file"
    assert calls[0][2] == str(photo)


def test_email_embeds_local_screenshot(monkeypatch, tmp_path):
    from retail.batch import alerts

    photo = tmp_path / "offer.png"
    photo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASSWORD", "p")
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(alerts, "load_channels", lambda: {})
    html = alerts.product_email_html(
        {"name": "TV", "store": "lider", "image_url": str(photo), "price": 1000},
        eyebrow="Prueba",
    )
    assert "cid:offer-screenshot" in html
    assert alerts.send_email("a@b.cl", "asunto", "cuerpo", html=html, image_url=str(photo))
    assert sent
    raw = sent[0].as_string()
    assert "offer-screenshot" in raw
    assert "image/png" in raw
