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
    evo = client.get("/cyber-day/evolucion?list=cyber_junio2026&n=1", follow_redirects=False)
    assert evo.status_code in {302, 303}


def test_cyber_day_api_requires_admin(anonymous_repo):
    client = TestClient(app)
    assert client.get("/api/admin/cyber-day").status_code == 401
    assert client.post("/api/admin/cyber-day/start").status_code == 401
    assert client.get("/api/admin/cyber-day/export.csv").status_code == 401
    assert client.get("/api/admin/cyber-day/export.json").status_code == 401
    assert client.patch("/api/admin/cyber-day/items/1", json={"query": "x"}).status_code == 401
    assert client.put("/api/admin/cyber-day/items/1", json={"query": "x"}).status_code == 401
    assert client.get("/api/admin/cyber-day/items/1/evolution").status_code == 401
    assert client.delete("/api/admin/cyber-day/lists?list=x").status_code == 401


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
    assert "cyber-delete-list" in html
    assert "Eliminar lista" in html
    assert "Importar / actualizar lista activa" in html
    assert "reemplaza las queries" in html
    assert "cyber-day.js?v=23" in html
    assert "styles.css?v=92" in html
    assert 'href="/cambios-precio"' in html
    assert "application/json; charset=utf-8" in js  # import raw JSON (no FormData/multipart)
    assert "new FormData()" not in js
    assert "<h1>Cyber</h1>" in html
    assert "cyber_junio2026" not in html  # branding genérico; slug solo backend/lista
    assert "<th>Matches</th>" not in html
    cron = (root / "cron.html").read_text(encoding="utf-8")
    assert "<h2>Cyber</h2>" in cron
    assert "Abrir Cyber" in cron
    assert "cyber_junio2026" not in cron
    assert "lista activa" in cron
    assert "last_match_count" not in js  # columna UI quitada; sigue en API/export
    assert "Precio más alto normal" in html
    assert "Tienda mejor precio" in html
    assert "Último cambio" in html
    assert "formatLastChange" in js
    assert "last_change_at" in js
    assert "Tiendas" in html
    assert "Mejor oferta" in html
    assert "<th>Evolución</th>" in html
    assert "<th>Descuento</th>" in html
    assert "<th>Pronóstico</th>" in html
    assert "cyber-legend" in html
    assert "cyber-dashboard" in html
    assert "renderDashboard" in js
    assert "discountCellHtml" in js
    assert "adviceCellHtml" in js
    assert "scroll-x" in html
    assert "/api/admin/cyber-day" in js
    assert "cyber-day/lists" in js
    assert "cyber-day/items/" in js
    assert "/cyber-day/evolucion" in js
    assert ">Informe<" in js or "Informe</a>" in js
    evo_html = (root / "cyber-day-evolucion.html").read_text(encoding="utf-8")
    evo_js = (root / "cyber-day-evolucion.js").read_text(encoding="utf-8")
    assert "Evolución del precio" in evo_html
    assert "cyber-day-evolucion.js?v=4" in evo_html
    assert "styles.css?v=92" in evo_html
    assert "chart-observations" in evo_html
    assert "Pronóstico experimental" in evo_html
    assert "cyber-evo-forecast" in evo_html
    assert "cyber-evo-mode" in evo_html
    assert "Evento completo" in evo_html
    assert "Menor valor" in evo_js
    assert "Mayor descuento" in evo_js
    assert "Tienda:" in evo_js
    assert "/api/admin/cyber-day/items/" in evo_js
    assert "evolution" in evo_js
    assert "renderForecast" in evo_js
    assert "Conviene comprar" in evo_js
    assert "Mejor esperar" in evo_js
    assert 'range === "event"' in evo_js or "range === 'event'" in evo_js
    assert "syncRangeControls" in evo_js
    assert "cyber-delete-list" in js
    assert 'method: "DELETE"' in js
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
    assert "best_store_title" in js
    assert "bestStoreCellText" in js
    assert "prev_best_store" in js
    assert "priceCellHtml" in js
    assert "down_again" in js
    assert "up_again" in js
    assert "price-arrow" in js
    assert "price-streak" in js
    assert "streak >= 2" in js
    styles = (root / "styles.css").read_text(encoding="utf-8")
    assert "down-again" in styles
    assert "up-again" in styles
    assert "price-streak" in styles
    assert "cyber-legend" in styles
    assert "cyber-dashboard" in styles
    assert "cyber-advice-chip" in styles
    assert 'nameEl.textContent = "Cyber"' in js
    assert "status === \"running\"" in js or 'status === "running"' in js
    assert "Pará la lista antes de eliminarla" in js
    assert (root / "cyber_junio2026.json").is_file()
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert 'href = "/cyber-day"' in prices or 'href="/cyber-day"' in prices
    assert 'textContent = "Cyber"' in prices
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
        evo = client.get("/api/admin/cyber-day/items/1/evolution?list=cyber_junio2026")
        assert evo.status_code == 200
        evo_payload = evo.json()
        assert evo_payload["ok"] is True
        assert evo_payload["n"] == 1
        assert evo_payload["list_id"] == "cyber_junio2026"
        assert evo_payload["timezone"] == "America/Santiago"
        assert isinstance(evo_payload["observations"], list)
        assert "forecast" in evo_payload
        assert evo_payload["forecast"]["ok"] is True
        assert evo_payload["forecast"]["summary"] is None or isinstance(
            evo_payload["forecast"]["summary"], dict
        )
        monkeypatch.setattr("retail.web.app.require_admin_html", lambda *a, **k: None)
        page = client.get("/cyber-day/evolucion?list=cyber_junio2026&n=1")
        assert page.status_code == 200
        assert "Evolución del precio" in page.text
        assert "Pronóstico experimental" in page.text
    finally:
        repo.close = real_close
        real_close()


def test_cyber_day_delete_and_reimport_api_admin(monkeypatch, mongo_uri):
    from uuid import uuid4

    from retail.cyber_day import create_list, ensure_seed, start_run
    from retail.mongo import ProductRepository

    repo = ProductRepository(mongo_uri, database=f"test_cyber_del_{uuid4().hex}")
    real_close = repo.close
    try:
        ensure_seed(repo)
        create_list(repo, name="Cyber Temp", slug="cyber_temp", use_seed=True)
        repo.close = lambda: None
        monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: repo)
        monkeypatch.setattr(
            "retail.web.settings_api.current_user",
            lambda *_a, **_k: {"role": "admin", "status": "approved"},
        )
        client = TestClient(app)

        start_run(repo, list_id="cyber_temp")
        blocked = client.delete("/api/admin/cyber-day/lists?list=cyber_temp")
        assert blocked.status_code == 409

        assert client.post("/api/admin/cyber-day/stop?list=cyber_temp").status_code == 200
        deleted = client.delete("/api/admin/cyber-day/lists?list=cyber_temp")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] == "cyber_temp"

        reimport = client.post(
            "/api/admin/cyber-day/import?list=cyber_junio2026",
            json={"items": [{"n": 1, "query": "Solo reimport", "category": "Audio"}]},
        )
        assert reimport.status_code == 200
        payload = reimport.json()
        assert payload["imported"] == 1
        assert payload["list_id"] == "cyber_junio2026"
        assert payload["list"]["name"]

        # Array JSON raw (mismo shape que el archivo del usuario / UI v13).
        raw_array = client.post(
            "/api/admin/cyber-day/import?list=cyber_junio2026",
            content='[{"n":1,"query":"TV OLED 55\\"","category":"TV"},'
            '{"n":2,"query":"Lavadora 9–12 kg","category":"Línea blanca"}]',
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        assert raw_array.status_code == 200
        assert raw_array.json()["imported"] == 2
    finally:
        repo.close = real_close
        real_close()
