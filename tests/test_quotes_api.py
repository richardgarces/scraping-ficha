from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from retail.web.app import app


def _matches(doc, query):
    for key, value in query.items():
        current = doc.get(key)
        if isinstance(value, dict):
            if "$ne" in value and current == value["$ne"]:
                return False
            if "$in" in value and current not in value["$in"]:
                return False
            continue
        if current != value:
            return False
    return True


class Cursor:
    def __init__(self, documents):
        self.documents = documents

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self):
        self.documents = []

    def count_documents(self, query, **kwargs):
        return sum(1 for doc in self.documents if _matches(doc, query))

    def insert_one(self, document):
        self.documents.append(deepcopy(document))

    def find_one(self, query):
        return next((deepcopy(doc) for doc in self.documents if _matches(doc, query)), None)

    def find(self, query, projection=None):
        rows = [deepcopy(doc) for doc in self.documents if _matches(doc, query)]
        if projection:
            include = {key for key, enabled in projection.items() if enabled}
            exclude = {key for key, enabled in projection.items() if not enabled}
            projected = []
            for row in rows:
                if include:
                    projected.append({key: row[key] for key in include if key in row})
                else:
                    projected.append({key: value for key, value in row.items() if key not in exclude})
            rows = projected
        return Cursor(rows)

    def update_one(self, query, updates):
        found = next((doc for doc in self.documents if _matches(doc, query)), None)
        if found is None:
            return SimpleNamespace(matched_count=0)
        for key, value in updates.get("$set", {}).items():
            if key.startswith("selections."):
                found.setdefault("selections", {})[key.split(".", 1)[1]] = value
            else:
                found[key] = value
        for key, value in updates.get("$inc", {}).items():
            found[key] = found.get(key, 0) + value
        return SimpleNamespace(matched_count=1)


def _fake_current_user(user):
    def current_user(_request, _store=None, *, required=False, admin=False, detail=None):
        if admin:
            if not user:
                raise HTTPException(status_code=401, detail="Entra con tu cuenta de administrador.")
            if user.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Solo el administrador puede hacer eso.")
        elif required and not user:
            raise HTTPException(status_code=401, detail=detail or "Entra con tu cuenta.")
        return user

    return current_user


@pytest.fixture
def quotes_client(monkeypatch):
    quotes = Collection()
    events = Collection()
    user = {"id": "user-1", "role": "admin", "status": "approved"}
    doc = {"store": "lider", "product_id": "sku", "name": "Samsung Galaxy S25 256GB", "brand": "Samsung",
           "price": 600000, "stock": 5, "condition": "new", "updated_at": datetime.now(timezone.utc)}
    repo = SimpleNamespace(
        db=SimpleNamespace(business_quotes=quotes, business_quote_events=events),
        product_detail=lambda *args: doc,
        find_by_query=lambda *args, **kwargs: [doc],
        close=lambda: None,
    )
    monkeypatch.setattr("retail.web.quotes_api.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.quotes_api.current_user", _fake_current_user(user))
    return TestClient(app), user, quotes, events


def create(client):
    response = client.post("/api/quotes/import-csv", json={"title": "Compra", "tax_included": True,
                           "text": "nombre;cantidad;precio_unitario;marca\nSamsung Galaxy S25 256GB;2;700000;Samsung"})
    assert response.status_code == 201
    return response.json()["id"]


def test_quote_review_and_export_are_private_and_versioned(quotes_client):
    client, user, collection, events = quotes_client
    quote_id = create(client)
    assert client.get("/api/quotes").json()["quotes"][0]["status"] == "draft"
    candidate = client.get(f"/api/quotes/{quote_id}/candidates/0")
    assert len(candidate.json()["candidates"]) == 1
    body = {"index": 0, "store": "lider", "product_id": "sku", "version": 1}
    selected = client.put(f"/api/quotes/{quote_id}/selection", json=body)
    assert selected.status_code == 200
    assert selected.json()["report"]["summary"]["potential_saving"] == 200000
    assert selected.json()["report"]["summary"]["status"] == "compared"
    assert selected.json()["quote"]["status"] == "compared"
    assert selected.headers["cache-control"] == "no-store"
    assert client.put(f"/api/quotes/{quote_id}/selection", json=body).status_code == 409
    exported = client.get(f"/api/quotes/{quote_id}/export.csv")
    assert exported.status_code == 200
    assert client.get(f"/api/quotes/{quote_id}").json()["quote"]["status"] == "exported"
    user["id"] = "user-2"
    for suffix in ("", "/candidates/0", "/export.csv"):
        assert client.get(f"/api/quotes/{quote_id}{suffix}").status_code == 404
    assert client.put(f"/api/quotes/{quote_id}/selection", json=body).status_code == 404
    assert client.post(f"/api/quotes/{quote_id}/feedback", json={"kind": "useful"}).status_code == 404


def test_edit_clears_approvals_and_never_writes_retail_history(quotes_client):
    client, user, collection, events = quotes_client
    quote_id = create(client)
    client.put(f"/api/quotes/{quote_id}/selection", json={"index": 0, "store": "lider", "product_id": "sku", "version": 1})
    quote = client.get(f"/api/quotes/{quote_id}").json()["quote"]
    editable = {key: value for key, value in quote.items()
                if key not in {"id", "created_at", "updated_at", "selections", "exported_at", "status", "feedback"}}
    editable["items"][0]["quantity"] = 3
    response = client.put(f"/api/quotes/{quote_id}", json=editable)
    assert response.status_code == 200
    assert response.json()["quote"]["selections"] == {}
    assert response.json()["quote"]["status"] == "review"
    assert response.json()["report"]["summary"]["compared_items"] == 0
    assert len(collection.documents) == 1


def test_pilot_metrics_track_imports_matches_exports_and_errors(quotes_client):
    client, user, collection, events = quotes_client
    quote_id = create(client)
    assert client.post("/api/quotes/import-csv", json={"title": "Mala", "text": "nombre;precio\nProducto;10,5"}).status_code == 422
    client.put(f"/api/quotes/{quote_id}/selection", json={"index": 0, "store": "lider", "product_id": "sku", "version": 1})
    assert client.get(f"/api/quotes/{quote_id}/export.csv").status_code == 200
    metrics = client.get("/api/admin/purchasing-metrics").json()
    assert metrics["imports"] == 1
    assert metrics["matches"] == 1
    assert metrics["exports"] == 1
    assert metrics["errors"] == 1
    assert metrics["potential_saving_exported"] == 200000
    assert metrics["exported_quotes"] == 1


def test_quote_endpoints_require_login(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.quotes_api.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    response = client.post("/api/quotes/import-csv", json={"title": "Compra", "text": "nombre\nProducto"})
    assert response.status_code == 401


def test_cotizaciones_api_alias_requires_login(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.quotes_api.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    assert client.get("/api/cotizaciones").status_code == 401
    assert client.get("/api/quotes").status_code == 401


def test_quotes_page_requires_admin(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.quotes_api.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    page = client.get("/cotizaciones", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")
    assert "cotizaciones" in page.headers["location"]


def test_approved_non_admin_cannot_use_quotes_api(monkeypatch):
    quotes = Collection()
    events = Collection()
    user = {"id": "user-1", "role": "user", "status": "approved"}
    repo = SimpleNamespace(
        db=SimpleNamespace(business_quotes=quotes, business_quote_events=events),
        product_detail=lambda *args: None,
        find_by_query=lambda *args, **kwargs: [],
        close=lambda: None,
    )
    monkeypatch.setattr("retail.web.quotes_api.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.quotes_api.current_user", _fake_current_user(user))
    client = TestClient(app)
    assert client.get("/api/quotes").status_code == 403
    assert client.get("/api/cotizaciones").status_code == 403
    assert client.post("/api/quotes/import-csv", json={"title": "Compra", "text": "nombre\nProducto"}).status_code == 403
    assert client.get("/api/admin/purchasing-metrics").status_code == 403


def test_quotes_menu_link_is_admin_only():
    from pathlib import Path

    prices = Path("retail/web/static/prices.js").read_text(encoding="utf-8")
    assert 'link.href = "/cotizaciones"' in prices
    assert 'link.setAttribute("data-admin", "")' in prices
    assert "if (admin)" in prices
    assert 'user.role === "admin"' in prices
    html = Path("retail/web/static/cotizaciones.html").read_text(encoding="utf-8")
    assert 'href="/cotizaciones" class="current" data-admin hidden' in html
    script = Path("retail/web/static/cotizaciones.js").read_text(encoding="utf-8")
    assert 'user.role !== "admin"' in script


def test_oversized_quote_is_rejected_before_processing():
    response = TestClient(app).post("/api/quotes/import-csv", content=b"x" * 600001,
                                   headers={"Content-Type": "application/json"})
    assert response.status_code == 413
