"""Cambios de precio (último mes) → export Cyber Day."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from retail.price_changes_month import (
    catalog_price_value_change,
    export_csv_text,
    export_json_payload,
    export_selected,
    list_price_changes,
    window_bounds,
)
from retail.web.app import app


def test_price_changes_page_requires_admin(anonymous_repo):
    client = TestClient(app)
    for path in ("/cambios-precio", "/cyber-day/cambios"):
        page = client.get(path, follow_redirects=False)
        assert page.status_code in {302, 303}
        assert "/entrar" in (page.headers.get("location") or "")


def test_price_changes_api_requires_admin(anonymous_repo):
    client = TestClient(app)
    assert client.get("/api/admin/price-changes").status_code == 401
    assert client.post("/api/admin/price-changes/export.csv", json={"ids": ["x"]}).status_code == 401
    assert client.post("/api/admin/price-changes/export.json", json={"ids": ["x"]}).status_code == 401


def test_price_changes_static_assets():
    root = Path("retail/web/static")
    html = (root / "cambios-precio.html").read_text(encoding="utf-8")
    js = (root / "cambios-precio.js").read_text(encoding="utf-8")
    assert "Cambios de precio" in html
    assert "cambios-precio.js?v=2" in html
    assert "prices.js?v=37" in html
    assert "styles.css?v=102-cambios-sort" in html
    assert "/api/admin/price-changes" in js
    assert "export.${kind}" in js or "price-changes/export" in js
    assert "select-filtered" in html
    assert "Exportar CSV" in html
    assert 'id="price-changes-table"' in html
    assert "col-sort" in html
    assert "sortState" in js
    assert "sortRows" in js
    cyber = (root / "cyber-day.html").read_text(encoding="utf-8")
    assert 'href="/cambios-precio"' in cyber
    cron = (root / "cron.html").read_text(encoding="utf-8")
    assert 'href="/cambios-precio"' in cron
    prices = (root / "prices.js").read_text(encoding="utf-8")
    assert "/cambios-precio" in prices


def test_window_bounds_santiago():
    # 2026-04-07 03:00 UTC = 2026-04-06 noche Chile (UTC-3/-4).
    now = datetime(2026, 4, 7, 15, 0, tzinfo=timezone.utc)
    bounds = window_bounds(30, now=now)
    assert bounds["timezone"] == "America/Santiago"
    assert bounds["days"] == 30
    assert bounds["to_day"] == "2026-04-07"
    assert bounds["from_day"] == "2026-03-08"


def test_catalog_price_value_change_detects_value_not_same_day_repeat():
    since = datetime(2026, 3, 1, tzinfo=timezone.utc)
    history = [
        {"price": 1000, "scraped_at": "2026-02-01T12:00:00+00:00"},
        {"price": 1000, "scraped_at": "2026-03-10T12:00:00+00:00"},  # mismo valor
        {"price": 900, "scraped_at": "2026-03-15T12:00:00+00:00"},
    ]
    change = catalog_price_value_change(history, since)
    assert change is not None
    assert change["previous_price"] == 1000
    assert change["price"] == 900

    no_change = catalog_price_value_change(
        [
            {"price": 1000, "scraped_at": "2026-02-01T12:00:00+00:00"},
            {"price": 1000, "scraped_at": "2026-03-10T12:00:00+00:00"},
        ],
        since,
    )
    assert no_change is None


def test_list_and_export_with_mongo(mongo_uri):
    from retail.mongo import ProductRepository

    repo = ProductRepository(mongo_uri, database=f"test_price_changes_{uuid4().hex}")
    try:
        now = datetime.now(timezone.utc)
        repo.collection.insert_one({
            "store": "falabella",
            "product_id": "sku-1",
            "name": "Notebook Gamer Test",
            "category": "Computación",
            "catalog_category": "Computación",
            "price": 500000,
            "url": "https://example.com/p/1",
            "price_history": [
                {"price": 600000, "scraped_at": now - timedelta(days=40)},
                {"price": 550000, "scraped_at": now - timedelta(days=10)},
                {"price": 500000, "scraped_at": now - timedelta(days=2)},
            ],
        })
        repo.cyber_day_price_history.insert_one({
            "list_id": "cyber_junio2026",
            "n": 1,
            "query": "iPhone 17 / 17 Pro",
            "day": "2026-03-20",
            "at": now - timedelta(days=5),
            "price": 999990,
            "store": "paris",
        })
        repo.cyber_day_products.insert_one({
            "list_id": "cyber_junio2026",
            "n": 1,
            "query": "iPhone 17 / 17 Pro",
            "category": "Celulares",
            "last_change_at": now - timedelta(days=5),
        })
        payload = list_price_changes(repo, days=30, now=now)
        assert payload["total"] >= 2
        queries = {row["query"] for row in payload["items"]}
        assert "Notebook Gamer Test" in queries
        assert "iPhone 17 / 17 Pro" in queries
        iphone = next(r for r in payload["items"] if "iPhone" in r["query"])
        assert iphone["category"] == "Celulares"
        assert "cyber_day" in iphone["sources"]

        selected = export_selected(payload["items"], selected_queries=["Notebook Gamer Test"])
        assert len(selected) == 1
        assert selected[0]["n"] == 1
        assert selected[0]["query"] == "Notebook Gamer Test"
        assert selected[0]["category"] == "Computación"

        csv_text = export_csv_text(selected)
        assert csv_text.splitlines()[0].startswith("n,query,category")
        assert "Notebook Gamer Test" in csv_text

        json_payload = export_json_payload(selected)
        assert json_payload["items"][0] == {
            "n": 1,
            "query": "Notebook Gamer Test",
            "category": "Computación",
        }
    finally:
        repo.client.drop_database(repo.db.name)
        repo.close()


def test_price_changes_export_api_admin(monkeypatch, mongo_uri):
    from retail.mongo import ProductRepository

    repo = ProductRepository(mongo_uri, database=f"test_price_api_{uuid4().hex}")
    real_close = repo.close
    try:
        now = datetime.now(timezone.utc)
        repo.collection.insert_one({
            "store": "ripley",
            "product_id": "r-1",
            "name": "TV Export Test",
            "category": "TV",
            "price": 200000,
            "price_history": [
                {"price": 250000, "scraped_at": now - timedelta(days=20)},
                {"price": 200000, "scraped_at": now - timedelta(days=1)},
            ],
        })
        repo.close = lambda: None
        monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: repo)
        monkeypatch.setattr(
            "retail.web.settings_api.current_user",
            lambda *_a, **_k: {"role": "admin", "id": "admin"},
        )
        client = TestClient(app)
        listed = client.get("/api/admin/price-changes?days=30")
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] >= 1
        ids = [row["id"] for row in body["items"] if "TV Export" in row["query"]]
        assert ids
        csv_resp = client.post(
            "/api/admin/price-changes/export.csv",
            json={"ids": ids, "days": 30},
        )
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers.get("content-type", "")
        assert "TV Export Test" in csv_resp.text
        assert csv_resp.text.splitlines()[0].startswith("n,query,category")

        json_resp = client.post(
            "/api/admin/price-changes/export.json",
            json={"ids": ids, "days": 30},
        )
        assert json_resp.status_code == 200
        data = json_resp.json()
        assert data["items"][0]["query"] == "TV Export Test"
        assert "category" in data["items"][0]
    finally:
        repo.close = real_close
        repo.client.drop_database(repo.db.name)
        repo.close()
