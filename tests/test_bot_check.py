"""Detector de la intersticial antibot. HTML estático: no se consulta ninguna tienda."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import retail.offer_screenshot as shots

CHALLENGE_HTML = """
<html><head><title>Just a moment...</title></head>
<body>
  <div id="cf-browser-verification" class="cf-im-under-attack"></div>
  <h1>Verify you are human</h1>
  <div id="cf-stage"><div class="cf-turnstile"></div></div>
  <script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>
  <p>Performance &amp; security by Cloudflare</p>
  <p>Ray ID: 8a1b</p>
</body></html>
"""

CHECKING_HTML = """
<html><head><title>Checking your browser before accessing tienda.cl</title></head>
<body><p>Checking your browser before accessing tienda.cl.</p></body></html>
"""

TURNSTILE_BLOCK_HTML = """
<html><head><title>tienda.cl</title></head>
<body>
  <h1>Are you human?</h1>
  <div class="cf-turnstile" data-sitekey="0x4AAAA"></div>
  <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
</body></html>
"""

SPANISH_HTML = """
<html><head><title>Un momento…</title></head>
<body><p>Comprobando si la conexión del sitio es segura</p></body></html>
"""

WALMART_HOLD_HTML = """
<html><head><title>Robot or human?</title></head>
<body>
  <main id="px-captcha">
    <p>Activate and hold the button to confirm that you're human. Thank You!</p>
    <button>PRESS &amp; HOLD</button>
  </main>
  <script>window._pxAppId = "PXu6b0qd2S";</script>
  <script src="https://captcha.px-cdn.net/PXu6b0qd2S/captcha.js"></script>
</body></html>
"""

PRODUCT_HTML = """
<html><head><title>Televisor 55 | Lider</title></head>
<body>
  <h1>Televisor 55</h1>
  <p>Just a moment ago I bought this TV at the store.</p>
  <script src="https://static.cloudflareinsights.com/beacon.min.js"></script>
  <script src="/cdn-cgi/scripts/5c5dd728/cloudflare-static/email-decode.min.js"></script>
  <div class="cf-turnstile" data-sitekey="checkout-widget"></div>
</body></html>
"""


def test_challenge_titles_and_markers():
    assert shots.is_bot_check_page(CHALLENGE_HTML) is True
    assert shots.is_bot_check_page(CHECKING_HTML) is True
    assert shots.is_bot_check_page(TURNSTILE_BLOCK_HTML) is True
    assert shots.is_bot_check_page(SPANISH_HTML) is True
    assert shots.is_bot_check_page("<html><title>Atención</title></html>", "Are you a human?") is True
    assert shots.is_bot_check_page(
        '<html><div id="challenge-form"></div><p>producto</p></html>',
        "Ficha",
    ) is True
    assert shots.is_bot_check_page(
        "<html><script>window._cf_chl_opt = {cType:'managed'};</script></html>",
        "Ficha",
    ) is True


def test_walmart_press_and_hold_requires_context():
    assert shots.is_bot_check_page(WALMART_HOLD_HTML) is True
    assert shots.bot_check_provider(WALMART_HOLD_HTML) == "perimeterx"
    assert shots.is_bot_check_page(
        "<html><title>Lider</title><body><main></main></body></html>",
        "Robot or human?",
        "Activate and hold the button to confirm that you're human. PRESS & HOLD",
    ) is True

    # Palabras aisladas pueden aparecer en instrucciones o nombres de producto.
    assert shots.is_bot_check_page(
        "<html><title>Robot or Human: The Psychology Book</title><p>Libro importado</p></html>"
    ) is False
    assert shots.is_bot_check_page(
        "<html><title>Taladro | Lider</title><p>Press and hold for two seconds to start.</p></html>"
    ) is False
    assert shots.is_bot_check_page(
        '<html><title>Pago</title><div id="px-captcha"></div><p>Completa el formulario.</p></html>'
    ) is False


def test_product_page_is_not_a_challenge():
    assert shots.is_bot_check_page(PRODUCT_HTML, "Televisor 55 | Lider") is False
    assert shots.is_bot_check_page("", "") is False
    assert shots.is_bot_check_page("<html><title>Un momento de paz | Vela</title><p>aroma</p></html>") is False


def test_mark_and_list_store_bot_check():
    class Collection:
        def __init__(self, docs):
            self.docs = docs

        def find(self, query):
            return [
                doc
                for doc in self.docs.values()
                if all(doc.get(key) == value for key, value in query.items())
            ]

    class Repo:
        def __init__(self):
            self.docs = {}
            self.app_settings = Collection(self.docs)

        def save_app_setting(self, key, value):
            self.docs[key] = {"_id": key, **dict(value), "updated_at": datetime(2026, 10, 3, tzinfo=timezone.utc)}

    repo = Repo()
    seen = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
    saved = shots.mark_store_bot_check(repo, " Lider ", seen_at=seen, provider="PerimeterX")
    assert saved["store"] == "lider"
    assert saved["bot_check"] is True
    assert repo.docs["store:lider"]["bot_check_last_seen_at"] == seen
    assert repo.docs["store:lider"]["bot_check_provider"] == "perimeterx"
    assert shots.list_store_bot_checks(repo) == {"lider": seen.isoformat()}
    assert shots.mark_store_bot_check(repo, "  ") is None

    rows = shots.annotate_store_bot_checks(
        [{"store": "Lider", "drops": 1}, {"store": "paris", "drops": 2}],
        shots.list_store_bot_checks(repo),
    )
    assert rows[0]["bot_check"] is True
    assert rows[0]["bot_check_last_seen_at"] == seen.isoformat()
    assert "bot_check" not in rows[1]


def test_api_rows_keep_the_flag_readable():
    rows = shots.bot_check_api_rows({"falabella": "2026-10-03T18:00:00+00:00"})
    assert rows[0]["store"] == "falabella"
    assert rows[0]["bot_check"] is True
    assert rows[0]["last_seen_at"] == "2026-10-03T18:00:00+00:00"
    assert rows[0]["store_title"]


def test_tiendas_page_shows_the_mark():
    html = Path("retail/web/static/tiendas.html").read_text()
    script = Path("retail/web/static/tiendas.js").read_text()
    assert 'id="bot-checks"' in html
    assert "tiendas.js?v=7" in html
    assert "comprobación antibot" in script
    assert "renderBotChecks" in script


def _install_fake_playwright(monkeypatch, factory):
    import sys
    import types

    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = factory
    pkg = types.ModuleType("playwright")
    pkg.__path__ = []
    pkg.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def _browser(page):
    class Browser:
        def new_page(self, viewport=None):
            return page

        def close(self):
            pass

    class Chromium:
        def launch(self, headless=True):
            return Browser()

    class Playwright:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return Playwright()


def test_challenge_screenshot_is_dropped_and_store_is_marked(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    marked = []
    monkeypatch.setattr(
        shots,
        "note_store_bot_check",
        lambda payload, repo=None, provider=None: marked.append((shots._store_id(payload), provider)),
    )
    dest = tmp_path / "challenge.png"
    monkeypatch.setattr(shots, "_destination_path", lambda payload, url: dest)

    class Page:
        def goto(self, url, wait_until=None, timeout=None):
            dest.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

        def wait_for_timeout(self, ms):
            pass

        def title(self):
            return "Robot or human?"

        def content(self):
            # Simula HTML que solo conserva los marcadores del proveedor; la
            # copia visible se obtiene además desde textContent tras render.
            return '<html><body><main id="px-captcha"></main></body></html>'

        def locator(self, selector):
            assert selector == "body"

            class Locator:
                def inner_text(self, timeout=None):
                    return (
                        "Activate and hold the button to confirm that you're human. "
                        "Thank You! PRESS & HOLD"
                    )

            return Locator()

        def screenshot(self, **kwargs):
            raise AssertionError("no se debe guardar la captura de la comprobación")

    _install_fake_playwright(monkeypatch, lambda: _browser(Page()))
    assert shots.resolve_alert_image(
        {
            "store": "Lider",
            "url": "https://tienda.cl/p/1",
            "image_url": "https://cdn.example/tv.jpg",
        }
    ) == "https://cdn.example/tv.jpg"
    assert not dest.exists()
    assert list(tmp_path.glob("*.png")) == []
    assert marked == [("lider", "perimeterx")]


def test_product_page_still_saves_png(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFER_SCREENSHOTS", "1")
    monkeypatch.setattr(shots, "storage_dir", lambda: tmp_path)
    monkeypatch.setattr(shots, "note_store_bot_check", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no marcar")))

    class Page:
        def goto(self, url, wait_until=None, timeout=None):
            pass

        def wait_for_timeout(self, ms):
            pass

        def title(self):
            return "Televisor 55 | Lider"

        def content(self):
            return PRODUCT_HTML

        def screenshot(self, path, full_page=False, type="png"):
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

    _install_fake_playwright(monkeypatch, lambda: _browser(Page()))
    path = shots.capture_offer_screenshot(
        {"store": "lider", "product_id": "p1", "url": "https://tienda.cl/p/1"},
    )
    assert path
    assert Path(path).is_file()


def test_falabella_passive_cloudflare_script_is_not_a_challenge():
    html = """<html><title>Café Colombia | Falabella</title>
    <body><h1>Café Colombia</h1><p>$8.590</p>
    <script>var a=document.createElement('script');
    a.src='/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script>
    </body></html>"""
    assert shots.is_bot_check_page(html) is False
    assert shots.is_bot_check_page(html, "Just a moment...") is True


def test_ripley_custom_block_page_and_product_copy():
    blocked = """<html><title>Error en Ripley.com | Blocked</title>
    <h1>&iexcl;Alto, no puedes acceder!</h1><h2>vuelve a intentarlo</h2>
    <p>&iquest;Por qu&eacute; me han bloqueado?</p></html>"""
    assert shots.is_bot_check_page(blocked)
    assert shots.is_bot_check_page("<main></main>", "Ripley", "¡Alto, no puedes acceder! ¿Por qué me han bloqueado?")
    assert not shots.is_bot_check_page("<title>Libro Alto, no puedes acceder | Ripley</title><p>Libro importado</p>")
    assert not shots.is_bot_check_page("<title>Mochila | Ripley</title><p>Si no puedes acceder a tu cuenta, vuelve a intentarlo.</p>")
