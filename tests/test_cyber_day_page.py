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
    assert client.patch("/api/admin/cyber-day/items/1", json={"query": "x"}).status_code == 401
    assert client.put("/api/admin/cyber-day/items/1", json={"query": "x"}).status_code == 401


def test_cyber_day_static_assets_exist():
    root = Path("retail/web/static")
    html = (root / "cyber-day.html").read_text(encoding="utf-8")
    js = (root / "cyber-day.js").read_text(encoding="utf-8")
    assert 'href="/cyber-day"' in html
    assert "data-admin" in html
    assert "cyber-export-csv" in html
    assert "Reiniciar" in html
    assert "cyber-list-select" in html
    assert "Nueva lista" in html
    assert "cyber-day.js?v=9" in html
    assert "<th>Matches</th>" not in html
    assert "last_match_count" not in js  # columna UI quitada; sigue en API/export
    assert "Precio más alto normal" in html
    assert "Tiendas" in html
    assert "Mejor oferta" in html
    assert "scroll-x" in html
    assert "/api/admin/cyber-day" in js
    assert "cyber-day/lists" in js
    assert "cyber-day/items/" in js
    assert "cyber-query-input" in js
    assert "Query actualizada" in js
    assert "FETCH_TIMEOUT_MS = 8000" in js
    assert "SEED_FALLBACK_URL" in js
    assert "(() => {" in js
    assert "function flash(" not in js  # choca con window.flash (#flash)
    assert "showFlash" in js
    assert "applyActionButtons" in js
    assert "stores_scraped" in js
    assert "best_offer_url" in js
    assert "status === \"running\"" in js or 'status === "running"' in js
    assert (root / "cyber_junio2026.json").is_file()
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert 'href = "/cyber-day"' in prices or 'href="/cyber-day"' in prices
    assert 'textContent = "Cyber Day"' in prices
    cron_js = (root / "cron.js").read_text(encoding="utf-8")
    assert "queries" in cron_js
    assert "query_list" in cron_js


def test_cyber_day_update_item_api_admin(monkeypatch, mongo_uri):
    from uuid import uuid4

    from retail.cyber_day import ensure_seed
    from retail.mongo import ProductRepository

    repo = ProductRepository(mongo_uri, database=f"test_cyber_api_{uuid4().hex}")
    real_close = repo.close
    try:
        ensure_seed(repo)
        repo.close = lambda: None  # settings_api cierra tras cada request
        monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: repo)
        monkeypatch.setattr(
            "retail.web.settings_api.current_user",
            lambda *_a, **_k: {"role": "admin", "status": "approved"},
        )
        monkeypatch.setattr(
            "retail.cyber_day.catalog_matches_for_query",
            lambda *_a, **_k: [],
        )
        client = TestClient(app)
        response = client.patch(
            "/api/admin/cyber-day/items/1",
            json={"query": "Samsung Galaxy S26 Ultra"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["message"] == "Query actualizada"
        assert payload["updated"]["query"] == "Samsung Galaxy S26 Ultra"
        assert payload["updated"]["last_match_count"] == 0
        empty = client.patch("/api/admin/cyber-day/items/1", json={"query": "  "})
        assert empty.status_code == 400
    finally:
        repo.close = real_close
        real_close()
