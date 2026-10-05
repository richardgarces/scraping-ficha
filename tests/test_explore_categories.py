"""Explora rápido / facetas de catálogo sin counts."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from retail.mongo import ProductRepository
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


def test_explore_categories_payload_has_no_counts(repo):
    repo.collection.insert_one(
        {"store": "falabella", "product_id": "1", "name": "TV", "catalog_category": "Tecnología", "price": 1000}
    )
    rows = repo.explore_categories(limit=10)
    assert rows == [{"value": "Tecnología", "label": "Tecnología"}]


def test_explore_categories_endpoint_and_catalog_default(monkeypatch, repo):
    repo.collection.insert_one(
        {"store": "falabella", "product_id": "1", "name": "TV", "catalog_category": "Tecnología", "price": 1000}
    )

    def _repo():
        return repo

    monkeypatch.setattr("retail.web.insights_api.connect_repo", _repo)
    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: None)
    # TestClient closes the repo; avoid dropping the fixture DB mid-suite.
    monkeypatch.setattr(repo, "close", lambda: None)
    client = TestClient(app)
    explore = client.get("/api/explore-categories")
    assert explore.status_code == 200
    body = explore.json()
    assert body["categories"]
    assert all("count" not in item for item in body["categories"])

    catalog = client.get("/api/catalog?size=1")
    assert catalog.status_code == 200
    payload = catalog.json()
    assert payload.get("include_counts") is False
    for bucket in (payload.get("facets") or {}).values():
        for item in bucket or []:
            assert "count" not in item
