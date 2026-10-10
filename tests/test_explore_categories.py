"""Explora rápido / facetas de catálogo sin counts."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from retail.mongo import ProductRepository
from retail.relevance import category_icon_kind
from retail.web.app import app


@pytest.fixture
def repo(mongo_uri):
    repository = ProductRepository(mongo_uri, database=f"test_explore_cats_{uuid4().hex}")
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_browse_facets_default_omits_counts(repo):
    repo.collection.insert_many([
        {"store": "falabella", "product_id": "1", "name": "A", "catalog_category": "Tecnología", "price": 1000},
        {"store": "falabella", "product_id": "2", "name": "B", "catalog_category": "tecnologia", "price": 2000},
        {"store": "lider", "product_id": "3", "name": "C", "catalog_category": "calzado", "price": 3000},
        {"store": "lider", "product_id": "4", "name": "D", "catalog_category": "calzado", "price": 0},
    ])
    facets = repo.browse_facets(include_counts=False, fields=("categories",))
    rows = facets["categories"]
    assert rows
    assert all("count" not in row for row in rows)
    values = {str(row["value"]).casefold() for row in rows}
    assert "tecnología" in values or "tecnologia" in values
    assert "calzado" in values


def test_browse_facets_include_counts_keeps_totals(repo):
    repo.collection.insert_many([
        {"store": "falabella", "product_id": "1", "name": "A", "catalog_category": "calzado", "price": 1000},
        {"store": "falabella", "product_id": "2", "name": "B", "catalog_category": "calzado", "price": 2000},
        {"store": "lider", "product_id": "3", "name": "C", "catalog_category": "hogar", "price": 3000},
    ])
    facets = repo.browse_facets(include_counts=True, fields=("categories",))
    by_value = {row["value"]: row["count"] for row in facets["categories"]}
    assert by_value["calzado"] == 2
    assert by_value["hogar"] == 1


def test_category_icon_kind_matches_home_heuristics():
    assert category_icon_kind("Tecnología") == "tech"
    assert category_icon_kind("Accesorios Moda") == "fashion"
    assert category_icon_kind("Accesorios de Cocina") == "kitchen"
    assert category_icon_kind("Accesorios de seguridad infantil") == "baby"
    assert category_icon_kind("25% OFF") == "other"


def test_explore_categories_payload_has_icon_without_counts(repo):
    # Categorías basura alfabéticas + una popular: el sample debe priorizar frecuencia.
    docs = []
    for i in range(20):
        docs.append({
            "store": "falabella",
            "product_id": f"t{i}",
            "name": f"TV {i}",
            "catalog_category": "Tecnología",
            "price": 1000 + i,
        })
    docs.append({
        "store": "falabella",
        "product_id": "x1",
        "name": "Rare",
        "catalog_category": "25% OFF",
        "price": 500,
    })
    repo.collection.insert_many(docs)
    rows = repo.explore_categories(limit=10, sample_size=500)
    assert rows
    assert all("count" not in row for row in rows)
    assert all(row.get("icon") for row in rows)
    top = rows[0]
    assert top["value"] == "Tecnología"
    assert top["label"] == "Tecnología"
    assert top["icon"] == "tech"


def test_explore_categories_include_counts_optional(repo):
    repo.collection.insert_many([
        {"store": "falabella", "product_id": "1", "name": "A", "catalog_category": "calzado", "price": 1000},
        {"store": "falabella", "product_id": "2", "name": "B", "catalog_category": "calzado", "price": 2000},
        {"store": "lider", "product_id": "3", "name": "C", "catalog_category": "hogar", "price": 3000},
    ])
    rows = repo.explore_categories(limit=10, include_counts=True, sample_size=500)
    assert rows
    assert all("count" in row for row in rows)
    assert all(int(row["count"]) > 0 for row in rows)


@pytest.mark.parametrize(
    "query",
    [
        "azúcar granulada iansa",
        "azucar granulada iansa",
        "AZÚCAR IANSA",
        "azúcar ianza",
    ],
)
def test_browse_finds_accented_sugar_queries(repo, query):
    """Cotizaciones /api/catalog usa browse(); debe hallar Azúcar… como /hoy/$text."""
    repo.collection.insert_many(
        [
            {
                "store": "alvi",
                "product_id": "az1",
                "name": "Azúcar granulada Iansa, 400 g",
                "brand": "Iansa",
                "price": 890,
                "updated_at": "2026-10-01T12:00:00Z",
            },
            {
                "store": "tottus",
                "product_id": "az2",
                "name": "Azúcar Granulada Iansa 900 g",
                "brand": "IANSA",
                "price": 990,
                "updated_at": "2026-10-02T12:00:00Z",
            },
            {
                "store": "lider",
                "product_id": "other",
                "name": "Café molido Juan Valdez",
                "brand": "Juan Valdez",
                "price": 4500,
                "updated_at": "2026-10-03T12:00:00Z",
            },
        ]
    )
    found = repo.browse(text=query, size=12, sort="updated")
    names = {str(item.get("name") or "") for item in found["items"]}
    assert found["total"] >= 1
    assert any("Azúcar" in name or "azúcar" in name.casefold() for name in names)
    assert all("Café" not in name for name in names)


def test_explore_categories_endpoint_and_catalog_default(monkeypatch, repo):
    repo.collection.insert_one(
        {"store": "falabella", "product_id": "1", "name": "TV", "catalog_category": "Tecnología", "price": 1000}
    )

    def _repo():
        return repo

    monkeypatch.setattr("retail.web.insights_api.connect_repo", _repo)
    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: None)
    monkeypatch.setattr("retail.web.deps.connect_repo", _repo)
    # TestClient closes the repo; avoid dropping the fixture DB mid-suite.
    monkeypatch.setattr(repo, "close", lambda: None)
    client = TestClient(app)
    explore = client.get("/api/explore-categories")
    assert explore.status_code == 200
    body = explore.json()
    assert body["categories"]
    assert body.get("include_counts") is False
    for item in body["categories"]:
        assert "count" not in item
        assert item.get("icon")
        assert item.get("value")
        assert item.get("label")

    # Sin sesión admin, el flag no filtra counts.
    flagged = client.get("/api/explore-categories?include_counts=1")
    assert flagged.status_code == 200
    assert flagged.json().get("include_counts") is False
    assert all("count" not in item for item in flagged.json()["categories"])

    catalog = client.get("/api/catalog?size=1")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload.get("include_counts") is False
    for bucket in (payload.get("facets") or {}).values():
        for item in bucket or []:
            assert "count" not in item
