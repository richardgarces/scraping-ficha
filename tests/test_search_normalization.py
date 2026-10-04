from uuid import uuid4

import pytest

from retail.models import Product
from retail.mongo import ProductRepository, stable_product_id


def offer(product_id: str = "sku-1", *, price: int = 9990) -> dict:
    return Product(
        product_id=product_id,
        sku_id=product_id,
        name="Producto de prueba",
        store="falabella",
        price=price,
        url=f"https://example.test/product/{product_id}",
    ).to_dict(flatten_specs=False)


def groups(item: dict) -> list[dict]:
    return [{
        "compare_code": "producto-prueba",
        "name": "Producto de prueba",
        "lowest_price": item["price"],
        "lowest_stores": [item["store"]],
        "comparable": False,
        "offers": [item],
    }]


def test_stable_product_id_prefers_external_id_and_has_url_fallback():
    assert stable_product_id({"product_id": " external-1 ", "url": "https://x/a?track=1"}) == "external-1"
    first = stable_product_id({"url": "HTTPS://Example.test/a/?utm=x"})
    second = stable_product_id({"url": "https://example.test/a"})
    assert first.startswith("url:")
    assert first == second


@pytest.fixture
def repo(mongo_uri):
    repository = ProductRepository(mongo_uri, database=f"test_search_normalization_{uuid4().hex}")
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_persist_search_keeps_one_product_and_stores_only_relations(repo):
    first = repo.persist_search(" Té LED ", groups(offer()), source="both", store_errors=[])
    second = repo.persist_search("te led", groups(offer(price=8990)), source="both", store_errors=[])

    assert repo.collection.count_documents({}) == 1
    assert repo.searches.count_documents({}) == 2
    assert repo.search_results.count_documents({}) == 2
    saved = repo.searches.find_one({"_id": repo.searches.find_one(sort=[("_id", 1)])["_id"]})
    assert saved["query_normalized"] == "te led"
    assert saved["relation_status"] == "complete"
    assert "groups" not in saved
    assert "cheapest" not in saved

    detail = repo.search_with_results(first["search_id"])
    assert detail is not None
    assert detail["results"][0]["product"]["product_id"] == "sku-1"
    assert detail["results"][0]["position"] == 0
    assert second["upserted"] == 0
