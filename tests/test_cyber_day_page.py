"""Página y API Cyber Day solo admin."""

from pathlib import Path

from fastapi.testclient import TestClient

from retail.web.app import app


def test_cyber_day_page_requires_admin(anonymous_repo):
    client = TestClient(app)
    page = client.get("/cyber-day", follow_redirects=False)
    assert page.status_code in {302, 303}
    assert "/entrar" in (page.headers.get("location") or "")
    alias = client.get("/cyber", follow_redirects=False)
    assert alias.status_code in {302, 303}


def test_cyber_day_api_requires_admin(anonymous_repo):
    client = TestClient(app)
    assert client.get("/api/admin/cyber-day").status_code == 401
    assert client.post("/api/admin/cyber-day/start").status_code == 401
    assert client.get("/api/admin/cyber-day/export.csv").status_code == 401
    assert client.get("/api/admin/cyber-day/export.json").status_code == 401


def test_cyber_day_static_assets_exist():
    root = Path("retail/web/static")
    html = (root / "cyber-day.html").read_text(encoding="utf-8")
    js = (root / "cyber-day.js").read_text(encoding="utf-8")
    assert 'href="/cyber-day"' in html
    assert "data-admin" in html
    assert "cyber-export-csv" in html
    assert "Reiniciar" in html
    assert "/api/admin/cyber-day" in js
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert 'href = "/cyber-day"' in prices or 'href="/cyber-day"' in prices
    assert 'textContent = "Cyber Day"' in prices
