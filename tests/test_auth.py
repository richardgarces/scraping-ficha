from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

from retail.auth import safe_next
from retail.users import authenticate, change_password, confirm_email, create_password_reset, reset_password, signup
from retail.web.app import _personalize_search_result, _with_store_preferences, app


class FakeUserStore:
    def __init__(self):
        self.users = []
        self._n = 0

    def find_user_by_email(self, email):
        return next((item for item in self.users if item["email"] == email), None)

    def find_user_by_id(self, user_id):
        return next((item for item in self.users if str(item.get("_id")) == str(user_id)), None)

    def find_user_by_confirmation_token_hash(self, token_hash):
        return next((item for item in self.users if item.get("confirmation_token_hash") == token_hash), None)

    def find_user_by_password_reset_token_hash(self, token_hash):
        return next((item for item in self.users if item.get("password_reset_token_hash") == token_hash), None)

    def insert_user(self, data):
        self._n += 1
        row = dict(data)
        row["_id"] = str(self._n)
        self.users.append(row)
        return row

    def update_user(self, user_id, fields):
        found = self.find_user_by_id(user_id)
        if not found:
            return None
        found.update(fields)
        return found

    def _public_user(self, item):
        if not item:
            return None
        return {
            "id": str(item.get("_id") or ""),
            "email": item.get("email"),
            "name": item.get("name") or "",
            "role": item.get("role") or "user",
            "status": item.get("status") or "pending",
        }


def test_safe_next_blocks_open_redirects():
    assert safe_next("/ofertas") == "/ofertas"
    assert safe_next("/ofertas?x=1") == "/ofertas?x=1"
    assert safe_next("https://evil.example") == "/"
    assert safe_next("//evil.example") == "/"
    assert safe_next("\\ofertas") == "/"
    assert safe_next(None, "/ofertas") == "/ofertas"


def test_ofertas_and_history_are_admin_only(anonymous_repo):
    client = TestClient(app)
    page = client.get("/ofertas", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")
    quotes = client.get("/cotizaciones", follow_redirects=False)
    assert quotes.status_code == 303
    assert quotes.headers["location"].startswith("/entrar")
    history = client.get("/api/history")
    assert history.status_code == 200
    assert history.json() == []
    settings = client.get("/api/settings")
    assert settings.status_code == 401


def test_price_alert_delete_requires_authentication(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.insights_api.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    response = client.delete("/api/price-alert?store=lider&id=sku-1")
    assert response.status_code == 401


def test_entrar_offers_public_signup():
    client = TestClient(app)
    page = client.get("/entrar")
    assert page.status_code == 200
    assert "Inscribirse" in page.text
    assert 'id="register-form"' in page.text
    home = client.get("/")
    assert "Inscribirse" in home.text


def test_signup_requires_email_confirmation():
    store = FakeUserStore()
    user = signup(store, "ana@example.com", "clave1234", "Ana")
    assert user["status"] == "pending"
    assert user["role"] == "user"
    assert user["name"] == "Ana"
    token = user["_confirmation_token"]
    with pytest.raises(ValueError, match="Confirma tu correo"):
        authenticate(store, "ana@example.com", "clave1234")
    confirmed = confirm_email(store, token)
    assert confirmed["status"] == "approved"
    logged = authenticate(store, "ana@example.com", "clave1234")
    assert logged["email"] == "ana@example.com"


def test_pending_user_cannot_login_without_confirmation():
    store = FakeUserStore()
    signup(store, "ana@example.com", "clave1234")
    with pytest.raises(ValueError, match="Confirma tu correo"):
        authenticate(store, "ana@example.com", "clave1234")


def test_password_reset_is_single_use_and_change_requires_current_password():
    store = FakeUserStore()
    user = signup(store, "ana@example.com", "clave1234")
    confirm_email(store, user["_confirmation_token"])
    _document, token = create_password_reset(store, "ana@example.com")
    assert token
    reset_password(store, token, "clave5678")
    with pytest.raises(ValueError, match="ya fue utilizado"):
        reset_password(store, token, "otra-clave")
    authenticate(store, "ana@example.com", "clave5678")
    with pytest.raises(ValueError, match="actual"):
        change_password(store, user["id"], "incorrecta", "clave9012")
    change_password(store, user["id"], "clave5678", "clave9012")
    authenticate(store, "ana@example.com", "clave9012")


def test_store_preferences_filter_and_put_favorites_first():
    args = _with_store_preferences({"stores": None}, ["paris", "lider"], ["ripley"])
    assert args["preferred_stores"] == ["paris", "lider"]
    assert args["excluded_stores"] == ["ripley"]
    result = _personalize_search_result({
        "stores": ["ripley", "lider", "paris"],
        "progress": [{"id": "ripley"}, {"id": "lider"}, {"id": "paris"}],
        "rows": [{"store": "ripley"}, {"store": "lider"}, {"store": "paris"}],
        "groups": [{"comparable": True, "offers": [
            {"store": "ripley", "price": 90}, {"store": "lider", "price": 100}, {"store": "paris", "price": 110},
        ]}],
    }, ["paris", "lider"], ["ripley"])
    assert [item["store"] for item in result["rows"]] == ["paris", "lider"]
    assert [item["store"] for item in result["groups"][0]["offers"]] == ["paris", "lider"]
    assert result["groups"][0]["lowest_price"] == 100


def test_rejected_email_cannot_signup():
    store = FakeUserStore()
    store.insert_user({"email": "no@example.com", "status": "rejected", "role": "user"})
    with pytest.raises(ValueError, match="no aceptó"):
        signup(store, "no@example.com", "clave1234")


def test_siguiendo_nav_is_hidden_until_login():
    client = TestClient(app)
    home = client.get("/")
    assert 'class="nav-menu" data-login' in home.text
    assert 'data-login-mode="inscribir"' in home.text
    assert 'class="nav-menu" data-auth hidden' in home.text
    assert 'href="/siguiendo"' in home.text
    assert "Inscribirse" in home.text
    assert home.text.index("Cuenta") < home.text.index("Inscribirse")


def test_real_and_super_offers_require_login():
    client = TestClient(app)
    reales = client.get("/reales", follow_redirects=False)
    assert reales.status_code == 303
    assert reales.headers["location"].startswith("/entrar?next=/reales")
    super_page = client.get("/super", follow_redirects=False)
    assert super_page.status_code == 302
    assert super_page.headers["location"] == "/reales?super=1"
    tiendas = client.get("/tiendas", follow_redirects=False)
    assert tiendas.status_code == 303
    assert tiendas.headers["location"].startswith("/entrar?next=/tiendas")
    comparar = client.get("/comparar?store=cugat&id=18221", follow_redirects=False)
    assert comparar.status_code == 303
    comparar_next = parse_qs(urlsplit(comparar.headers["location"]).query)["next"][0]
    assert comparar_next == "/comparar?store=cugat&id=18221"
    for path in ("/api/reales", "/api/super", "/api/stores-report", "/api/stores-drops?store=falabella"):
        denied = client.get(path)
        assert denied.status_code in {401, 503}
        assert denied.status_code != 200
        body = denied.json()
        assert "stores" not in body
        assert "items" not in body
        if denied.status_code == 401:
            assert "Inicia sesión" in body["detail"]
    stores_api = client.get("/api/stores-report")
    if stores_api.status_code == 401:
        assert "administrador" in stores_api.json()["detail"].casefold()
    drops_api = client.get("/api/stores-drops?store=falabella")
    if drops_api.status_code == 401:
        assert "administrador" in drops_api.json()["detail"].casefold()
    for path in ("/", "/hoy", "/catalogo"):
        assert client.get(path).status_code == 200
    entrar = client.get("/entrar?next=/reales")
    assert entrar.status_code == 200
    assert "entrar.js?v=16" in entrar.text
    js = Path("retail/web/static/entrar.js").read_text()
    assert "Inicia sesión para ver ofertas reales." in js
    assert "Inicia sesión para ver super ofertas." in js
    assert "Solo administradores pueden ver el ranking de tiendas." in js
    assert '"/tiendas"' in js
    assert '"/pronosticos"' in js
    assert '"/cambios-precio"' in js
    assert '"/analisis-producto"' in js
    assert 'dest.startsWith("/reales")' not in js


def test_logged_in_user_can_open_offer_pages(monkeypatch):
    class Store:
        def close(self):
            return None

    user = {"id": "1", "role": "user", "status": "approved"}
    monkeypatch.setattr("retail.web.deps.connect_repo", lambda: Store())
    monkeypatch.setattr("retail.web.deps.current_user", lambda *args, **kwargs: user)
    monkeypatch.setattr("retail.web.app.connect_repo", lambda: Store())
    monkeypatch.setattr("retail.web.app.current_user", lambda *args, **kwargs: user)
    client = TestClient(app)
    reales = client.get("/reales")
    assert reales.status_code == 200
    assert "Ofertas reales" in reales.text
    super_page = client.get("/super")
    assert super_page.status_code == 200
    comparar = client.get("/comparar?store=cugat&id=18221")
    assert comparar.status_code == 200
    assert "Comparar productos" in comparar.text
    analysis = client.get("/analisis-producto", follow_redirects=False)
    assert analysis.status_code == 303
    assert analysis.headers["location"] == "/entrar?next=/analisis-producto"
    assert "Super ofertas: descuento superior al 50%" in super_page.text
    tiendas = client.get("/tiendas", follow_redirects=False)
    assert tiendas.status_code == 303
    assert tiendas.headers["location"] == "/entrar?next=/tiendas"
    back = client.get("/entrar?next=/reales", follow_redirects=False)
    assert back.status_code == 303
    assert back.headers["location"] == "/reales"
    back_stores = client.get("/entrar?next=/tiendas", follow_redirects=False)
    assert back_stores.status_code == 200
    assert '<h2 id="auth-title">Entrar</h2>' in back_stores.text
    cron = client.get("/entrar?next=/cron", follow_redirects=False)
    assert cron.status_code == 200
    for admin_dest in ("/pronosticos", "/cambios-precio", "/tiendas", "/analisis-producto"):
        stuck = client.get(f"/entrar?next={admin_dest}", follow_redirects=False)
        assert stuck.status_code == 200, admin_dest
        assert '<h2 id="auth-title">Entrar</h2>' in stuck.text


def test_logged_in_admin_redirects_from_entrar_to_admin_pages(monkeypatch):
    class Store:
        def close(self):
            return None

    admin = {"id": "9", "role": "admin", "status": "approved"}
    monkeypatch.setattr("retail.web.deps.connect_repo", lambda: Store())
    monkeypatch.setattr("retail.web.deps.current_user", lambda *args, **kwargs: admin)
    monkeypatch.setattr("retail.web.app.connect_repo", lambda: Store())
    monkeypatch.setattr("retail.web.app.current_user", lambda *args, **kwargs: admin)
    client = TestClient(app)
    for dest in (
        "/pronosticos",
        "/cambios-precio",
        "/tiendas",
        "/analisis-producto",
        "/cotizaciones",
        "/cron",
    ):
        response = client.get(f"/entrar?next={dest}", follow_redirects=False)
        assert response.status_code == 303, dest
        assert response.headers["location"] == dest
    analysis = client.get("/analisis-producto")
    assert analysis.status_code == 200
    assert "Análisis de producto" in analysis.text
    from retail.web.deps import ADMIN_HTML_PREFIXES

    js = Path("retail/web/static/entrar.js").read_text(encoding="utf-8")
    for prefix in ADMIN_HTML_PREFIXES:
        assert f'"{prefix}"' in js


def test_watches_require_login():
    client = TestClient(app)
    listed = client.get("/api/watches")
    assert listed.status_code in {401, 503}
    created = client.post("/api/watches", json={"query": "tv lg", "name": "TV", "target_price": 100000})
    assert created.status_code in {401, 503}
    assert created.status_code != 200
