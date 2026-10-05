from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.models import Product
from retail.mongo import ProductRepository
from retail.real_offer_worker import chile_day, chile_day_bounds, run_once


def item(store: str, product_id: str, price: int, normal: int | None) -> dict:
    return Product(
        product_id=product_id,
        sku_id=product_id,
        name="Shampoo Acme Hidratante 400 ml",
        brand="Acme",
        store=store,
        price=price,
        price_normal=normal,
        stock=5,
        url=f"https://example.test/{store}/{product_id}",
    ).to_dict(flatten_specs=False)


def grouped(*offers: dict) -> list[dict]:
    return [{
        "compare_code": "shampoo-acme-400",
        "name": "Shampoo Acme Hidratante 400 ml",
        "comparable": True,
        "offers": list(offers),
    }]


@pytest.fixture
def repo(mongo_uri):
    repository = ProductRepository(mongo_uri, database=f"test_real_worker_{uuid4().hex}")
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_chile_day_uses_local_boundary():
    assert chile_day(datetime(2026, 10, 4, 2, 30, tzinfo=timezone.utc)) == "2026-10-03"
    start, end = chile_day_bounds("2026-10-04")
    assert start < end
    assert (end - start).total_seconds() in {23 * 3600, 24 * 3600, 25 * 3600}


def test_enqueue_only_discount_dedupes_and_requeues_price_change(repo):
    discount = item("falabella", "one", 6000, 10000)
    regular = item("paris", "two", 10000, 10000)
    first = repo.persist_search("shampoo", grouped(discount, regular), source="test", store_errors=[])
    assert first["real_offer_queue"]["candidates"] == 1
    assert first["real_offer_queue"]["enqueued"] == 1

    second = repo.persist_search("shampoo", grouped(discount, regular), source="test", store_errors=[])
    assert second["real_offer_queue"]["deduplicated"] == 1
    assert repo.real_offer_jobs.count_documents({}) == 1

    changed = item("falabella", "one", 5500, 10000)
    third = repo.persist_search("shampoo", grouped(changed, regular), source="test", store_errors=[])
    assert third["real_offer_queue"]["enqueued"] == 1
    assert repo.real_offer_jobs.count_documents({}) == 2


def test_worker_marks_real_and_reales_reads_today_marker_without_recalculation(repo, monkeypatch):
    discount = item("falabella", "one", 6000, 10000)
    peer = item("paris", "two", 10000, 10000)
    repo.persist_search("shampoo", grouped(discount, peer), source="test", store_errors=[])

    metrics = run_once(repo)
    assert metrics == {"processed": 1, "real": 1, "not_real": 0, "errors": 0}
    marker = repo.daily_real_offers.find_one({})
    assert marker["is_real"] is True
    assert marker["evaluated_price"] == 6000
    assert marker["criterion_version"] == "real-offer-v2"

    monkeypatch.setattr("retail.reales.pick_real_offer", lambda *args, **kwargs: pytest.fail("recalculó"))
    found = repo.real_offers()
    assert found["total"] == 1
    assert found["items"][0]["price"] == 6000
    assert found["day"] == chile_day()

    # Si el producto cambia después de evaluarlo, no se mezcla el precio nuevo
    # con la marca vieja.
    repo.collection.update_one({"store": "falabella", "product_id": "one"}, {"$set": {"price": 5000}})
    assert repo.real_offers()["total"] == 0


def test_worker_marks_not_real_and_retries_errors(repo, monkeypatch):
    discount = item("falabella", "one", 9000, 10000)
    unrelated = item("paris", "two", 12000, 12000)
    unrelated["name"] = "Acondicionador Distinto 1 litro"
    repo.persist_search("cuidado", grouped(discount, unrelated), source="test", store_errors=[])
    metrics = run_once(repo)
    assert metrics["not_real"] == 1
    assert repo.daily_real_offers.find_one({})["is_real"] is False

    changed = item("falabella", "one", 8500, 10000)
    repo.persist_search("cuidado", grouped(changed, unrelated), source="test", store_errors=[])
    monkeypatch.setattr(
        "retail.real_offer_worker.cluster_offer_rows",
        lambda rows: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    metrics = run_once(repo)
    assert metrics["errors"] == 1
    assert repo.real_offer_jobs.find_one({"price_signature": "8500:10000"})["status"] == "retry"


def test_backfill_only_search_products_found_today_with_discount(repo):
    discount = item("falabella", "one", 6000, 10000)
    regular = item("paris", "two", 10000, 10000)
    repo.persist_search("shampoo", grouped(discount, regular), source="test", store_errors=[])
    repo.real_offer_jobs.delete_many({})

    result = repo.enqueue_today_real_offer_candidates()
    assert result["found_today"] == 2
    assert result["candidates"] == 1
    assert result["enqueued"] == 1
