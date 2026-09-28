from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from retail.models import Product
from retail.search_cache import (
    SearchCache,
    canonical_query,
    chile_today,
    compatible_queries,
    query_digest,
    result_redis_key,
    store_redis_key,
    ttl_until_midnight,
    typo_equivalent,
)


class MemoryRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttls[key] = ttl

    def ping(self) -> bool:
        return True


def _phone(store: str, sku: str) -> Product:
    return Product(product_id=sku, sku_id=sku, name="Galaxy S25 512GB", store=store, price=800000)


def test_canonical_query_folds_noise():
    assert canonical_query("  Galaxy   S25  512GB ") == "galaxy s25 512gb"


def test_cache_query_keeps_short_models_and_purchase_qualifiers():
    assert query_digest("iphone 5") != query_digest("iphone 6")
    assert query_digest("notebook gamer") != query_digest("notebook")
    assert query_digest("sal sin sodio") != query_digest("sal con sodio")
    assert query_digest("sal 1 kg") != query_digest("sal 2 kg")


def test_compatible_queries_allows_near_phrasing():
    assert compatible_queries("galaxy s25 512gb", "celular galaxy s25 512gb")


def test_compatible_queries_rejects_capacity_and_inches():
    assert not compatible_queries("galaxy s25 512gb", "galaxy s25 256gb")
    assert not compatible_queries("tv 50 pulgadas", "tv 55 pulgadas")


def test_ttl_lasts_until_chile_midnight():
    now = datetime(2026, 9, 14, 22, 0, tzinfo=ZoneInfo("America/Santiago"))
    assert chile_today(now) == "2026-09-14"
    assert ttl_until_midnight(now) == 2 * 3600


def test_store_cache_hits_same_query_today():
    cache = SearchCache(MemoryRedis())
    cache.store_stores(
        "galaxy s25 512gb",
        {"falabella": [_phone("falabella", "A")], "ripley": [_phone("ripley", "B")]},
        max_items=8,
    )
    found = cache.lookup_stores("galaxy s25 512gb", ["falabella", "ripley", "paris"], max_items=8)
    assert set(found) == {"falabella", "ripley"}
    assert found["falabella"]["hit"] == "exact"
    assert found["falabella"]["products"][0].product_id == "A"


def test_store_cache_requires_enough_items():
    cache = SearchCache(MemoryRedis())
    cache.store_stores("galaxy s25 512gb", {"falabella": [_phone("falabella", "A")]}, max_items=5)
    assert cache.lookup_stores("galaxy s25 512gb", ["falabella"], max_items=8) == {}
    assert "falabella" in cache.lookup_stores("galaxy s25 512gb", ["falabella"], max_items=5)


def test_store_redis_key_is_per_store_and_day():
    digest = query_digest("galaxy s25 512gb")
    assert store_redis_key("falabella", digest, "2026-09-14") != store_redis_key("ripley", digest, "2026-09-14")
    assert store_redis_key("falabella", digest, "2026-09-14") != store_redis_key("falabella", digest, "2026-09-15")


def test_result_cache_hits_same_query_until_midnight(monkeypatch):
    monkeypatch.setattr("retail.search_cache._now", lambda: datetime(2026, 9, 28, 22, tzinfo=ZoneInfo("America/Santiago")))
    redis = MemoryRedis()
    cache = SearchCache(redis)
    result = {
        "query": "tv",
        "offer_count": 1,
        "rows": [{"name": "TV LG 50", "price": 299990, "store": "lider"}],
        "groups": [{"name": "TV LG 50"}],
        "progress": [{"id": "lider", "state": "ok", "count": 1}],
    }
    cache.store_result(
        "TV",
        source="both",
        stores=["lider", "tottus"],
        max_items=8,
        price_band=True,
        result=result,
    )
    key = result_redis_key("tv", source="both", stores=["tottus", "lider"], max_items=8, price_band=True)
    assert redis.ttls[key] == 2 * 3600
    assert ":2026-09-28:result:" in key

    hit = cache.lookup_result("tv", source="both", stores=["lider", "tottus"], max_items=8, price_band=True)
    assert hit is not None
    assert hit["cache"]["hit"] == "result"
    assert hit["rows"][0]["name"] == "TV LG 50"
    assert hit["saved"] is None

    assert cache.lookup_result("tv", source="both", stores=["lider"], max_items=8, price_band=True) is None
    assert cache.lookup_result("notebook", source="both", stores=["lider", "tottus"], max_items=8, price_band=True) is None


def test_result_cache_keeps_completed_empty_search():
    cache = SearchCache(MemoryRedis())
    cache.store_result("tv", source="both", stores=["lider"], max_items=8, price_band=True, result={"rows": []})
    assert cache.lookup_result("tv", source="both", stores=["lider"], max_items=8, price_band=True)["rows"] == []


@pytest.mark.parametrize("extra", [
    {"cancelled": True}, {"store_errors": [{"store": "lider", "error": "timeout"}]},
    {"progress": [{"id": "lider", "state": "running"}]},
    {"progress": [{"id": "lider", "state": "error"}]},
    {"warnings": ["MongoDB no está disponible"]},
])
def test_incomplete_or_failed_search_is_not_reused_for_the_day(extra):
    cache = SearchCache(MemoryRedis())
    cache.store_result("tv", source="both", stores=["lider"], max_items=8, price_band=True, result={"rows": [], **extra})
    assert cache.lookup_result("tv", source="both", stores=["lider"], max_items=8, price_band=True) is None


def test_cache_does_not_cross_calendar_day_even_if_key_has_not_expired(monkeypatch):
    day = [datetime(2026, 9, 28, 23, 59, 59, tzinfo=ZoneInfo("America/Santiago"))]
    monkeypatch.setattr("retail.search_cache._now", lambda: day[0])
    redis = MemoryRedis()
    cache = SearchCache(redis)
    scope = dict(source="both", stores=["lider"], max_items=5, price_band=True)
    cache.store_result("sal", result={"rows": [{"name": "Sal"}]}, **scope)
    cache.store_stores("sal", {"lider": []}, max_items=5)
    assert all(ttl == 1 for ttl in redis.ttls.values())
    assert cache.lookup_result("sal", **scope) is not None
    day[0] = datetime(2026, 9, 29, tzinfo=ZoneInfo("America/Santiago"))
    assert cache.lookup_result("sal", **scope) is None
    assert cache.lookup_stores("sal", ["lider"], max_items=5) == {}


def test_cache_read_crossing_midnight_rejects_yesterdays_result(monkeypatch):
    day = [datetime(2026, 9, 28, 23, 59, 59, tzinfo=ZoneInfo("America/Santiago"))]
    monkeypatch.setattr("retail.search_cache._now", lambda: day[0])
    redis = MemoryRedis()
    cache = SearchCache(redis)
    scope = dict(source="scrape", stores=["lider"], max_items=5, price_band=True)
    cache.store_result("sal", result={"rows": []}, **scope)
    read = redis.get

    def cross_midnight(key):
        day[0] = datetime(2026, 9, 29, tzinfo=ZoneInfo("America/Santiago"))
        return read(key)

    monkeypatch.setattr(redis, "get", cross_midnight)
    assert cache.lookup_result("sal", **scope) is None


@pytest.mark.parametrize("day", [datetime(2026, 4, 4, 12), datetime(2026, 9, 6, 0)])
def test_midnight_ttl_uses_real_seconds_across_chile_dst(day):
    from datetime import timedelta

    local = day.replace(tzinfo=ZoneInfo("America/Santiago"))
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    assert ttl_until_midnight(local) == int(midnight.timestamp() - local.timestamp())


@pytest.mark.parametrize("left,right,expected", [
    ("ssal", "sal", True), ("lecche", "leche", True), ("aroz", "arroz", True),
    ("sal", "sol", False), ("sal", "cal", False), ("sal", "sal de fruta", False),
    ("sal marina", "sal rosada", False), ("s25", "s24", False),
    ("galaxy 512gb", "galaxy 256gb", False), ("tv 55", "tv 555", False),
    ("sal sin sodio", "sal", False),
])
def test_query_correction_does_not_change_product_or_specs(left, right, expected):
    assert typo_equivalent(left, right) is expected


def test_qdrant_corrects_ssal_to_todays_redis_query(monkeypatch):
    from qdrant_client import QdrantClient
    from retail.qdrant_index import QdrantIndex
    from retail.search_cache import resolve_search_query

    redis = MemoryRedis()
    qdrant = QdrantIndex(QdrantClient(":memory:"))
    cache = SearchCache(redis, qdrant)
    scope = dict(source="both", stores=["lider"], max_items=5, price_band=True)
    try:
        cache.store_result("sal", result={"rows": [{"name": "Sal de mesa", "price": 1000}]}, **scope)
        monkeypatch.setattr("retail.search_cache.connect_redis", lambda: redis)
        monkeypatch.setattr("retail.qdrant_index.connect_qdrant", lambda: qdrant)
        assert resolve_search_query("ssal") == "sal"
        assert resolve_search_query("sol") == "sol"
        hit = cache.lookup_result(resolve_search_query("ssal"), **scope)
        assert hit["rows"][0]["name"] == "Sal de mesa"
        assert resolve_search_query("sal de fruta") == "sal de fruta"
    finally:
        qdrant.client.close()


def test_typo_uses_cached_result_before_routing_or_scraping(monkeypatch):
    from qdrant_client import QdrantClient
    from retail.index.products import stores_for
    from retail.qdrant_index import QdrantIndex
    from retail.registry import list_stores
    from retail.search import iter_search_events

    redis = MemoryRedis()
    qdrant = QdrantIndex(QdrantClient(":memory:"))
    selected = stores_for("sal", [store.id for store in list_stores()], client=False)
    cache = SearchCache(redis, qdrant)
    cache.store_result("sal", source="scrape", stores=selected, max_items=5, price_band=True, result={
        "query": "sal", "rows": [{"name": "Sal de mesa", "price": 1000, "store": "lider"}],
        "offer_count": 1, "progress": [{"id": store, "state": "ok"} for store in selected],
    })
    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: redis)
    monkeypatch.setattr("retail.qdrant_index.connect_qdrant", lambda: qdrant)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.feed_search", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: True)
    monkeypatch.setattr("retail.search.release_unique_sweep", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda job: pytest.fail("Un acierto de caché no consulta otras tiendas"))
    monkeypatch.setattr("retail.search.connect_repo", lambda: pytest.fail("No debe consultar Mongo ni tiendas"))
    try:
        events = list(iter_search_events("ssal", source="scrape", persist=False))
        assert [event["type"] for event in events] == ["start", "done"]
        assert events[-1]["result"]["query"] == "sal"
        assert events[-1]["result"]["requested_query"] == "ssal"
        assert events[-1]["result"]["stores"] == selected
    finally:
        qdrant.client.close()


def test_public_store_search_uses_daily_cache_and_admin_can_force_refresh():
    from retail.web.app import _search_args_for_role

    ordinary = _search_args_for_role(False, "sal", "scrape", None, 5, 0, False, False)
    assert ordinary["source"] == "both"
    assert ordinary["fresh"] is False
    forced = _search_args_for_role(True, "sal", "both", None, 5, 0, False, True)
    assert forced["fresh"] is True
    quick = _search_args_for_role(False, "sal", "both", None, 5, 0, False, False, quick=True)
    assert quick["source"] == "db"
    assert quick["recover_underfilled_db"] is False


def test_search_stream_returns_cached_result(monkeypatch):
    from retail.search import iter_search_events

    cached = {
        "query": "tv",
        "offer_count": 1,
        "rows": [{"name": "TV LG", "price": 1}],
        "progress": [{"id": "falabella", "state": "ok", "count": 1}],
        "cache": {"hit": "result"},
    }
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: cached)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    events = list(iter_search_events("tv", source="scrape", stores=["falabella"], persist=False))
    assert [item["type"] for item in events] == ["start", "done"]
    assert events[-1]["result"]["rows"][0]["name"] == "TV LG"
    assert events[0]["progress"][0]["cached"] is True
