"""Capturas de oferta: sin navegador real; Playwright se mockea."""

from __future__ import annotations

from pathlib import Path

import retail.offer_screenshot as shots


class _SettingsRepo:
    def __init__(self, document=None):
        self.document = document
        self.saved_key = None

    def get_app_setting(self, key):
        assert key == shots.SETTING_KEY
        return self.document

    def save_app_setting(self, key, value):
        self.saved_key = key
        self.document = dict(value)
        return self.document

    def close(self):
        pass


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


def _install_fake_async_playwright(monkeypatch, async_playwright_factory):
    import sys
    import types

    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = async_playwright_factory
    sync_api = types.ModuleType("playwright.sync_api")
    pkg = types.ModuleType("playwright")
    pkg.__path__ = []
    pkg.async_api = async_api
    pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.async_api", async_api)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _async_playwright_stack(*, page_factory=None, launch_side_effect=None, launches=None):
    """Fake async Playwright: un browser, pages async, cuenta launches."""

    class FakePage:
        def __init__(self):
            self.url = ""

        async def goto(self, url, wait_until=None, timeout=None):
            self.url = url

        async def wait_for_timeout(self, ms):
            pass

        async def title(self):
            return "Producto | Tienda"

        async def content(self):
            return "<html><body><h1>Producto</h1></body></html>"

        def locator(self, selector):
            class Locator:
                async def inner_text(self, timeout=None):
                    return "Producto en oferta"

            return Locator()

        async def screenshot(self, path, full_page=False, type="png"):
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

        async def close(self):
            pass

    class FakeBrowser:
        async def new_page(self, viewport=None):
            if page_factory is not None:
                return page_factory()
            return FakePage()

        async def close(self):
            pass

    class FakeChromium:
        async def launch(self, headless=True):
            if launches is not None:
                launches.append(1)
            if launch_side_effect is not None:
                raise launch_side_effect
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    return FakePlaywright


def test_capture_writes_png_with_mocked_playwright(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setenv("OFFER_SCREENSHOT_TIMEOUT_MS", "5000")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    launches: list[int] = []
    FakePlaywright = _async_playwright_stack(launches=launches)
    _install_fake_async_playwright(monkeypatch, lambda: FakePlaywright())

    path = shots.capture_offer_screenshot(
        {"store": "lider", "product_id": "p1", "url": "https://tienda.cl/p/1"},
    )
    assert path
    assert Path(path).is_file()
    assert Path(path).read_bytes().startswith(b"\x89PNG")
    assert len(launches) == 1


def test_batch_captures_many_urls_with_single_launch(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setenv("RETAIL_CHROMIUM_CONCURRENCY", "3")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    launches: list[int] = []
    FakePlaywright = _async_playwright_stack(launches=launches)
    _install_fake_async_playwright(monkeypatch, lambda: FakePlaywright())

    payloads = [
        {"store": "lider", "product_id": f"p{i}", "url": f"https://tienda.cl/p/{i}"}
        for i in range(5)
    ]
    keys = [f"k{i}" for i in range(5)]
    paths = shots.capture_offer_screenshots_batch(payloads, keys=keys)
    assert len(launches) == 1
    assert set(paths) == set(keys)
    assert all(paths[key] and Path(paths[key]).is_file() for key in keys)


def test_apply_offer_screenshots_updates_payloads(monkeypatch):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(
        shots,
        "capture_offer_screenshots_batch",
        lambda payloads, keys=None: {keys[0]: "/tmp/a.png", keys[1]: "/tmp/b.png"},
    )
    media = {
        "a": {"url": "https://tienda.cl/a", "image_url": "https://cdn.example/a.jpg"},
        "b": {"url": "https://tienda.cl/b", "image_url": "https://cdn.example/b.jpg"},
    }
    shots.apply_offer_screenshots(media)
    assert media["a"]["image_url"] == "/tmp/a.png"
    assert media["b"]["image_url"] == "/tmp/b.png"


def test_capture_failure_falls_back(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    FakePlaywright = _async_playwright_stack(launch_side_effect=RuntimeError("browser down"))
    _install_fake_async_playwright(monkeypatch, lambda: FakePlaywright())

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


def test_missing_setting_follows_env(monkeypatch):
    monkeypatch.delenv("OFFER_SCREENSHOTS", raising=False)
    shots.clear_screenshots_setting_cache()
    assert shots.screenshots_enabled() is False
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    shots.clear_screenshots_setting_cache()
    assert shots.screenshots_enabled() is True
    assert shots.load_stored_screenshots_enabled(_SettingsRepo(None)) is None
    assert shots.load_stored_screenshots_enabled(_SettingsRepo({"updated_at": "x"})) is None


def test_database_off_overrides_env_on(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    shots.clear_screenshots_setting_cache()
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    repo = _SettingsRepo({"enabled": False})
    assert shots.stored_screenshots_enabled(repo) is False
    assert shots.screenshots_enabled() is False
    assert shots.resolve_alert_image(
        {"url": "https://tienda.cl/p/1", "image_url": "https://cdn.example/a.jpg"},
    ) == "https://cdn.example/a.jpg"


def test_database_on_overrides_env_off(monkeypatch):
    monkeypatch.delenv("OFFER_SCREENSHOTS", raising=False)
    shots.clear_screenshots_setting_cache()
    assert shots.stored_screenshots_enabled(_SettingsRepo({"enabled": True})) is True
    assert shots.screenshots_enabled() is True
    assert shots.offer_screenshot_status() == {"enabled": True, "source": "database"}


def test_string_false_in_database_stays_off():
    shots.clear_screenshots_setting_cache()
    assert shots.load_stored_screenshots_enabled(_SettingsRepo({"enabled": "false"})) is False
    assert shots.load_stored_screenshots_enabled(_SettingsRepo({"enabled": "off"})) is False
    assert shots.load_stored_screenshots_enabled(_SettingsRepo({"enabled": "yes"})) is True


def test_save_offer_screenshots_persists_boolean():
    shots.clear_screenshots_setting_cache()
    repo = _SettingsRepo()
    saved = shots.save_offer_screenshots_enabled(False, repo)
    assert saved == {"enabled": False, "source": "database"}
    assert repo.saved_key == "offer_screenshots"
    assert repo.document["enabled"] is False
    assert shots.screenshots_enabled() is False
    turned_on = shots.save_offer_screenshots_enabled(True, repo)
    assert turned_on["enabled"] is True
    assert shots.load_stored_screenshots_enabled(repo) is True
    assert shots.screenshots_enabled() is True


def test_unreadable_database_keeps_env(monkeypatch):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    shots.clear_screenshots_setting_cache()

    class Down:
        def get_app_setting(self, key):
            raise RuntimeError("mongo down")

        def close(self):
            pass

    assert shots.stored_screenshots_enabled(Down()) is None
    assert shots.screenshots_enabled() is True


def test_offer_screenshots_api_and_page(monkeypatch, anonymous_repo):
    from fastapi.testclient import TestClient

    from retail.web.app import app

    client = TestClient(app)
    denied = client.put("/api/settings/offer-screenshots", json={"enabled": False})
    assert denied.status_code == 401

    repo = _SettingsRepo()
    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin"},
    )
    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: repo)
    invalid = client.put("/api/settings/offer-screenshots", json={"enabled": "no"})
    assert invalid.status_code == 400
    saved = client.put("/api/settings/offer-screenshots", json={"enabled": False})
    assert saved.status_code == 200
    assert saved.json() == {"enabled": False, "source": "database"}
    assert repo.document["enabled"] is False
    html = (Path("retail/web/static/ofertas.html")).read_text()
    js = (Path("retail/web/static/settings.js")).read_text()
    assert 'id="capturas-oferta"' in html
    assert "Adjuntar captura de la página en Telegram y correo" in html
    assert "settings.js?v=14" in html
    assert "/api/settings/offer-screenshots" in js
    assert "offer_screenshots" in js


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
