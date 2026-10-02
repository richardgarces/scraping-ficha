from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

from retail.product_analysis import build_product_analysis, parse_ficha_ref, stock_state
from retail.web.app import app


def test_stock_state_does_not_invent_quantities():
    assert stock_state(7, None)["quantity_label"] == "7 unidades"
    assert stock_state(0, None)["quantity_kind"] == "exact"
    assert stock_state(True, None)["quantity_kind"] == "available"
    assert stock_state(None, "Disponible")["quantity"] is None
    assert stock_state(None, "Sin stock")["quantity"] == 0
    assert stock_state(None, None)["quantity_kind"] == "unknown"
    assert stock_state(None, {"message": "Disponible para despacho"})["availability"] == "Disponible para despacho"
    assert stock_state(None, {"available": False})["availability"] == "Sin stock"


def test_parse_ficha_ref_accepts_absolute_relative_and_host_without_scheme():
    assert parse_ficha_ref("https://precios.meincart.cl/producto?store=dolly&id=9227") == ("dolly", "9227")
    assert parse_ficha_ref("/producto?store=Dolly&id=9227") == ("dolly", "9227")
    assert parse_ficha_ref("producto?store=dolly&id=9227") == ("dolly", "9227")
    assert parse_ficha_ref("precios.meincart.cl/producto?id=9227&store=dolly") == ("dolly", "9227")
    assert parse_ficha_ref("https://precios.meincart.cl/producto?store=thelab&id=sku%201") == ("thelab", "sku 1")
    assert parse_ficha_ref("Samsung Galaxy S25") is None
    assert parse_ficha_ref("https://www.paris.cl/producto/algo") is None
    assert parse_ficha_ref("/producto?store=dolly") is None
    assert parse_ficha_ref("") is None


def test_analysis_groups_stores_prices_and_stock():
    result = build_product_analysis(
        {
            "query": "galaxy s25",
            "groups": [
                {
                    "name": "Galaxy S25 256GB",
                    "compare_code": "s25-256",
                    "offers": [
                        {
                            "store": "nike",
                            "product_id": "1",
                            "name": "Galaxy S25 256GB",
                            "price": 700000,
                            "stock": 4,
                            "from_scrape": True,
                        },
                        {
                            "store": "paris",
                            "product_id": "2",
                            "name": "Galaxy S25 256GB",
                            "price": 720000,
                            "availability": "Disponible",
                        },
                    ],
                }
            ],
        },
        {"nike": "Tienda A", "paris": "Paris"},
    )
    assert result["store_count"] == 2
    assert result["exact_quantity_count"] == 1
    assert result["groups"][0]["offers"][0]["price"] == 700000
    assert result["groups"][0]["offers"][1]["quantity_kind"] == "available"


def test_product_analysis_page_and_api_require_login(monkeypatch):
    monkeypatch.setattr("retail.web.app.connect_repo", lambda: None)

    def unavailable():
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")

    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", unavailable)
    client = TestClient(app)
    page = client.get("/analisis-producto", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar?next=/analisis-producto")
    for path in ("/api/product-analysis", "/api/admin/product-analysis"):
        response = client.post(path, json={"query": "televisor"})
        assert response.status_code in {401, 503}

    html = Path("retail/web/static/analisis-producto.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/analisis-producto.js").read_text(encoding="utf-8")
    assert "Análisis de producto" in html
    assert "<h2>Consultar precio</h2>" in html
    assert "Consultar precio y existencias" not in html
    assert "URI de ficha, nombre, modelo, SKU o código de barras" in html
    assert 'maxlength="500"' in html
    assert 'data-admin hidden><input id="analysis-live"' in html
    assert "/api/product-analysis" in script
    assert "currentUser?.role === \"admin\"" in script
    assert "/api/admin/entity-overrides" in script
    assert "Cantidad" in script
    assert "Todo medio" in script
    assert 'const adminHeaders = currentUser?.role === "admin"' in script
    assert "setAnalysisBusy" in script
    assert 'class="spinner"' in script
    assert "Analizando…" in script


def test_product_analysis_api_returns_shaped_results(monkeypatch):
    class Repo:
        def close(self):
            return None

    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", lambda: Repo())
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.current_user",
        lambda *args, **kwargs: {"id": "1", "role": "admin"},
    )
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.search_products",
        lambda query, **kwargs: {
            "query": query,
            "groups": [{"name": "Producto", "offers": [{"store": "lider", "product_id": "1", "price": 9990, "stock": 3}]}],
        },
    )
    response = TestClient(app).post("/api/product-analysis", json={"query": "Producto", "live": True})
    assert response.status_code == 200
    body = response.json()
    assert body["store_count"] == 1
    assert body["groups"][0]["offers"][0]["quantity"] == 3


def test_product_analysis_api_resolves_ficha_uri_to_seed_name(monkeypatch):
    class Repo:
        def product_detail(self, store, product_id):
            assert store == "dolly"
            assert product_id == "9227"
            return {
                "store": "dolly",
                "product_id": "9227",
                "name": "Silla ergonómica Dolly Pro",
                "brand": "Dolly",
            }

        def close(self):
            return None

    calls = []
    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", lambda: Repo())
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.current_user",
        lambda *args, **kwargs: {"id": "1", "role": "admin"},
    )
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.search_products",
        lambda query, **kwargs: calls.append(query) or {
            "query": query,
            "groups": [{"name": query, "offers": [{"store": "dolly", "product_id": "9227", "price": 19990, "stock": 2}]}],
        },
    )
    response = TestClient(app).post(
        "/api/product-analysis",
        json={"query": "https://precios.meincart.cl/producto?store=dolly&id=9227", "live": False},
    )
    assert response.status_code == 200
    assert calls == ["Silla ergonómica Dolly Pro"]
    body = response.json()
    assert body["seed"] == {"store": "dolly", "product_id": "9227", "name": "Silla ergonómica Dolly Pro"}
    assert body["resolved_query"] == "Silla ergonómica Dolly Pro"
    assert body["store_count"] == 1


def test_product_analysis_api_rejects_unknown_ficha(monkeypatch):
    class Repo:
        def product_detail(self, store, product_id):
            return None

        def close(self):
            return None

    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", lambda: Repo())
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.current_user",
        lambda *args, **kwargs: {"id": "1", "role": "admin"},
    )
    response = TestClient(app).post(
        "/api/product-analysis",
        json={"query": "/producto?store=dolly&id=999999", "live": False},
    )
    assert response.status_code == 404
    assert "guardado" in response.json()["detail"]


def test_regular_user_can_analyze_saved_data_but_not_query_stores(monkeypatch):
    class Repo:
        def close(self):
            return None

    calls = []
    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", lambda: Repo())
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.current_user",
        lambda *args, **kwargs: {"id": "2", "role": "user", "status": "approved"},
    )
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.search_products",
        lambda query, **kwargs: calls.append(kwargs) or {
            "query": query,
            "groups": [{
                "name": "Producto",
                "offers": [{
                    "store": "lider", "product_id": "1", "price": 9990,
                    "stock": 3, "shipping_cost": 2990, "entity_confidence": 0.95,
                }],
            }],
        },
    )
    client = TestClient(app)

    saved = client.post("/api/product-analysis", json={"query": "Producto", "live": False})
    assert saved.status_code == 200
    assert calls[0]["source"] == "db"
    assert calls[0]["persist"] is False
    assert calls[0]["fresh"] is False
    regular_offer = saved.json()["groups"][0]["offers"][0]
    assert "shipping_cost" not in regular_offer
    assert "quantity" not in regular_offer
    assert "availability" not in regular_offer
    assert "checked_live" not in regular_offer
    assert "entity_confidence" not in regular_offer
    assert "exact_quantity_count" not in saved.json()

    live = client.post("/api/product-analysis", json={"query": "Producto", "live": True})
    assert live.status_code == 403
    assert "administrador" in live.json()["detail"]
    assert len(calls) == 1


def test_admin_can_persist_manual_entity_merge(monkeypatch):
    class Repo:
        saved = None

        def set_entity_overrides(self, products, overrides):
            self.saved = (products, overrides)
            return {"matched": len(products), "modified": len(products)}

        def close(self):
            return None

    repo = Repo()
    monkeypatch.setattr("retail.web.admin_analysis_api.repo_or_503", lambda: repo)
    monkeypatch.setattr(
        "retail.web.admin_analysis_api.current_user",
        lambda *args, **kwargs: {"id": "1", "role": "admin"},
    )
    response = TestClient(app).post("/api/admin/entity-overrides", json={
        "action": "merge",
        "products": [
            {"store": "paris", "product_id": "1"},
            {"store": "ripley", "product_id": "2"},
        ],
    })
    assert response.status_code == 200
    products, overrides = repo.saved
    assert products == [("paris", "1"), ("ripley", "2")]
    assert overrides[0] == overrides[1]
    assert overrides[0].startswith("manual:")
