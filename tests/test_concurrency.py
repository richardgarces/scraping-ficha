"""Límites de concurrencia: fallback in-process y cliente Redis falso."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import retail.concurrency as concurrency


class FakeRedis:
    """Subset mínimo para eval de acquire/release (ZSET + Lua emulado)."""

    def __init__(self) -> None:
        self._zsets: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    def ping(self) -> bool:
        return True

    def eval(self, script: str, numkeys: int, *args):
        keys = list(args[:numkeys])
        argv = list(args[numkeys:])
        key = keys[0]
        with self._lock:
            zset = self._zsets.setdefault(key, {})
            if "ZADD" in script and "ZCARD" in script:
                token, limit, now, expire_at = argv[0], int(argv[1]), float(argv[2]), float(argv[3])
                for member, score in list(zset.items()):
                    if score <= now:
                        del zset[member]
                if len(zset) < limit:
                    zset[token] = expire_at
                    return 1
                return 0
            if "ZREM" in script:
                token = argv[0]
                return 1 if zset.pop(token, None) is not None else 0
            raise AssertionError(f"script no soportado: {script[:40]}")


@pytest.fixture(autouse=True)
def _reset_concurrency(monkeypatch):
    concurrency.reset_backend_for_tests()
    monkeypatch.setenv("RETAIL_SCRAPE_CONCURRENCY", "2")
    monkeypatch.setenv("RETAIL_CHROMIUM_CONCURRENCY", "1")
    concurrency.SCRAPE_LIMIT = 2
    concurrency.CHROMIUM_LIMIT = 1
    yield
    concurrency.reset_backend_for_tests()


def test_in_process_scrape_slot_caps_parallel(monkeypatch):
    monkeypatch.setattr(concurrency, "_connect_redis", lambda: None)
    concurrency.reset_backend_for_tests()

    active = 0
    peak = 0
    lock = threading.Lock()

    def work(_i: int) -> None:
        nonlocal active, peak
        with concurrency.scrape_slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, range(6)))

    assert peak <= 2
    assert peak >= 1


def test_scrape_slot_releases_on_exception(monkeypatch):
    monkeypatch.setattr(concurrency, "_connect_redis", lambda: None)
    concurrency.reset_backend_for_tests()

    with pytest.raises(RuntimeError):
        with concurrency.scrape_slot():
            raise RuntimeError("boom")

    # Tras el fallo debe haber slots libres otra vez.
    with concurrency.scrape_slot(timeout=0.5):
        pass


def test_chromium_slot_takes_scrape_and_chromium(monkeypatch):
    monkeypatch.setattr(concurrency, "_connect_redis", lambda: None)
    concurrency.reset_backend_for_tests()

    with concurrency.chromium_slot(timeout=0.5) as (scrape_token, chrome_token):
        assert scrape_token
        assert chrome_token
        # Con CHROMIUM_LIMIT=1, un segundo chromium no entra.
        with pytest.raises(concurrency.ConcurrencyTimeout):
            with concurrency.chromium_slot(timeout=0.15):
                pass


def test_fake_redis_shared_limit(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(concurrency, "_connect_redis", lambda: fake)
    concurrency.reset_backend_for_tests()

    tokens = []
    tokens.append(concurrency.acquire("scrape", 2, timeout=0.5))
    tokens.append(concurrency.acquire("scrape", 2, timeout=0.5))
    with pytest.raises(concurrency.ConcurrencyTimeout):
        concurrency.acquire("scrape", 2, timeout=0.15)

    concurrency.release("scrape", tokens.pop())
    tokens.append(concurrency.acquire("scrape", 2, timeout=0.5))
    for token in tokens:
        concurrency.release("scrape", token)


def test_helpers_respect_env_caps(monkeypatch):
    monkeypatch.setenv("BATCH_PRODUCT_WORKERS", "99")
    monkeypatch.setenv("RETAIL_OPTIONAL_STORE_WORKERS", "2")
    monkeypatch.setenv("RETAIL_THUMB_WORKERS", "2")
    assert concurrency.batch_product_workers() == 4
    assert concurrency.optional_store_workers(5) == 2
    assert concurrency.optional_store_workers(1) == 1
    assert concurrency.thumb_workers() == 2


def test_scrape_store_uses_scrape_slot(monkeypatch):
    from retail import search

    held: list[str] = []

    class _Slot:
        def __enter__(self):
            held.append("in")
            return "tok"

        def __exit__(self, *args):
            held.append("out")
            return False

    monkeypatch.setattr(search, "scrape_slot", lambda: _Slot())
    monkeypatch.setattr(
        search,
        "get_client",
        lambda store_id, **kw: _FakeClient(),
    )

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def scrape(self, query, max_pages=1, max_items=5):
            return []

    products, error = search.scrape_store("lider", "tv", max_items=1, delay=0, timeout=5)
    assert products == []
    assert error is None
    assert held == ["in", "out"]
