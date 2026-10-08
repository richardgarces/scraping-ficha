"""Ranking /tiendas: admin-only, cobertura registry y exclusión de agregadores."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from retail.web.app import app
from retail.web import insights_api


NOW = datetime(2026, 10, 8, 16, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, documents):
        self.documents = documents

    def limit(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self.documents)


class Collection:
    def __init__(self, documents):
        self.documents = documents

    def find(self, query, projection=None):
        return Cursor(list(self.documents))


def _history(prices, *, start=None):
    start = start or (NOW - timedelta(days=40))
    rows = []
    for index, price in enumerate(prices):
        rows.append({
            "price": price,
            "scraped_at": (start + timedelta(days=index)).isoformat(),
            "price_basis": "all_payment",
        })
    return rows


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
def stores_client(monkeypatch):
    docs = [
        {
            "store": "falabella",
            "product_id": "a",
            "name": "Shampoo",
            "url": "https://example/a",
            "price": 6000,
            "updated_at": NOW,
            "price_history": _history([10000, 10000, 6000]),
        },
        {
            "store": "knasta",
            "product_id": "k1",
            "name": "Shampoo agregador",
            "url": "https://knasta.cl/x",
            "price": 5500,
            "updated_at": NOW,
            "price_history": _history([10000, 10000, 5500]),
        },
        {
            "store": "ripley",
            "product_id": "b",
            "name": "Shampoo Ripley",
            "url": "https://example/b",
            "price": 10000,
            "updated_at": NOW - timedelta(hours=2),
            "price_history": _history([10000, 10000, 10000]),
        },
    ]
    repo = SimpleNamespace(
        collection=Collection(docs),
        db=SimpleNamespace(app_settings=Collection([])),
        app_settings=Collection([]),
        close=lambda: None,
    )
    user = {"id": "admin-1", "role": "admin", "status": "approved"}
    monkeypatch.setattr("retail.web.insights_api.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.web.insights_api.current_user", _fake_current_user(user))
    monkeypatch.setattr(
        "retail.web.insights_api.list_stores",
        lambda: [
            SimpleNamespace(id="falabella", title="Falabella"),
            SimpleNamespace(id="ripley", title="Ripley"),
            SimpleNamespace(id="paris", title="Paris"),
            SimpleNamespace(id="knasta", title="Knasta"),
        ],
    )
    monkeypatch.setattr("retail.web.insights_api.list_store_bot_checks", lambda _repo: {})
    monkeypatch.setattr(
        "retail.web.insights_api.annotate_store_bot_checks",
        lambda rows, _checks: rows,
    )
    monkeypatch.setattr(
        "retail.web.insights_api.bot_check_api_rows",
        lambda _checks: [],
    )
    return TestClient(app), user, repo


def test_stores_report_requires_admin(stores_client, monkeypatch):
    client, user, _repo = stores_client
    user["role"] = "user"
    monkeypatch.setattr("retail.web.insights_api.current_user", _fake_current_user(user))
    response = client.get("/api/stores-report")
    assert response.status_code == 403
    assert "administrador" in response.json()["detail"].casefold()
    drops = client.get("/api/stores-drops?store=falabella")
    assert drops.status_code == 403


def test_stores_report_covers_registry_excludes_knasta(stores_client):
    client, _user, _repo = stores_client
    response = client.get("/api/stores-report")
    assert response.status_code == 200, response.text
    body = response.json()
    stores = {row["store"]: row for row in body["stores"]}
    assert "knasta" not in stores
    assert stores["paris"]["products"] == 0
    assert stores["paris"]["coverage"] == "sin_muestra"
    assert stores["falabella"]["products"] >= 1
    assert stores["falabella"]["coverage"] in {"ok", "sin_bajas"}
    assert stores["ripley"]["coverage"] in {"ok", "sin_bajas"}
    assert body["registry_stores"] == 3  # falabella, ripley, paris (sin knasta)
    assert body["ranked_stores"] >= 2
    assert body["scan_limit"] == insights_api.REPORT_SCAN_LIMIT
    assert body["stale_hours"] == 48
    assert "last_seen" in stores["falabella"]


def test_stores_drops_rejects_knasta_and_counts_inflated(stores_client):
    client, _user, _repo = stores_client
    denied = client.get("/api/stores-drops?store=knasta")
    assert denied.status_code == 404
    ok = client.get("/api/stores-drops?store=falabella")
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["total"] == len(payload["items"])
    assert "inflated" in payload
