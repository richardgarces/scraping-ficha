import threading
import time

from retail.models import Product
from retail.search import iter_search_events, request_search_cancel


def _mute(monkeypatch) -> None:
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.STORE_WORKERS", 1)


def _tv(store: str) -> Product:
    return Product(
        product_id="tv1",
        sku_id="tv1",
        name="Smart TV 50",
        store=store,
        price=299990,
    )


def test_cancel_returns_partial_and_skips_remaining_stores(monkeypatch):
    _mute(monkeypatch)
    stored = []
    launched = []
    started: list[str] = []

    def scrape(store_id, query, **kwargs):
        started.append(store_id)
        if store_id == "falabella":
            return [_tv("falabella")], None
        time.sleep(3)
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: stored.append(True))
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda job: launched.append(job))
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: True)

    cancel = threading.Event()
    events = []
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=["falabella", "lider", "paris"],
        persist=False,
        delay=0,
        timeout=1,
        cancel=cancel,
    ):
        events.append(event)
        if event.get("type") == "snapshot":
            cancel.set()

    done = [item for item in events if item.get("type") == "done"][-1]["result"]
    progress = {item["id"]: item["state"] for item in done.get("progress") or []}
    assert done["cancelled"] is True
    assert "Búsqueda detenida" in done["stopped_label"]
    assert stored == []
    assert launched == []
    assert "falabella" in started
    assert "paris" not in started
    assert progress.get("paris") == "skip"
    assert progress.get("lider") == "skip"


def test_in_flight_stores_are_marked_running(monkeypatch):
    _mute(monkeypatch)
    gate = threading.Event()
    release = threading.Event()
    monkeypatch.setattr("retail.search.STORE_WORKERS", 2)

    def scrape(store_id, query, **kwargs):
        gate.set()
        release.wait(timeout=2)
        return [], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    cancel = threading.Event()
    seen_running = []
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=["lider", "paris", "falabella"],
        persist=False,
        delay=0,
        timeout=1,
        cancel=cancel,
    ):
        progress = event.get("progress") or (event.get("result") or {}).get("progress") or []
        running = [item["id"] for item in progress if item.get("state") == "running"]
        if running:
            seen_running.append(running)
            cancel.set()
            release.set()
    assert seen_running
    assert len(seen_running[0]) >= 1
    assert set(seen_running[0]) <= {"lider", "paris", "falabella"}


def test_cache_hit_ignores_cancel(monkeypatch):
    cached = {
        "query": "tv",
        "offer_count": 1,
        "rows": [{"name": "TV LG", "price": 1}],
        "progress": [{"id": "falabella", "state": "ok", "count": 1}],
        "cache": {"hit": "result"},
    }
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: cached)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)
    cancel = threading.Event()
    cancel.set()
    events = list(iter_search_events("tv", source="scrape", stores=["falabella"], persist=False, cancel=cancel))
    assert [item["type"] for item in events] == ["start", "done"]
    assert events[-1]["result"]["rows"][0]["name"] == "TV LG"
    assert events[-1]["result"].get("cancelled") is False


def test_request_cancel_sets_event():
    from retail.search import drop_search_cancel, new_search_cancel

    ident, event = new_search_cancel("testdetener01")
    try:
        assert event.is_set() is False
        assert request_search_cancel(ident) is True
        assert event.is_set() is True
    finally:
        drop_search_cancel(ident)
