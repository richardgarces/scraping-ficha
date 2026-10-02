"""Pruebas de aviso: solo admin, un envío, sin secretos en la respuesta."""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from retail.web.app import app

STATIC = Path("retail/web/static")


def test_telegram_notification_links_to_product_page_instead_of_store(monkeypatch):
    from retail.batch.alerts import _notification_text

    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    text = _notification_text(
        {
            "name": "Televisor",
            "store": "lider",
            "product_id": "sku 1",
            "price": 299990,
            "url": "https://www.lider.cl/ip/sku-1",
        }
    )
    assert "https://precios.meincart.cl/producto?store=lider&id=sku%201" in text
    assert "lider.cl/ip" not in text


def test_telegram_notification_never_falls_back_to_store_link():
    from retail.batch.alerts import _notification_text

    text = _notification_text(
        {"name": "Televisor", "price": 299990, "url": "https://tienda.example/producto"}
    )
    assert "tienda.example" not in text


def test_notification_uses_persistent_short_product_link(monkeypatch):
    from retail.batch.alerts import _notification_text
    from retail.short_links import attach_short_url

    class Repo:
        def product_short_code(self, store, product_id):
            assert (store, product_id) == ("thelab", "9440931348693")
            return "237864234"

    monkeypatch.setenv("SHORT_LINK_BASE_URL", "https://mein.link")
    payload = {
        "name": "Producto",
        "store": "thelab",
        "product_id": "9440931348693",
        "price": 19990,
    }
    attach_short_url(payload, Repo())
    text = _notification_text(payload)
    assert "https://mein.link/o/237864234" in text
    assert "/producto?" not in text


def test_short_link_redirects_only_to_internal_product_page(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")

    class Repo:
        def resolve_product_short_link(self, code):
            assert code == "237864234"
            return {"store": "thelab", "product_id": "9440931348693"}

        def close(self):
            pass

    monkeypatch.setattr("retail.web.app.connect_repo", lambda: Repo())
    response = TestClient(app).get("/o/237864234", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://precios.meincart.cl/producto?store=thelab&id=9440931348693"
    )

    missing = TestClient(app).get("/o/javascript:alert(1)", follow_redirects=False)
    assert missing.status_code == 404


def test_notice_panel_lives_on_configurar():
    html = (STATIC / "ofertas.html").read_text()
    js = (STATIC / "settings.js").read_text()
    assert "Pruebas de aviso" in html
    assert "Enviar prueba por Telegram" in html
    assert "Enviar correo de prueba" in html
    assert "Enviar prueba push al celular" in html
    assert 'value="push"' in html
    assert "Celular (push)" in html
    assert 'id="test_email_to"' in html
    assert 'value="richardgarces@gmail.com"' in html
    assert "TEST_EMAIL_DEFAULT" in js
    assert "richardgarces@gmail.com" in js
    assert "/api/admin/test-telegram" in js
    assert "/api/admin/test-email" in js
    assert "/api/admin/test-push" in js


def test_notice_endpoints_require_admin(anonymous_repo):
    client = TestClient(app)
    for path in ("/api/admin/test-telegram", "/api/admin/test-email", "/api/admin/test-push"):
        denied = client.post(path)
        assert denied.status_code == 401


def test_email_filters_have_compact_responsive_controls():
    html = (STATIC / "siguiendo.html").read_text()
    js = (STATIC / "siguiendo.js").read_text()
    styles = (STATIC / "styles.css").read_text()
    assert 'class="email-filters"' in html
    assert 'id="email-categories-all"' in html
    assert 'id="email-categories-none"' in html
    assert 'class="percent-input"' in html
    assert "refreshEmailCategorySummary" in js
    assert ".email-filter-grid" in styles
    assert "grid-template-columns: repeat(3" in styles
    assert 'class="store-preference-overview"' in html
    assert 'id="favorite-store-count"' in html
    assert 'data-store-state=' in js
    assert 'value="normal"' in js
    assert 'value="favorite"' in js
    assert 'value="excluded"' in js
    assert '.store-state-control' in styles
    assert 'src="/static/siguiendo.js?v=' in html
    assert 'href="/static/styles.css?v=' in html
    assert "Celular (push)" in html


def test_catalog_editor_limits_rows_without_dropping_hidden_products():
    html = (STATIC / "ofertas.html").read_text()
    js = (STATIC / "settings.js").read_text()
    assert "CATALOG_DISPLAY_LIMIT = 100" in js
    assert "catalogProducts.slice(0, CATALOG_DISPLAY_LIMIT)" in js
    assert "products.filter((_item, index) => !removedCatalogIndexes.has(index)).concat(added)" in js
    assert 'id="catalog-limit-note"' in html
    assert 'src="/static/settings.js?v=' in html


def test_telegram_test_reports_missing_token_without_secrets(monkeypatch):
    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1", "email": "admin@example.com"},
    )
    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: None)
    monkeypatch.setattr(
        "retail.batch.alerts.send_telegram_test",
        lambda document: {"ok": False, "error": "Falta el token del bot de Telegram."},
    )
    response = TestClient(app).post("/api/admin/test-telegram")
    assert response.status_code == 400
    body = response.text
    assert "token" in body.lower()
    assert "123:abc" not in body
    assert "admin@example.com" not in body


def test_email_test_uses_account_email_and_hides_it(monkeypatch):
    seen = {}

    def fake_send(to_addr):
        seen["to"] = to_addr
        return {"ok": True, "message": "Correo de prueba enviado a tu cuenta."}

    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1", "email": "admin@example.com"},
    )
    monkeypatch.setattr("retail.batch.alerts.send_email_test", fake_send)
    response = TestClient(app).post("/api/admin/test-email")
    assert response.status_code == 200
    assert seen["to"] == "admin@example.com"
    assert "admin@example.com" not in response.text
    assert "enviado" in response.json()["message"].lower()


def test_saved_notice_chat_prefers_channels_then_account(monkeypatch):
    from retail.batch import alerts

    monkeypatch.setattr(alerts, "load_channels", lambda: {"telegram_chat_id": "canales-1"})
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert alerts.saved_notice_chat({"telegram_chat_id": "cuenta-9"}) == "canales-1"
    monkeypatch.setattr(alerts, "load_channels", lambda: {})
    assert alerts.saved_notice_chat({"telegram_username": "@cuenta"}) == "@cuenta"
    assert alerts.saved_notice_chat({}) == ""


def test_telegram_test_sends_once(monkeypatch):
    from retail.batch import alerts

    calls = []
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secreto")
    monkeypatch.setattr(alerts, "load_channels", lambda: {"telegram_chat_id": "99"})
    monkeypatch.setattr(alerts, "_send_telegram_result", lambda token, chat, text: calls.append(chat) or (True, ""))
    result = alerts.send_telegram_test({"telegram_chat_id": "99", "email": "a@b.c"})
    assert result["ok"] is True
    assert calls == ["99"]
    assert "123:secreto" not in str(result)
    assert "99" not in str(result)


def test_email_test_accepts_typed_recipient_and_defaults_empty(monkeypatch):
    from retail.batch import alerts

    seen = {}
    monkeypatch.setattr(alerts, "_secret", lambda env_name, local_name: "smtp.example" if env_name == "SMTP_HOST" else "")
    monkeypatch.setattr(alerts, "send_email", lambda to, subject, body, **kwargs: seen.setdefault("direct", to) or True)
    result = alerts.send_email_test("")
    assert result["ok"] is True
    assert seen["direct"] == "richardgarces@gmail.com"
    assert "richardgarces@gmail.com" not in result["message"]

    def fake_send(to_addr):
        seen["to"] = to_addr
        return {"ok": True, "message": "Correo de prueba enviado a tu cuenta."}

    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1", "email": "admin@example.com"},
    )
    monkeypatch.setattr("retail.batch.alerts.send_email_test", fake_send)
    client = TestClient(app)
    other = client.post("/api/admin/test-email", json={"to": "otro@example.com"})
    assert other.status_code == 200
    assert seen["to"] == "otro@example.com"
    assert "otro@example.com" not in other.text

    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1", "email": ""},
    )
    empty = client.post("/api/admin/test-email")
    assert empty.status_code == 200
    assert seen["to"] == "richardgarces@gmail.com"


def test_email_test_missing_smtp(monkeypatch):
    from retail.batch import alerts

    monkeypatch.setattr(alerts, "_secret", lambda env_name, local_name: "")
    result = alerts.send_email_test("admin@example.com")
    assert result["ok"] is False
    assert "SMTP" in result["error"]
    assert "admin@example.com" not in result["error"]


def test_product_email_looks_like_the_product_page(monkeypatch):
    from retail.batch.alerts import product_email_html

    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    html = product_email_html(
        {
            "name": "TV <OLED>",
            "store": "falabella",
            "price": 799990,
            "previous_price": 999990,
            "saving": 200000,
            "message": "Bajó de precio frente a su historial.",
            "image_url": "https://example.com/tv.jpg",
            "url": "https://tienda.example/tv",
            "extra": {"product_id": "sku 1", "store_title": "Falabella"},
        }
    )
    assert "TV &lt;OLED&gt;" in html
    assert "Falabella" in html
    assert "$799.990" in html
    assert "$999.990" in html
    assert "−20%" in html
    assert "Ahorras $200.000" in html
    assert 'src="https://example.com/tv.jpg"' in html
    assert 'src="https://precios.meincart.cl/static/logos/falabella.png"' in html
    assert "max-width:460px" in html
    assert "max-width:320px" in html
    assert html.index("Precio para todo medio de pago") < html.index('src="https://example.com/tv.jpg"')
    assert "Ver ficha del producto" in html
    assert "/producto?store=falabella&amp;id=sku%201" in html
    assert "Abrir directamente en la tienda" in html
    assert "<OLED>" not in html


def test_product_email_rejects_unsafe_links():
    from retail.batch.alerts import product_email_html

    html = product_email_html(
        {"name": "Producto", "price": 1000, "url": "javascript:alert(1)", "image_url": "data:text/html,bad"}
    )
    assert "javascript:" not in html
    assert "data:text" not in html


def test_product_email_uses_generic_store_logo_when_store_has_no_asset(monkeypatch):
    from retail.batch.alerts import product_email_html

    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    html = product_email_html({"name": "Producto", "store": "tienda-inexistente", "price": 1000})
    assert "/static/logos/_store.svg" in html


def test_user_offer_email_uses_product_card(monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = {}

    def fake_send(to_addr, subject, body, **kwargs):
        sent.update(to=to_addr, subject=subject, body=body, html=kwargs.get("html"))
        return True

    monkeypatch.setattr(alerts, "send_email", fake_send)
    offer = Alert(
        catalog_id="tv",
        query="televisor",
        rule="common_discount",
        name="Televisor OLED",
        store="lider",
        price=799990,
        previous_price=999990,
        message="20% de descuento",
        url="https://tienda.example/tv",
        compare_code="tv-oled",
        extra={"product_id": "123", "percent": 20, "store_title": "Lider"},
        saving=200000,
        image_url="https://example.com/tv.jpg",
        price_normal=999990,
    )
    delivered = alerts.dispatch_user_alerts(
        [offer],
        [{"email": "ana@example.com", "notification_preferences": {"channels": ["email"], "kinds": ["common"]}}],
    )
    assert delivered == 1
    assert sent["to"] == "ana@example.com"
    assert "Televisor OLED" in sent["html"]
    assert "Ver ficha del producto" in sent["html"]


def test_user_email_respects_category_and_real_discount(monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda *args, **kwargs: sent.append(args) or True)
    deal = Alert(
        catalog_id="tv", query="televisor", rule="below_median", name="Televisor",
        store="lider", price=70000, previous_price=100000, message="30% bajo precio habitual",
        url=None, compare_code="tv-1",
        extra={"percent_vs_median": -30, "notification_category": "tecnologia", "product_id": "1"},
        category="tv",
    )
    user = {
        "id": "u1", "email": "ana@example.com",
        "notification_preferences": {
            "channels": ["email"], "kinds": ["real"],
            "email_categories": ["hogar"], "email_min_real_discount": 20,
        },
    }
    assert alerts.dispatch_user_alerts([deal], [user]) == 0
    assert sent == []
    user["notification_preferences"]["email_categories"] = ["tecnologia"]
    user["notification_preferences"]["email_min_real_discount"] = 40
    assert alerts.dispatch_user_alerts([deal], [user]) == 0
    user["notification_preferences"]["email_min_real_discount"] = 25
    assert alerts.dispatch_user_alerts([deal], [user]) == 1
    assert len(sent) == 1


def test_user_telegram_requires_40_percent_and_deduplicates_product(monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(alerts, "_secret", lambda *args: "token")
    monkeypatch.setattr(alerts, "_resolve_chat", lambda token, chat: chat)
    monkeypatch.setattr(alerts, "send_to_user", lambda user, text, **kwargs: sent.append(text) or True)

    class Repo:
        claimed = set()

        def claim_user_notification_send(self, user_id, channel, entity_key, price):
            key = (user_id, channel, entity_key)
            if key in self.claimed:
                return False
            self.claimed.add(key)
            return True

    def deal(code, percent, store="lider"):
        return Alert(
            catalog_id="tv", query="tv", rule="common_discount", name=f"TV {code}",
            store=store, price=100000, previous_price=200000, message="oferta",
            url=None, compare_code=code, extra={"percent": percent, "product_id": code},
        )

    user = {
        "id": "u1", "telegram_chat_id": "99",
        "notification_preferences": {"channels": ["telegram"], "kinds": ["common"]},
    }
    repo = Repo()
    assert alerts.dispatch_user_alerts([deal("bajo", 39), deal("bueno", 40)], [user], repo=repo) == 1
    assert len(sent) == 1
    assert alerts.dispatch_user_alerts([deal("bueno", 55, store="paris")], [user], repo=repo) == 0
    assert len(sent) == 1


def test_private_telegram_chat_id_wins_over_visible_username():
    from retail.batch.alerts import _chat_values

    assert _chat_values({"telegram_chat_id": "987654", "telegram_username": "@ana"}) == ["987654"]


def test_telegram_start_link_stores_private_chat_id(monkeypatch):
    from retail.web import auth_api

    raw = "token-seguro"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = {
        "_id": "u1",
        "telegram_link_token_hash": digest,
        "telegram_link_expires_at": datetime.now(timezone.utc) + timedelta(minutes=10),
        "telegram_username": "@anterior",
    }

    class Users:
        def find(self, query):
            return [row]

    class Store:
        users = Users()

        def update_user_fields(self, user_id, fields, *, unset=()):
            assert user_id == "u1"
            row.update(fields)
            for name in unset:
                row.pop(name, None)
            return row

    calls = []

    def fake_api(token, method, params):
        calls.append((method, params))
        if params.get("offset"):
            return {"ok": True, "result": []}
        return {
            "ok": True,
            "result": [{
                "update_id": 44,
                "message": {
                    "text": f"/start precios_{raw}",
                    "chat": {"id": 987654, "type": "private"},
                    "from": {"id": 987654, "username": "ana_real"},
                },
            }],
        }

    monkeypatch.setattr(auth_api, "_telegram_api", fake_api)
    assert auth_api._sync_telegram_links(Store(), "bot-token") == 1
    assert row["telegram_chat_id"] == "987654"
    assert row["telegram_username"] == "@ana_real"
    assert "telegram_link_token_hash" not in row
    assert calls[-1][1]["offset"] == "45"


def test_global_telegram_requires_40_percent(monkeypatch, tmp_path):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(alerts, "_telegram", lambda payload: sent.append(payload) or True)

    def deal(code, percent):
        return Alert(
            catalog_id="tv", query="tv", rule="common_discount", name=f"TV {code}",
            store="lider", price=100000, previous_price=200000, message="oferta",
            url=None, compare_code=code, extra={"percent": percent, "product_id": code},
        )

    alerts.dispatch_alerts(
        [deal("bajo", 39.9), deal("bueno", 40)], ["telegram"],
        log_path=tmp_path / "alerts.jsonl",
    )
    assert [item["compare_code"] for item in sent] == ["bueno"]


def test_global_telegram_does_not_repeat_product_during_cooldown(monkeypatch, tmp_path):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(alerts, "_telegram", lambda payload: sent.append(payload) or True)

    class Repo:
        claimed = set()

        def claim_user_notification_send(self, user_id, channel, entity_key, price):
            key = (user_id, channel, entity_key)
            if key in self.claimed:
                return False
            self.claimed.add(key)
            return True

    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV",
        store="lider", price=100000, previous_price=200000, message="50%",
        url=None, compare_code="tv-uno", extra={"percent": 50, "product_id": "1"},
    )
    repo = Repo()
    alerts.dispatch_alerts([deal], ["telegram"], log_path=tmp_path / "a", repo=repo)
    alerts.dispatch_alerts([deal], ["telegram"], log_path=tmp_path / "a", repo=repo)
    assert len(sent) == 1


def test_user_push_requires_admin_channel_and_subscription(monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(
        "retail.web_push.send_user_push",
        lambda user, payload, **kwargs: sent.append(payload) or True,
    )
    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV",
        store="lider", price=100000, previous_price=200000, message="50%",
        url=None, compare_code="tv-push",
        extra={"percent": 50, "product_id": "p1"},
    )
    user = {
        "id": "u1",
        "push_subscriptions": [{"endpoint": "https://push.example/1", "keys": {"p256dh": "a", "auth": "b"}}],
        "notification_preferences": {"channels": ["push"], "kinds": ["common"]},
    }
    assert alerts.dispatch_user_alerts([deal], [user], system_channels=["log", "telegram"]) == 0
    assert sent == []
    assert alerts.dispatch_user_alerts([deal], [user], system_channels=["push"]) == 1
    assert len(sent) == 1


def test_user_email_requires_admin_correo_channel(monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    sent = []
    monkeypatch.setattr(alerts, "send_email", lambda *args, **kwargs: sent.append(args) or True)
    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV",
        store="lider", price=100000, previous_price=200000, message="50%",
        url=None, compare_code="tv-email-gate",
        extra={"percent": 50, "product_id": "p1"},
    )
    user = {
        "id": "u1",
        "email": "ana@example.com",
        "notification_preferences": {"channels": ["email"], "kinds": ["common"]},
    }
    assert alerts.dispatch_user_alerts(
        [deal], [user], system_channels=["log", "file", "telegram"],
    ) == 0
    assert sent == []
    assert alerts.dispatch_user_alerts(
        [deal], [user], system_channels=["log", "file", "telegram", "email"],
    ) == 1
    assert len(sent) == 1
    assert sent[0][0] == "ana@example.com"


def test_push_test_needs_subscription_and_hides_endpoint(monkeypatch):
    from retail.batch import alerts

    class Repo:
        def update_user_fields(self, *_args, **_kwargs):
            return True

    assert alerts.send_push_test({}, repo=Repo())["ok"] is False
    monkeypatch.setattr("retail.web_push.send_user_push", lambda *args, **kwargs: True)
    result = alerts.send_push_test(
        {
            "id": "1",
            "push_subscriptions": [
                {"endpoint": "https://fcm.googleapis.com/secret-endpoint", "keys": {"p256dh": "a", "auth": "b"}},
            ],
        },
        repo=Repo(),
    )
    assert result["ok"] is True
    assert "secret-endpoint" not in str(result)
    assert "push" in result["message"].lower()


def test_admin_push_test_endpoint(monkeypatch):
    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1", "email": "admin@example.com"},
    )

    class Repo:
        def find_user_by_id(self, _user_id):
            return {
                "id": "1",
                "push_subscriptions": [
                    {"endpoint": "https://push.example/secret", "keys": {"p256dh": "a", "auth": "b"}},
                ],
            }

        def close(self):
            pass

    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: Repo())
    monkeypatch.setattr(
        "retail.batch.alerts.send_push_test",
        lambda document, repo=None: {"ok": True, "message": "Aviso push de prueba enviado a tus dispositivos."},
    )
    response = TestClient(app).post("/api/admin/test-push")
    assert response.status_code == 200
    assert "push" in response.json()["message"].lower()
    assert "secret" not in response.text
