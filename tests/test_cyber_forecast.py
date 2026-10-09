"""Historial Cyber → pronóstico experimental (listas oct/junio 2026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CYBER_GROUP_ID,
    append_best_price_observation,
    create_list,
    day_evolution_report,
    ensure_seed,
)
from retail.cyber_forecast import (
    CYBER_DENSE_MIN_CHANGES,
    CYBER_DENSE_MIN_POINTS,
    CYBER_DENSE_MODEL,
    CYBER_EVENT_MODEL,
    CYBER_FORECAST_MIN_OBSERVATIONS,
    CYBER_FUTURE_MODEL,
    MANY_CYBER_CHANGES,
    bucket_relative_series,
    count_price_changes,
    cyber_buy_advice,
    cyber_change_count,
    cyber_product_keys,
    ensure_forecast_for_product,
    ensure_cyber_list_forecasts,
    experimental_forecast_for_cyber_query,
    feed_cyber_observation_to_product_history,
    forecast_cyber_list_ids,
    is_dense_enough,
    latest_forecast,
    matches_forecast_cyber_list,
    merge_price_history_with_cyber,
    prepare_cyber_dense_event_product,
    prepare_cyber_enriched_product,
    prepare_cyber_event_product,
    prepare_cyber_future_transfer_product,
    project_cyber_event_prices,
    project_dense_event_prices,
    record_cyber_lap_samples,
)


NOW = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(mongo_uri, monkeypatch):
    from retail.mongo import ProductRepository

    repository = ProductRepository(mongo_uri, database=f"test_cyber_fc_{uuid4().hex}")
    monkeypatch.setattr("retail.cyber_day._now", lambda: NOW)
    monkeypatch.setattr("retail.cyber_forecast._now", lambda: NOW)
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_matches_forecast_cyber_list_slugs_and_names():
    assert matches_forecast_cyber_list("cyber_junio2026")
    assert matches_forecast_cyber_list("cyber_oct2026")
    assert matches_forecast_cyber_list("cyber_octubre_2026")
    assert matches_forecast_cyber_list("lista-x", name="Cyber Octubre 2026")
    assert matches_forecast_cyber_list("promo", title="Cyber Junio 2026 Sonic")
    assert not matches_forecast_cyber_list("cyber_prueba")
    assert not matches_forecast_cyber_list("retail")


def test_forecast_cyber_list_ids_resolves_oct_and_junio(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    ids = forecast_cyber_list_ids(repo)
    assert "cyber_junio2026" in ids
    assert "cyber_oct2026" in ids


def test_feed_and_forecast_when_many_cyber_changes(repo):
    ensure_seed(repo)
    store, product_id = "falabella", "SKU-CYBER-1"
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    history = [
        {
            "price": 100_000 + day,
            "price_basis": "all_payment",
            "scraped_at": start + timedelta(days=day),
        }
        for day in range(30)
    ]
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "TV Cyber",
        "price": history[-1]["price"],
        "price_history": history,
        "availability": "available",
    })

    for index in range(MANY_CYBER_CHANGES):
        at = NOW + timedelta(minutes=index)
        point = append_best_price_observation(
            repo,
            list_id=CYBER_GROUP_ID,
            n=1,
            query="TV OLED",
            summary={
                "last_price": 90_000 - index * 1000,
                "last_price_normal": 120_000,
                "best_store": store,
            },
            matches=[{
                "store": store,
                "product_id": product_id,
                "name": "TV Cyber",
                "price": 90_000 - index * 1000,
                "price_normal": 120_000,
            }],
            at=at,
        )
        assert point is not None

    assert cyber_change_count(repo, store, product_id) >= MANY_CYBER_CHANGES
    product = repo.collection.find_one({"store": store, "product_id": product_id})
    assert any(row.get("source") == "cyber_day" for row in (product.get("price_history") or []))

    forecast = latest_forecast(repo, store, product_id)
    assert forecast is not None
    assert forecast["forecast_key"] == f"{store}:{product_id}"
    assert forecast["metadata"].get("cyber_observation_count", 0) >= 1 or forecast["model"] in {
        "last_value_baseline", "timesfm",
    }


def test_prepare_merges_cyber_history_not_yet_in_product(repo):
    ensure_seed(repo)
    store, product_id = "ripley", "SKU-MERGE"
    start = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Notebook",
        "price": 500_000,
        "price_history": [
            {
                "price": 500_000 + day,
                "price_basis": "all_payment",
                "scraped_at": start + timedelta(days=day),
            }
            for day in range(28)
        ],
    })
    # Dos días Cyber adicionales que no están en price_history del producto.
    for offset, price in enumerate((480_000, 470_000)):
        repo.cyber_day_price_history.insert_one({
            "list_id": CYBER_GROUP_ID,
            "n": 2,
            "query": "Notebook",
            "day": (start + timedelta(days=28 + offset)).date().isoformat(),
            "at": start + timedelta(days=28 + offset),
            "price": price,
            "price_normal": 600_000,
            "store": store,
            "product_id": product_id,
            "name": "Notebook",
        })

    prepared, reason = prepare_cyber_enriched_product(repo, store, product_id)
    assert reason is None
    assert prepared is not None
    assert prepared["observation_count"] >= 30
    assert prepared["cyber_observation_count"] == 2


def test_ensure_list_forecasts_writes_cyber_event_with_dense_same_day_laps(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "paris", "SHORT-HIST"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Short",
        "price": 10_000,
        "price_history": [{
            "price": 10_000,
            "price_basis": "all_payment",
            "scraped_at": NOW,
        }],
    })
    for index in range(CYBER_FORECAST_MIN_OBSERVATIONS):
        repo.cyber_day_price_history.insert_one({
            "list_id": "cyber_oct2026",
            "n": 1,
            "query": "Short",
            "day": "2026-10-06",
            "at": NOW + timedelta(minutes=index * 10),
            "price": 10_000 - index * 50,
            "store": store,
            "product_id": product_id,
        })
    # last_matches para que cyber_product_keys lo vea
    repo.cyber_day_products.insert_one({
        "list_id": "cyber_oct2026",
        "n": 1,
        "order": 1,
        "query": "Short",
        "last_matches": {f"{store}:{product_id}": "10000:0:0"},
    })

    stats = ensure_cyber_list_forecasts(repo, list_id="cyber_oct2026", use_timesfm=False, force=True)
    assert stats["candidates"] >= 1
    assert stats["written"] >= 1
    assert stats["written_cyber_event"] >= 1
    forecast = latest_forecast(repo, store, product_id)
    assert forecast is not None
    assert forecast["model"] == CYBER_EVENT_MODEL
    assert forecast["horizon"] <= 3
    assert forecast.get("buy_advice", {}).get("advice") in {"comprar", "esperar", "observar"}


def test_merge_price_history_with_cyber_keeps_both_sources():
    base = [{"price": 1, "scraped_at": NOW}]
    cyber = [{"price": 2, "scraped_at": NOW + timedelta(hours=1), "source": "cyber_day"}]
    merged = merge_price_history_with_cyber(base, cyber)
    assert len(merged) == 2
    assert merged[1]["source"] == "cyber_day"


def test_feed_respects_should_record_dedupe(repo):
    store, product_id = "lider", "DEDUP"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "X",
        "price": 1000,
        "price_history": [],
    })
    obs = {
        "store": store,
        "product_id": product_id,
        "price": 1000,
        "price_normal": 2000,
        "at": NOW,
        "day": "2026-10-06",
        "list_id": CYBER_GROUP_ID,
        "n": 1,
        "query": "X",
    }
    assert feed_cyber_observation_to_product_history(repo, obs) is True
    assert feed_cyber_observation_to_product_history(repo, obs) is False


def test_cyber_product_keys_from_history_and_matches(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    repo.cyber_day_products.insert_one({
        "list_id": "cyber_oct2026",
        "n": 9,
        "order": 9,
        "query": "AirPods",
        "last_matches": {"hites:AAA": "1:0:0", "falabella:BBB": "2:0:0"},
    })
    keys = set(cyber_product_keys(repo, ["cyber_oct2026"]))
    assert ("hites", "AAA") in keys
    assert ("falabella", "BBB") in keys


def test_ensure_forecast_writes_baseline(repo):
    store, product_id = "abcdin", "FULL-30"
    start = datetime(2026, 3, 1, 12, tzinfo=timezone.utc)
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Full",
        "price": 200_000,
        "price_history": [
            {
                "price": 200_000 - day,
                "price_basis": "all_payment",
                "scraped_at": start + timedelta(days=day),
            }
            for day in range(30)
        ],
    })
    result = ensure_forecast_for_product(
        repo,
        store,
        product_id,
        list_ids=[],
        use_timesfm=False,
        force=True,
        prefer_cyber_event=False,
    )
    assert result["ok"] is True
    assert result["action"] == "written"
    assert latest_forecast(repo, store, product_id)["model"] == "last_value_baseline"


def test_project_and_buy_advice_for_falling_cyber_prices():
    prices = [100_000 - i * 1000 for i in range(10)]
    projected = project_cyber_event_prices(prices, horizon=3, span_seconds=12 * 3600)
    assert len(projected) == 3
    assert projected[-1] < prices[-1]
    advice = cyber_buy_advice(current=prices[-1], prices=prices, point_forecast=projected)
    assert advice["advice"] == "esperar"
    assert "esperar" in advice["label"].lower() or "mejor" in advice["label"].lower()


def test_buy_advice_comprar_near_cyber_low():
    prices = [90_000, 88_000, 85_000, 84_000, 83_500]
    projected = [83_400, 83_300, 83_200]
    advice = cyber_buy_advice(current=83_500, prices=prices, point_forecast=projected)
    assert advice["advice"] == "comprar"


def test_record_cyber_lap_samples_feeds_even_if_price_unchanged(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "falabella", "LAP-STABLE"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Stable",
        "price": 200_000,
        "price_history": [],
    })
    repo.cyber_day_products.insert_one({
        "list_id": "cyber_oct2026",
        "n": 7,
        "order": 7,
        "query": "Stable",
        "last_price": 200_000,
        "last_price_normal": 250_000,
        "best_store": store,
        "last_product_id": product_id,
        "last_matches": {f"{store}:{product_id}": "200000:0:0"},
    })
    first = record_cyber_lap_samples(repo, "cyber_oct2026", lap=56, at=NOW)
    second = record_cyber_lap_samples(repo, "cyber_oct2026", lap=56, at=NOW)
    third = record_cyber_lap_samples(repo, "cyber_oct2026", lap=57, at=NOW + timedelta(minutes=30))
    assert first["inserted"] == 1
    assert second["inserted"] == 0  # misma vuelta + día
    assert third["inserted"] == 1
    assert cyber_change_count(repo, store, product_id, list_ids=["cyber_oct2026"]) >= 2


def test_experimental_forecast_for_cyber_query_from_day_history(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "falabella", "EVO-TV"
    repo.cyber_day_products.insert_one({
        "list_id": "cyber_oct2026",
        "n": 4,
        "order": 4,
        "query": "TV OLED",
        "last_price": 480_000,
        "best_store": store,
        "last_product_id": product_id,
    })
    for index in range(CYBER_FORECAST_MIN_OBSERVATIONS + 1):
        repo.cyber_day_price_history.insert_one({
            "list_id": "cyber_oct2026",
            "n": 4,
            "query": "TV OLED",
            "day": "2026-10-06",
            "at": NOW + timedelta(minutes=index * 20),
            "price": 500_000 - index * 5000,
            "store": store,
            "product_id": product_id,
        })
    payload = experimental_forecast_for_cyber_query(
        repo,
        list_id="cyber_oct2026",
        n=4,
        current_price=480_000,
    )
    assert payload["ok"] is True
    assert payload["source"] == "query_history"
    assert payload["summary"] is not None
    assert payload["summary"]["model"] in {CYBER_EVENT_MODEL, CYBER_DENSE_MODEL}
    assert payload["summary"]["buy_advice"]["advice"] in {"comprar", "esperar", "observar"}
    report = day_evolution_report(repo, 4, list_id="cyber_oct2026", day="2026-10-06")
    assert report["forecast"]["summary"]["model"] in {CYBER_EVENT_MODEL, CYBER_DENSE_MODEL}
    assert report["forecast"]["summary"]["range_low"] is not None
    assert report["forecast"]["summary"]["range_high"] is not None


def test_prepare_cyber_event_without_30_calendar_days(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "falabella", "EVENT-ONLY"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Event TV",
        "price": 500_000,
        "price_history": [{
            "price": 500_000,
            "price_basis": "all_payment",
            "scraped_at": NOW,
        }],
    })
    for index in range(CYBER_FORECAST_MIN_OBSERVATIONS + 2):
        repo.cyber_day_price_history.insert_one({
            "list_id": "cyber_oct2026",
            "n": 3,
            "query": "Event TV",
            "day": "2026-10-06",
            "at": NOW + timedelta(minutes=index * 15),
            "price": 500_000 - index * 2000,
            "store": store,
            "product_id": product_id,
        })
    prepared, reason = prepare_cyber_event_product(repo, store, product_id, list_ids=["cyber_oct2026"])
    assert reason is None
    assert prepared is not None
    assert prepared["mode"] == "cyber_event"
    assert prepared["horizon"] <= 3
    assert prepared["buy_advice"]["advice"] in {"comprar", "esperar", "observar"}
    result = ensure_forecast_for_product(
        repo, store, product_id, list_ids=["cyber_oct2026"], force=True,
    )
    assert result["ok"] is True
    assert result["model"] in {CYBER_EVENT_MODEL, CYBER_DENSE_MODEL}
    assert result["buy_advice"] in {"comprar", "esperar", "observar"}


def _dense_history(repo, *, list_id, n, store, product_id, start, count=10, step_min=12, drop=3000):
    for index in range(count):
        repo.cyber_day_price_history.insert_one({
            "list_id": list_id,
            "n": n,
            "query": "Dense TV",
            "day": (start + timedelta(minutes=index * step_min)).date().isoformat(),
            "at": start + timedelta(minutes=index * step_min),
            "price": 400_000 - index * drop,
            "store": store,
            "product_id": product_id,
        })


def test_dense_series_helpers_and_event_forecast(repo):
    ensure_seed(repo)
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "falabella", "DENSE-1"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Dense TV",
        "price": 370_000,
        "price_history": [],
    })
    _dense_history(
        repo,
        list_id="cyber_oct2026",
        n=11,
        store=store,
        product_id=product_id,
        start=NOW,
        count=max(CYBER_DENSE_MIN_POINTS, 10),
    )
    points = [
        {"price": 400_000 - i * 3000, "scraped_at": NOW + timedelta(minutes=i * 12)}
        for i in range(max(CYBER_DENSE_MIN_POINTS, 10))
    ]
    bucketed = bucket_relative_series(points)
    assert is_dense_enough(points, bucketed)
    assert count_price_changes([p["price"] for p in points]) >= CYBER_DENSE_MIN_CHANGES
    projected = project_dense_event_prices(bucketed, horizon=2, current=370_000)
    assert len(projected) == 2
    prepared, reason = prepare_cyber_dense_event_product(
        repo, store, product_id, list_ids=["cyber_oct2026"], current_price=370_000,
    )
    assert reason is None
    assert prepared is not None
    assert prepared["model"] == CYBER_DENSE_MODEL
    assert prepared["mode"] == "cyber_event"
    result = ensure_forecast_for_product(
        repo, store, product_id, list_ids=["cyber_oct2026"], force=True,
    )
    assert result["ok"] is True
    assert result["model"] == CYBER_DENSE_MODEL
    doc = latest_forecast(repo, store, product_id)
    assert doc["model"] == CYBER_DENSE_MODEL


def test_future_transfer_needs_two_dense_cybers(repo):
    ensure_seed(repo)  # incluye cyber_junio2026
    create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    store, product_id = "falabella", "FUTURE-1"
    repo.collection.insert_one({
        "store": store,
        "product_id": product_id,
        "name": "Future TV",
        "price": 390_000,
        "price_history": [],
    })
    blocked, reason = prepare_cyber_future_transfer_product(
        repo, store, product_id, list_ids=["cyber_oct2026", "cyber_junio2026"],
    )
    assert blocked is None
    assert reason == "need_another_dense_cyber"

    _dense_history(
        repo,
        list_id="cyber_junio2026",
        n=1,
        store=store,
        product_id=product_id,
        start=NOW - timedelta(days=90),
        count=10,
    )
    still, reason2 = prepare_cyber_future_transfer_product(
        repo, store, product_id, list_ids=["cyber_oct2026", "cyber_junio2026"],
    )
    assert still is None
    assert reason2 == "need_another_dense_cyber"

    _dense_history(
        repo,
        list_id="cyber_oct2026",
        n=1,
        store=store,
        product_id=product_id,
        start=NOW,
        count=10,
        drop=2500,
    )
    prepared, ok_reason = prepare_cyber_future_transfer_product(
        repo, store, product_id, list_ids=["cyber_oct2026", "cyber_junio2026"], scale_price=390_000,
    )
    assert ok_reason is None
    assert prepared is not None
    assert prepared["model"] == CYBER_FUTURE_MODEL
    assert prepared["mode"] == "cyber_future"
    assert len(prepared["point_forecast"]) >= 1
    assert len(prepared["source_events"]) >= 2

    payload = experimental_forecast_for_cyber_query(
        repo,
        list_id="cyber_oct2026",
        n=1,
        product={"best_store": store, "last_product_id": product_id, "last_price": 390_000},
        current_price=390_000,
    )
    assert payload["future_summary"] is not None
    assert payload["future_summary"]["mode"] == "cyber_future"
    assert "próximo" in (payload["future_summary"].get("mode_label") or "").lower() or \
        payload["future_summary"]["model"] == CYBER_FUTURE_MODEL
