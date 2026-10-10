from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from bson import ObjectId
import pytest

from retail.batch.group_scope import GroupBatchBusy
from retail.mongo import ProductRepository


@pytest.fixture
def group_repo(mongo_uri):
    repo = ProductRepository(mongo_uri, database=f"test_group_start_{uuid4().hex}")
    try:
        yield repo
    finally:
        repo.client.drop_database(repo.db.name)
        repo.close()


def reservation(group="retail", phase="starting"):
    return {
        "grupo": group, "scope": "grupo", "phase": phase,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }


@pytest.mark.parametrize("phase", ["starting", "products", "paused"])
def test_active_group_cannot_be_started_twice(group_repo, phase):
    first = group_repo.start_batch_run(reservation(phase=phase))
    with pytest.raises(GroupBatchBusy):
        group_repo.start_batch_run(reservation())
    assert group_repo.batch_runs.count_documents({}) == 1
    group_repo.finish_batch_run(first)
    assert group_repo.start_batch_run(reservation()) != first


def test_simultaneous_web_and_cron_clients_reserve_only_once(group_repo, mongo_uri):
    other = ProductRepository(mongo_uri, database=group_repo.db.name)

    def start(index):
        repo = group_repo if index % 2 else other
        try:
            return repo.start_batch_run(reservation())
        except GroupBatchBusy:
            return None

    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(start, range(16)))
        assert sum(result is not None for result in results) == 1
        assert group_repo.batch_runs.count_documents({"status": "running"}) == 1
        assert group_repo.app_settings.count_documents({"_id": "batch_start:retail"}) == 0
        assert group_repo.start_batch_run(reservation("farmacias"))
    finally:
        other.close()


def test_legacy_group_run_is_also_protected(group_repo):
    group_repo.batch_runs.insert_one({"grupo": "retail", "status": "running"})
    with pytest.raises(GroupBatchBusy):
        group_repo.start_batch_run(reservation())


def test_reservation_can_only_be_activated_for_its_group_once(group_repo):
    run_id = group_repo.start_batch_run(reservation())
    with pytest.raises(GroupBatchBusy):
        group_repo.activate_group_batch_run(run_id, "farmacias", {"phase": "index"})
    group_repo.activate_group_batch_run(run_id, "retail", {"phase": "index", "items": 10})
    with pytest.raises(GroupBatchBusy):
        group_repo.activate_group_batch_run(run_id, "retail", {"phase": "index"})
    assert group_repo.batch_runs.count_documents({}) == 1
    assert group_repo.batch_runs.find_one({"_id": ObjectId(run_id)})["items"] == 10


def test_expired_start_lock_recovers_without_removing_another_owner(group_repo):
    lock = {"_id": "batch_start:retail", "token": "other", "expires_at": datetime.now(timezone.utc) + timedelta(minutes=1)}
    group_repo.app_settings.insert_one(lock)
    with pytest.raises(GroupBatchBusy):
        group_repo.start_batch_run(reservation())
    assert group_repo.app_settings.find_one({"_id": lock["_id"]})["token"] == "other"
    group_repo.app_settings.update_one({"_id": lock["_id"]}, {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}})
    assert group_repo.start_batch_run(reservation())


def test_runner_finishes_the_reserved_run_without_inserting_another(group_repo, mongo_uri, monkeypatch):
    from retail.batch import runner

    run_id = group_repo.start_batch_run(reservation())
    monkeypatch.setattr("retail.search.connect_repo", lambda: ProductRepository(mongo_uri, database=group_repo.db.name))
    monkeypatch.setattr(runner, "load_catalog", lambda path: {"title": "Test", "products": [{"id": "tv", "query": "tv"}]})
    monkeypatch.setattr(runner, "load_rules", lambda path: {"channels": ["log"]})
    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {})
    monkeypatch.setattr("retail.store_categories.stores_for_group", lambda group: ["falabella"])
    monkeypatch.setattr("retail.store_categories.filter_products_for_group", lambda products, group: products)
    monkeypatch.setenv("ADAPTIVE_SCRAPING", "0")
    monkeypatch.setenv("BATCH_REFRESH_INDEX", "0")

    def no_search(*args, **kwargs):
        pytest.fail("La prueba de arranque no debe consultar tiendas")

    monkeypatch.setattr(runner, "search_products", no_search)
    summary = runner.run_batch(grupo="retail", batch_run_id=run_id, limit=0, pause=0)
    assert summary["batch_run_id"] == run_id
    assert group_repo.batch_runs.count_documents({}) == 1
    assert group_repo.batch_runs.find_one({"_id": ObjectId(run_id)})["status"] == "done"
