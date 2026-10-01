"""La lista de usuarios es solo para el administrador y no expone secretos."""

from pathlib import Path

from fastapi.testclient import TestClient

from retail.mongo import ProductRepository
from retail.web.app import app

STATIC = Path("retail/web/static")


def test_usuarios_page_and_api_require_admin(anonymous_repo):
    client = TestClient(app)
    denied = client.get("/api/admin/users")
    assert denied.status_code == 401
    page = client.get("/usuarios", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")
    assert "next=" in page.headers["location"]
    home = (STATIC / "index.html").read_text()
    assert 'href="/usuarios"' in home
    assert ">Usuarios</a>" in home
    html = (STATIC / "usuarios.html").read_text()
    js = (STATIC / "usuarios.js").read_text()
    assert "usuarios.js?v=2" in html
    assert "function $(id)" not in js
    assert "/api/admin/users" in js
    assert 'href="/usuarios"' in html
    entrar = (STATIC / "entrar.js").read_text()
    assert "/usuarios" in entrar


def test_admin_user_view_omits_secrets():
    row = ProductRepository.admin_user_public(
        {
            "_id": "abc",
            "email": "ana@example.com",
            "name": "Ana",
            "role": "user",
            "status": "approved",
            "password_hash": "scrypt$secreto",
            "password": "clave1234",
            "token": "sess-no",
            "telegram_chat_id": "99",
            "telegram_bot_token": "bot",
        },
        price_alerts=3,
    )
    assert row["email"] == "ana@example.com"
    assert row["name"] == "Ana"
    assert row["has_telegram"] is True
    assert row["price_alerts"] == 3
    blob = " ".join(str(value) for value in row.values())
    assert "scrypt$secreto" not in blob
    assert "clave1234" not in blob
    assert "sess-no" not in blob
    assert "99" not in blob
    assert "bot" not in blob
    assert "password" not in row
    assert "telegram_chat_id" not in row


def test_admin_users_api_returns_public_rows(monkeypatch):
    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1"},
    )

    class Repo:
        def list_admin_users(self):
            return [
                {
                    "id": "1",
                    "email": "ana@example.com",
                    "name": "Ana",
                    "created_at": "2026-01-02T15:00:00+00:00",
                    "has_telegram": False,
                    "price_alerts": 1,
                }
            ]

        def close(self):
            return None

    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: Repo())
    response = TestClient(app).get("/api/admin/users")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    user = payload["users"][0]
    assert user["email"] == "ana@example.com"
    assert "password_hash" not in user
    assert "token" not in user
