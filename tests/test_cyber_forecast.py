"""Historial Cyber → pronóstico experimental (listas oct/junio 2026)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CYBER_GROUP_ID,
    append_best_price_observation,
    create_list,
    ensure_seed,
)
from retail.cyber_forecast import (
    MANY_CYBER_CHANGES,
    cyber_change_count,
    cyber_product_keys,
    ensure_forecast_for_product,
    ensure_cyber_list_forecasts,
    feed_cyber_observation_to_product_history,
    forecast_cyber_list_ids,
    latest_forecast,
    matches_forecast_cyber_list,
    merge_price_history_with_cyber,
    prepare_cyber_enriched_product,
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


def test_ensure_list_forecasts_reports_gap_when_many_changes_but_short_history(repo):
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
    for index in range(MANY_CYBER_CHANGES):
        repo.cyber_day_price_history.insert_one({
            "list_id": "cyber_oct2026",
            "n": 1,
            "query": "Short",
            "day": "2026-10-06",
            "at": NOW + timedelta(minutes=index),
            "price": 10_000 - index,
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

    stats = ensure_cyber_list_forecasts(repo, list_id="cyber_oct2026", use_timesfm=False)
    assert stats["candidates"] >= 1
    assert stats["missing_forecast_with_many_changes"] >= 1
    assert latest_forecast(repo, store, product_id) is None


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
        repo, store, product_id, list_ids=[], use_timesfm=False, force=True,
    )
    assert result["ok"] is True
    assert result["action"] == "written"
    assert latest_forecast(repo, store, product_id)["model"] == "last_value_baseline"
