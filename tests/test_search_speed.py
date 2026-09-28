import threading
import time

from retail.models import Product
from retail.search import (
    READY_EARLY_OFFERS,
    READY_EARLY_SECONDS,
    SEARCH_TIMEOUT,
    iter_search_events,
    mark_thumbs,
    search_is_ready,
    search_products,
    wait_progress,
    wait_set_done,
)


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
    monkeypatch.setattr("retail.search.STORE_WORKERS", 2)


def _tv(store: str) -> Product:
    return Product(
        product_id="tv1",
        sku_id="tv1",
        name="Smart TV 50",
        store=store,
        price=299990,
    )


def test_search_timeout_default_is_12():
    assert SEARCH_TIMEOUT == 12.0


def test_overlay_ready_at_80_percent_wait_set():
    progress = [{"id": f"s{i}", "state": "ok" if i < 8 else "running"} for i in range(10)]
    assert search_is_ready(progress, 0) is True
    early = [{"id": f"s{i}", "state": "ok" if i < 2 else "pending"} for i in range(10)]
    assert search_is_ready(early, 0) is False


def test_overlay_ready_with_offer_at_50_percent():
    progress = [{"id": f"s{i}", "state": "ok" if i < 5 else "pending"} for i in range(10)]
    assert search_is_ready(progress, 1) is True
    assert search_is_ready(progress, 0) is False


def test_movistar_does_not_block_wait_set():
    progress = [
        {"id": "falabella", "state": "ok"},
        {"id": "movistar", "state": "running"},
    ]
    assert wait_set_done(progress) is True
    assert search_is_ready(progress, 1) is True


def test_timeout_failures_are_not_in_retry_wave(monkeypatch):
    _mute(monkeypatch)
    calls: list[str] = []

    def scrape(store_id, query, **kwargs):
        calls.append(store_id)
        if store_id == "lider":
            return [], "timeout (12s): Read timed out"
        if store_id == "paris":
            return [], "HTTP 500 en Paris"
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    list(
        iter_search_events(
            "tv",
            source="scrape",
            stores=["falabella", "lider", "paris"],
            persist=False,
            delay=0,
            timeout=1,
        )
    )
    assert calls.count("lider") == 1
    assert calls.count("paris") == 2
    assert calls.count("falabella") == 1


def test_done_does_not_wait_for_movistar(monkeypatch):
    _mute(monkeypatch)
    release = threading.Event()

    def scrape(store_id, query, **kwargs):
        if store_id == "movistar":
            release.wait(timeout=3)
            return [_tv("movistar")], None
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    events = []
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=["falabella", "movistar"],
        persist=False,
        delay=0,
        timeout=1,
    ):
        events.append(event)
        if event.get("type") == "done":
            progress = {item["id"]: item["state"] for item in event["result"]["progress"]}
            assert progress.get("falabella") == "ok"
            assert progress.get("movistar") in {"pending", "running"}
            release.set()

    types = [item["type"] for item in events]
    assert "done" in types
    done_at = types.index("done")
    later = events[done_at:]
    assert any(
        (item.get("result") or {}).get("progress")
        and any(
            row.get("id") == "movistar" and row.get("state") == "ok"
            for row in (item.get("result") or {}).get("progress") or []
        )
        for item in later
    )


def test_search_products_returns_before_movistar(monkeypatch):
    _mute(monkeypatch)
    release = threading.Event()

    def scrape(store_id, query, **kwargs):
        if store_id == "movistar":
            release.wait(timeout=3)
            return [_tv("movistar")], None
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    result = search_products(
        "tv",
        source="scrape",
        stores=["falabella", "movistar"],
        persist=False,
        delay=0,
        timeout=1,
    )
    try:
        progress = {item["id"]: item["state"] for item in result["progress"]}
        assert progress.get("falabella") == "ok"
        assert progress.get("movistar") in {"pending", "running"}
    finally:
        release.set()


def test_batch_mode_waits_for_optional_store(monkeypatch):
    _mute(monkeypatch)

    def scrape(store_id, query, **kwargs):
        if store_id == "movistar":
            time.sleep(0.02)
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    result = search_products(
        "tv",
        source="scrape",
        stores=["movistar"],
        persist=False,
        delay=0,
        timeout=1,
        fresh=True,
        background_side_effects=False,
        wait_for_all=True,
    )
    progress = {item["id"]: item["state"] for item in result["progress"]}
    assert progress == {"movistar": "ok"}
    assert result["offer_count"] == 1


WAIT_STORES = [
    "falabella",
    "paris",
    "ripley",
    "lider",
    "tottus",
    "unimarc",
    "alvi",
    "ahumada",
    "cruzverde",
    "sodimac",
]


def _tvs(store: str, count: int) -> list[Product]:
    return [
        Product(
            product_id=f"{store}-{index}",
            sku_id=f"{store}-{index}",
            name=f"Smart TV {40 + index} pulgadas {index}",
            store=store,
            price=200000 + index * 1000,
            image_url=f"https://img.example/{store}/{index}.jpg",
        )
        for index in range(count)
    ]


def test_overlay_ready_after_5s_with_10_offers():
    progress = [{"id": f"s{i}", "state": "ok" if i < 1 else "pending"} for i in range(10)]
    assert READY_EARLY_SECONDS == 5.0
    assert READY_EARLY_OFFERS == 10
    assert search_is_ready(progress, 10, elapsed=5) is True
    assert search_is_ready(progress, 10, elapsed=6) is True
    assert search_is_ready(progress, 9, elapsed=5) is False
    assert search_is_ready(progress, 10, elapsed=3) is False


def test_optional_wait_set_excludes_movistar_and_salcobrand():
    progress = [
        {"id": "falabella", "state": "ok"},
        {"id": "movistar", "state": "running"},
        {"id": "salcobrand", "state": "running"},
    ]
    waiting = [item["id"] for item in wait_progress(progress)]
    assert waiting == ["falabella"]
    assert wait_set_done(progress) is True
    assert search_is_ready(progress, 1) is True


def test_done_does_not_wait_for_salcobrand(monkeypatch):
    _mute(monkeypatch)
    release = threading.Event()

    def scrape(store_id, query, **kwargs):
        if store_id == "salcobrand":
            release.wait(timeout=3)
            return [_tv("salcobrand")], None
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    events = []
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=["falabella", "salcobrand"],
        persist=False,
        delay=0,
        timeout=1,
    ):
        events.append(event)
        if event.get("type") == "done":
            progress = {item["id"]: item["state"] for item in event["result"]["progress"]}
            assert progress.get("falabella") == "ok"
            assert progress.get("salcobrand") in {"pending", "running"}
            release.set()

    types = [item["type"] for item in events]
    assert "done" in types
    done_at = types.index("done")
    assert any(
        row.get("id") == "salcobrand" and row.get("state") == "ok"
        for item in events[done_at:]
        for row in (item.get("result") or {}).get("progress") or []
    )


def test_overlay_ready_event_after_early_threshold(monkeypatch):
    _mute(monkeypatch)
    monkeypatch.setattr("retail.search.READY_EARLY_SECONDS", 0.25)
    monkeypatch.setattr("retail.search.STORE_WORKERS", 2)
    release = threading.Event()

    def scrape(store_id, query, **kwargs):
        if store_id == "falabella":
            return _tvs("falabella", 10), None
        release.wait(timeout=4)
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    started = time.monotonic()
    ready_at = None
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=WAIT_STORES,
        persist=False,
        delay=0,
        timeout=1,
    ):
        if event.get("type") == "ready" and ready_at is None:
            ready_at = time.monotonic() - started
            offers = int((event.get("result") or {}).get("offer_count") or 0)
            assert offers >= 10
            release.set()
    assert ready_at is not None
    assert ready_at >= 0.2


def test_overlay_stays_if_fewer_than_10_at_threshold(monkeypatch):
    _mute(monkeypatch)
    monkeypatch.setattr("retail.search.READY_EARLY_SECONDS", 0.2)
    monkeypatch.setattr("retail.search.STORE_WORKERS", 2)
    release = threading.Event()
    cancel = threading.Event()

    def scrape(store_id, query, **kwargs):
        if store_id == "falabella":
            return _tvs("falabella", 9), None
        release.wait(timeout=4)
        return [_tv(store_id)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    types = []
    started = time.monotonic()
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=WAIT_STORES,
        persist=False,
        delay=0,
        timeout=1,
        cancel=cancel,
    ):
        types.append(event.get("type"))
        if time.monotonic() - started >= 0.45:
            cancel.set()
    release.set()
    assert "ready" not in types


def test_mark_thumbs_patches_existing_payload():
    result = {
        "rows": [{"store": "falabella", "product_id": "1", "has_thumb": False, "name": "TV"}],
        "groups": [{"offers": [{"store": "falabella", "product_id": "1", "has_thumb": False}]}],
    }
    patched = mark_thumbs(result, [{"store": "falabella", "product_id": "1"}])
    assert patched == [{"store": "falabella", "product_id": "1"}]
    assert result["rows"][0]["has_thumb"] is True
    assert result["groups"][0]["offers"][0]["has_thumb"] is True


class _FakeThumbRepo:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], dict] = {}

    def close(self) -> None:
        return None

    def find_by_query(self, query: str) -> list:
        return []

    def histories(self, keys):
        return {}

    def thumb_flags(self, keys):
        return {key for key in keys if key in self.saved}

    def missing_thumbnails(self, wanted):
        return [(key, url) for key, url in wanted if key not in self.saved]

    def save_thumbnails(self, items):
        self.saved.update(items)
        return len(items)

    def persist_search(self, *args, **kwargs):
        return None


def test_thumbs_stream_after_first_snapshot(monkeypatch):
    _mute(monkeypatch)
    repo = _FakeThumbRepo()
    monkeypatch.setattr("retail.search.connect_repo", lambda: repo)
    monkeypatch.setattr(
        "retail.thumbs.build_thumbnail",
        lambda url: {"data": "eA==", "mime": "image/jpeg", "source_url": url, "bytes": 1, "width": 1, "height": 1},
    )

    def scrape(store_id, query, **kwargs):
        return _tvs(store_id, 1), None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    first_has_thumb = None
    thumbs_event = None
    saw_done = False
    for event in iter_search_events(
        "tv",
        source="scrape",
        stores=["falabella"],
        persist=False,
        delay=0,
        timeout=1,
    ):
        rows = (event.get("result") or {}).get("rows") or []
        if first_has_thumb is None and rows:
            first_has_thumb = bool(rows[0].get("has_thumb"))
        if event.get("type") == "thumbs":
            thumbs_event = event
        if event.get("type") == "done":
            saw_done = True
    assert first_has_thumb is False
    assert thumbs_event and thumbs_event["thumbs"]
    assert thumbs_event["thumbs"][0]["store"] == "falabella"
    assert saw_done
