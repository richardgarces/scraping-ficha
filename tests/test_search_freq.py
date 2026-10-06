from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from retail.search_freq import (
    filter_result_payload,
    first_word,
    freq_redis_key,
    lookup_top_search,
    normalize_search_query,
    record_search_frequency,
    store_top_search_result,
    top_queries,
    top_redis_key,
)


class MemoryRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.data.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.data[key] = value
        self.ttls[key] = int(ttl)

    def expire(self, key: str, ttl: int) -> bool:
        self.ttls[key] = int(ttl)
        return True

    def zincrby(self, key: str, amount: float, member: str) -> float:
        bucket = self.zsets.setdefault(key, {})
        bucket[member] = float(bucket.get(member, 0.0)) + float(amount)
        return bucket[member]

    def zrevrange(self, key: str, start: int, end: int, withscores: bool = False):
        bucket = self.zsets.get(key) or {}
        ordered = sorted(bucket.items(), key=lambda item: (-item[1], item[0]))
        if end < 0:
            end = len(ordered) - 1
        slice_rows = ordered[start : end + 1]
        if withscores:
            return [(member, score) for member, score in slice_rows]
        return [member for member, _ in slice_rows]

    def ping(self) -> bool:
        return True


NOW = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("America/Santiago"))


def _result(*names: str, stores: list[str] | None = None) -> dict:
    store_ids = stores or ["falabella", "ripley"]
    rows = []
    offers = []
    for index, name in enumerate(names):
        store = store_ids[index % len(store_ids)]
        row = {
            "name": name,
            "brand": "Samsung" if "galaxy" in name.lower() or "s25" in name.lower() else "Genérica",
            "store": store,
            "store_title": store.title(),
            "price": 1000 + index,
            "product_id": f"p{index}",
            "attrs": {"model": name},
        }
        rows.append(row)
        offers.append(dict(row))
    return {
        "rows": rows,
        "groups": [{"title": "Grupo", "offers": offers, "comparable": len(offers) > 1}],
        "offer_count": len(rows),
        "group_count": 1,
        "comparable_count": 1 if len(offers) > 1 else 0,
        "stores": list(store_ids),
        "progress": [{"id": store, "title": store, "state": "ok"} for store in store_ids],
        "cancelled": False,
    }


@pytest.fixture
def redis(monkeypatch):
    client = MemoryRedis()
    monkeypatch.setattr("retail.search_freq.connect_redis", lambda: client)
    monkeypatch.setattr("retail.search_freq.chile_today", lambda now=None: "2026-10-05")
    monkeypatch.setattr("retail.search_freq.ttl_until_midnight", lambda now=None: 3600)
    return client


def test_normalize_folds_case_and_accents():
    assert normalize_search_query("  Célulár  ") == "celular"
    assert normalize_search_query("Celular S25") == "celular s25"
    assert first_word("celular s25 ultra") == "celular"


def test_record_increments_full_and_first_word(redis):
    record_search_frequency("Celular S25", redis_client=redis, now=NOW)
    record_search_frequency("celular", redis_client=redis, now=NOW)
    key = freq_redis_key("2026-10-05")
    assert redis.zsets[key]["celular s25"] == 1.0
    # primera palabra de «celular s25» + búsqueda exacta «celular»
    assert redis.zsets[key]["celular"] == 2.0


def test_exact_top_hit(redis):
    for _ in range(3):
        record_search_frequency("celular", redis_client=redis, now=NOW)
    payload = _result("Celular Samsung A15", "Celular Motorola G")
    assert store_top_search_result("celular", payload, redis_client=redis, now=NOW)
    hit = lookup_top_search("Célular", redis_client=redis, now=NOW)
    assert hit is not None
    assert hit["cache"]["hit"] == "top"
    assert hit["cache"]["day"] == "2026-10-05"
    assert hit["offer_count"] == 2


def test_prefix_hit_filters_extra_tokens(redis):
    for _ in range(5):
        record_search_frequency("celular", redis_client=redis, now=NOW)
    payload = _result(
        "Galaxy S25 Ultra 512GB",
        "Celular Motorola G54",
        "Audífonos Bluetooth",
    )
    assert store_top_search_result("celular", payload, redis_client=redis, now=NOW)
    hit = lookup_top_search("celular s25", redis_client=redis, now=NOW)
    assert hit is not None
    assert hit["cache"]["hit"] == "top_prefix"
    assert hit["cache"]["filter_tokens"] == ["s25"]
    names = [row["name"] for row in hit["rows"]]
    assert names == ["Galaxy S25 Ultra 512GB"]
    assert hit["offer_count"] == 1


def test_miss_when_not_in_top_or_no_payload(redis):
    record_search_frequency("tv", redis_client=redis, now=NOW)
    assert lookup_top_search("tv", redis_client=redis, now=NOW) is None
    for _ in range(3):
        record_search_frequency("notebook", redis_client=redis, now=NOW)
    assert lookup_top_search("notebook gamer", redis_client=redis, now=NOW) is None


def test_store_filter_on_global_top_cache(redis):
    for _ in range(3):
        record_search_frequency("celular", redis_client=redis, now=NOW)
    payload = _result("Galaxy S25", "iPhone 16", stores=["falabella", "ripley"])
    store_top_search_result("celular", payload, redis_client=redis, now=NOW)
    hit = lookup_top_search("celular", stores=["ripley"], redis_client=redis, now=NOW)
    assert hit is not None
    assert all(row["store"] == "ripley" for row in hit["rows"])
    assert hit["offer_count"] == 1


def test_filter_result_payload_tokens_case_insensitive():
    payload = _result("GALAXY S25", "otro")
    filtered = filter_result_payload(payload, tokens=["s25"])
    assert len(filtered["rows"]) == 1
    assert "S25" in filtered["rows"][0]["name"]


def test_top_queries_respects_limit(redis):
    for index in range(12):
        term = f"q{index}"
        for _ in range(index + 1):
            record_search_frequency(term, redis_client=redis, now=NOW)
    ranking = top_queries(redis_client=redis, now=NOW, limit=10)
    assert len(ranking) == 10
    assert ranking[0]["query"] == "q11"
    assert ranking[0]["count"] == 12


def test_rejects_payload_from_other_day(redis, monkeypatch):
    for _ in range(3):
        record_search_frequency("celular", redis_client=redis, now=NOW)
    store_top_search_result("celular", _result("Celular X"), redis_client=redis, now=NOW)
    # Simular clave con día viejo en el JSON.
    import json

    key = top_redis_key("celular", "2026-10-05")
    stale = json.loads(redis.data[key])
    stale["day"] = "2026-10-04"
    redis.data[key] = json.dumps(stale)
    assert lookup_top_search("celular", redis_client=redis, now=NOW) is None


def test_admin_stats_includes_search_freq(monkeypatch):
    from fastapi.testclient import TestClient

    from retail.web.app import app

    freq_payload = {
        "redis": True,
        "day": "2026-10-05",
        "timezone": "America/Santiago",
        "top_n": 10,
        "count": 1,
        "cached_count": 1,
        "items": [{"query": "celular", "count": 5, "cached": True}],
        "window": "día",
        "store_policy": "top global",
    }
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})
    monkeypatch.setattr(
        "retail.request_stats.load_stats",
        lambda: {"mongo": True, "totals": {}, "by_day": [], "by_hour": [], "origins": [], "groups": []},
    )
    monkeypatch.setattr(
        "retail.search_stats.load_search_stats",
        lambda: {"mongo": True, "totals": {}, "by_day": [], "top": []},
    )
    monkeypatch.setattr(
        "retail.click_stats.load_click_stats",
        lambda: {"mongo": True, "totals": {}, "items": [], "by_day": []},
    )
    monkeypatch.setattr(
        "retail.scrape_stats.load_scrape_stats",
        lambda: {"mongo": True, "totals": {}, "by_day": []},
    )
    monkeypatch.setattr(
        "retail.search_cache.load_search_cache",
        lambda: {"redis": True, "day": "2026-10-05", "count": 0, "items": []},
    )
    monkeypatch.setattr("retail.search_freq.load_search_freq", lambda: freq_payload)

    response = TestClient(app).get("/api/admin/stats")
    assert response.status_code == 200
    assert response.json()["search_freq"] == freq_payload
