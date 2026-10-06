from datetime import datetime
from zoneinfo import ZoneInfo
import re

import pytest

from retail.models import Product
from retail.search_cache import (
    SearchCache,
    canonical_query,
    chile_today,
    compatible_queries,
    load_search_cache,
    query_digest,
    result_redis_key,
    store_redis_key,
    summarize_search_cache,
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

    def ttl(self, key: str) -> int:
        if key not in self.data:
            return -2
        return int(self.ttls.get(key, -1))

    def scan_iter(self, match: str = "*", count: int = 10):
        regex = re.compile("^" + re.escape(match).replace("\\*", ".*") + "$")
        for key in list(self.data):
            if regex.match(key):
                yield key

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


def test_ttl_caps_long_days_for_fresher_search(monkeypatch):
    import retail.search_cache as cache_mod

    monkeypatch.setattr(cache_mod, "MAX_RESULT_TTL", 14400)
    noon = datetime(2026, 9, 14, 12, 0, tzinfo=ZoneInfo("America/Santiago"))
    assert ttl_until_midnight(noon) == 14400
    monkeypatch.setattr(cache_mod, "MAX_RESULT_TTL", 0)
    assert ttl_until_midnight(noon) == 12 * 3600


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


def test_result_cache_skips_empty_search():
    """Un cero del día no debe reutilizarse: tipografía/timeouts lo convertían en falso vacío."""
    from retail.search_cache import rewrite_search_query

    cache = SearchCache(MemoryRedis())
    cache.store_result(
        "tv",
        source="both",
        stores=["lider"],
        max_items=8,
        price_band=True,
        result={"rows": [], "progress": [{"id": "lider", "state": "ok", "count": 0}]},
    )
    assert cache.lookup_result("tv", source="both", stores=["lider"], max_items=8, price_band=True) is None
    assert rewrite_search_query("azúcar ianza") == "azúcar iansa"
    assert rewrite_search_query("azucar  ianza") == "azucar iansa"
    assert rewrite_search_query("azúcar granulada") == "azúcar granulada"


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
    cache.store_result("sal", result={"rows": [{"name": "Sal", "price": 500}]}, **scope)
    read = redis.get

    def cross_midnight(key):
        day[0] = datetime(2026, 9, 29, tzinfo=ZoneInfo("America/Santiago"))
        return read(key)

    monkeypatch.setattr(redis, "get", cross_midnight)
    assert cache.lookup_result("sal", **scope) is None


@pytest.mark.parametrize("day", [datetime(2026, 4, 4, 12), datetime(2026, 9, 6, 0)])
def test_midnight_ttl_uses_real_seconds_across_chile_dst(day, monkeypatch):
    from datetime import timedelta

    import retail.search_cache as cache_mod

    monkeypatch.setattr(cache_mod, "MAX_RESULT_TTL", 0)
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
        assert [event["type"] for event in events] == ["start", "done", "end"]
        assert events[1]["result"]["query"] == "sal"
        assert events[1]["result"]["requested_query"] == "ssal"
        assert events[1]["result"]["stores"] == selected
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


def test_full_search_skips_scrape_when_same_query_was_cached_today(monkeypatch):
    """Sin búsqueda rápida: si Redis ya tiene scrape de hoy, no vuelve a tiendas."""
    from retail.search import iter_search_events

    redis = MemoryRedis()
    cache = SearchCache(redis)
    cache.store_stores("clavo", {"falabella": [_phone("falabella", "C1")]}, max_items=8)
    scrape_calls: list[str] = []

    class _Repo:
        def ping(self):
            return True

        def close(self):
            return None

        def find_by_query(self, query):
            assert query == "clavo"
            return [
                Product(
                    product_id="db1",
                    sku_id="db1",
                    name="Clavo 2 pulgadas",
                    store="ripley",
                    price=990,
                ).to_dict(flatten_specs=False)
            ]

        def histories(self, keys):
            return {}

        def thumb_flags(self, keys):
            return set()

    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: redis)
    monkeypatch.setattr("retail.search.connect_repo", lambda: _Repo())
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "retail.search.scrape_store",
        lambda store_id, *args, **kwargs: scrape_calls.append(store_id) or ([], None),
    )

    events = list(
        iter_search_events(
            "clavo",
            source="both",
            stores=["falabella", "ripley", "paris"],
            max_items=8,
            persist=False,
            delay=0,
            timeout=1,
            background_side_effects=False,
            wait_for_all=True,
        )
    )
    assert scrape_calls == []
    done = next(event for event in events if event["type"] == "done")
    assert done["result"]["cache"]["hit"] in {"exact", "partial", "similar"}
    progress = {item["id"]: item["state"] for item in done["result"]["progress"]}
    assert progress == {"falabella": "skip", "ripley": "skip", "paris": "skip"}
    assert any(row["store"] == "ripley" for row in done["result"]["rows"])


def test_full_search_scrapes_when_today_store_cache_missing(monkeypatch):
    from retail.search import iter_search_events

    scrape_calls: list[str] = []
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "retail.search.scrape_store",
        lambda store_id, *args, **kwargs: scrape_calls.append(store_id) or ([_phone(store_id, store_id)], None),
    )

    list(
        iter_search_events(
            "clavo",
            source="both",
            stores=["falabella", "ripley"],
            max_items=5,
            persist=False,
            delay=0,
            timeout=1,
            background_side_effects=False,
            wait_for_all=True,
        )
    )
    assert scrape_calls == ["falabella", "ripley"]


def test_quick_db_path_unchanged_with_today_store_cache(monkeypatch):
    """Búsqueda rápida sigue en DB y no scrapea aunque haya caché de tiendas."""
    from retail.search import search_products

    redis = MemoryRedis()
    SearchCache(redis).store_stores("clavo", {"paris": [_phone("paris", "P1")]}, max_items=8)
    scrape_calls: list[str] = []

    class _Repo:
        def ping(self):
            return True

        def close(self):
            return None

        def find_by_query(self, query):
            return [
                Product(
                    product_id="db-quick",
                    sku_id="db-quick",
                    name="Clavo rápido",
                    store="falabella",
                    price=500,
                ).to_dict(flatten_specs=False)
            ]

        def histories(self, keys):
            return {}

        def thumb_flags(self, keys):
            return set()

    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: redis)
    monkeypatch.setattr("retail.search.connect_repo", lambda: _Repo())
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "retail.search.scrape_store",
        lambda store_id, *args, **kwargs: scrape_calls.append(store_id) or ([], None),
    )

    result = search_products(
        "clavo",
        source="db",
        stores=["falabella", "paris"],
        max_items=8,
        persist=False,
        background_side_effects=False,
        wait_for_all=True,
        recover_underfilled_db=False,
    )
    assert scrape_calls == []
    assert result["offer_count"] >= 1
    assert "recovery" not in result


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
    assert [item["type"] for item in events] == ["start", "done", "end"]
    assert events[1]["result"]["rows"][0]["name"] == "TV LG"
    assert events[0]["progress"][0]["cached"] is True


def test_ianza_typo_rewrites_before_cache_and_scope(monkeypatch):
    from retail.search import iter_search_events
    from retail.search_cache import rewrite_search_query

    assert rewrite_search_query("azúcar ianza") == "azúcar iansa"
    seen = []

    def fake_lookup(query, **kwargs):
        seen.append(query)
        return {
            "query": query,
            "offer_count": 2,
            "rows": [{"name": "Azúcar Iansa", "price": 1290, "store": "lider"}],
            "progress": [{"id": "lider", "state": "ok", "count": 1}],
            "cache": {"hit": "result"},
        }

    monkeypatch.setattr("retail.search.lookup_search_result", fake_lookup)
    monkeypatch.setattr("retail.search.resolve_search_query", lambda query: query)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.launch_other_store_sweep", lambda *args, **kwargs: None)
    events = list(
        iter_search_events(
            "azúcar ianza",
            source="scrape",
            stores=["lider"],
            persist=False,
            fresh=False,
        )
    )
    assert seen == ["azúcar iansa"]
    assert events[0]["query"] == "azúcar iansa"
    assert events[1]["requested_query"] == "azúcar ianza"
    assert [item["type"] for item in events] == ["start", "done", "end"]


def test_summarize_search_cache_lists_today_queries(monkeypatch):
    now = datetime(2026, 10, 2, 15, 30, tzinfo=ZoneInfo("America/Santiago"))
    monkeypatch.setattr("retail.search_cache._now", lambda: now)
    redis = MemoryRedis()
    cache = SearchCache(redis)
    cache.store_stores(
        "galaxy s25 512gb",
        {"falabella": [_phone("falabella", "A")], "ripley": [_phone("ripley", "B")]},
        max_items=8,
    )
    cache.store_result(
        "tv 50",
        source="both",
        stores=["lider"],
        max_items=8,
        price_band=True,
        result={
            "query": "tv 50",
            "rows": [{"name": "TV", "price": 1, "store": "lider"}],
            "progress": [{"id": "lider", "state": "ok"}],
            "store_errors": [],
            "warnings": [],
        },
    )

    payload = summarize_search_cache(redis, now=now)
    assert payload["redis"] is True
    assert payload["day"] == "2026-10-02"
    assert payload["count"] == 2
    by_query = {item["query"]: item for item in payload["items"]}
    phone = by_query["galaxy s25 512gb"]
    assert phone["folded"] == "galaxy s25 512gb"
    assert phone["stores"] == ["falabella", "ripley"]
    assert phone["store_count"] == 2
    assert phone["result_cached"] is False
    assert phone["ttl"] == ttl_until_midnight(now)
    tv = by_query["tv 50"]
    assert tv["result_cached"] is True
    assert tv["stores"] == []


def test_load_search_cache_returns_empty_when_redis_down(monkeypatch):
    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: None)
    payload = load_search_cache(now=datetime(2026, 10, 2, 12, tzinfo=ZoneInfo("America/Santiago")))
    assert payload == {
        "redis": False,
        "day": "2026-10-02",
        "timezone": "America/Santiago",
        "count": 0,
        "items": [],
    }


def test_admin_stats_includes_search_cache(monkeypatch):
    from fastapi.testclient import TestClient

    from retail.web.app import app

    cache_payload = {
        "redis": True,
        "day": "2026-10-02",
        "timezone": "America/Santiago",
        "count": 1,
        "items": [
            {
                "query": "tv",
                "folded": "tv",
                "digest": "abc",
                "day": "2026-10-02",
                "stores": ["lider"],
                "store_titles": ["Lider"],
                "store_count": 1,
                "result_cached": True,
                "ttl": 3600,
            }
        ],
    }
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})
    monkeypatch.setattr(
        "retail.request_stats.load_stats",
        lambda: {"mongo": True, "totals": {}, "by_day": [], "by_hour": [], "origins": [], "groups": []},
    )
    monkeypatch.setattr("retail.search_stats.load_search_stats", lambda: {"mongo": True, "totals": {}, "by_day": [], "top": []})
    monkeypatch.setattr("retail.click_stats.load_click_stats", lambda: {"mongo": True, "totals": {}, "items": [], "by_day": []})
    monkeypatch.setattr("retail.scrape_stats.load_scrape_stats", lambda: {"mongo": True, "totals": {}, "by_day": []})
    monkeypatch.setattr("retail.search_cache.load_search_cache", lambda: cache_payload)

    response = TestClient(app).get("/api/admin/stats")
    assert response.status_code == 200
    assert response.json()["search_cache"] == cache_payload
