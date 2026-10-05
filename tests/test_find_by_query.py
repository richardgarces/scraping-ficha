"""Tests de find_by_query: mismos hits de fixture, sin payload pesado."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.mongo import ProductRepository, SEARCH_FIND_PROJECTION


@pytest.fixture
def repo(mongo_uri):
    repository = ProductRepository(mongo_uri, database=f"test_find_by_query_{uuid4().hex}")
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def _doc(**overrides):
    base = {
        "store": "falabella",
        "product_id": "p1",
        "sku_id": "sku1",
        "name": "Leche Entera 1L",
        "brand": "Soprole",
        "price": 1190,
        "url": "https://example.test/p1",
        "updated_at": datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        "last_search_query": "leche",
        "thumbnail": {"data": "x" * 5000, "mime": "image/jpeg"},
        "price_history": [{"price": 1000, "scraped_at": "2026-01-01"}] * 40,
    }
    base.update(overrides)
    return base


def test_find_by_query_uses_projection_and_exact_last_search(repo):
    repo.collection.insert_many([
        _doc(product_id="a", sku_id="a", name="Leche Entera", last_search_query="leche"),
        _doc(
            product_id="b",
            sku_id="b",
            name="Queso Gouda",
            last_search_query="queso",
            updated_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
        ),
        _doc(
            store="lider",
            product_id="c",
            sku_id="c",
            name="Yogurt Light",
            last_search_query="yogurt",
        ),
    ])

    rows = repo.find_by_query("leche", limit=50)
    assert [row["product_id"] for row in rows] == ["a"]
    assert "thumbnail" not in rows[0]
    assert "price_history" not in rows[0]
    assert rows[0]["name"] == "Leche Entera"


def test_find_by_query_text_index_finds_by_name(repo):
    repo.collection.insert_many([
        _doc(product_id="tv1", sku_id="tv1", name="Smart TV 55 pulgadas Samsung", last_search_query="otros"),
        _doc(product_id="tv2", sku_id="tv2", name="Soundbar 2.1", last_search_query="otros"),
        _doc(product_id="leche1", sku_id="leche1", name="Leche Descremada", last_search_query="otros"),
    ])

    rows = repo.find_by_query("smart tv 55", limit=50)
    ids = {row["product_id"] for row in rows}
    assert "tv1" in ids
    assert "leche1" not in ids


def test_find_by_query_exact_product_id(repo):
    repo.collection.insert_one(
        _doc(product_id="ABC-999", sku_id="SKU-999", name="Producto X", last_search_query="nada")
    )
    rows = repo.find_by_query("ABC-999", limit=10)
    assert len(rows) == 1
    assert rows[0]["product_id"] == "ABC-999"


def test_find_by_query_regex_fallback_when_no_indexed_hit(repo):
    # Sin coincidencia exacta ni tokens de texto útiles: el substring en brand
    # solo aparece vía fallback regex (p.ej. fragmento raro).
    repo.collection.insert_one(
        _doc(
            product_id="z1",
            sku_id="z1",
            name="Artículo genérico",
            brand="XxQwertyZz",
            last_search_query="otro",
        )
    )
    rows = repo.find_by_query("qwerty", limit=10)
    assert [row["product_id"] for row in rows] == ["z1"]


def test_store_product_filter_batches_by_store():
    filt = ProductRepository._store_product_filter([
        ("falabella", "1"),
        ("falabella", "2"),
        ("lider", "9"),
    ])
    assert filt == {
        "$or": [
            {"store": "falabella", "product_id": {"$in": ["1", "2"]}},
            {"store": "lider", "product_id": {"$in": ["9"]}},
        ]
    }
    single = ProductRepository._store_product_filter([("falabella", "1"), ("falabella", "2")])
    assert single == {"store": "falabella", "product_id": {"$in": ["1", "2"]}}


def test_search_find_projection_excludes_heavy_fields():
    assert SEARCH_FIND_PROJECTION["thumbnail"] == 0
    assert SEARCH_FIND_PROJECTION["price_history"] == 0


def test_histories_and_thumbs_use_batched_filter(repo):
    repo.collection.insert_many([
        _doc(product_id="1", sku_id="1", thumbnail={"data": "aa", "mime": "image/jpeg"}),
        _doc(store="lider", product_id="2", sku_id="2", thumbnail={"data": "bb", "mime": "image/jpeg"}),
        _doc(product_id="3", sku_id="3"),  # sin thumbnail.data
    ])
    # Quitar thumbnail.data del tercero
    repo.collection.update_one({"product_id": "3"}, {"$unset": {"thumbnail": ""}})

    hist = repo.histories([("falabella", "1"), ("lider", "2"), ("falabella", "3")])
    assert set(hist) == {("falabella", "1"), ("lider", "2"), ("falabella", "3")}
    assert len(hist[("falabella", "1")]) == 40

    flags = repo.thumb_flags([("falabella", "1"), ("lider", "2"), ("falabella", "3")])
    assert flags == {("falabella", "1"), ("lider", "2")}
