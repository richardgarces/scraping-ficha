from datetime import datetime, timedelta, timezone

from retail.batch.adaptive import (
    aggregate_catalog_priorities,
    assess_product,
    detect_price_patterns,
    plan_catalog_products,
)


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def history(days, price_for_day):
    start = NOW - timedelta(days=days - 1)
    return [
        {"scraped_at": (start + timedelta(days=index)).isoformat(), "price": price_for_day(index, start + timedelta(days=index))}
        for index in range(days)
    ]


def product(ident, rows, price=100):
    return {
        "store": "lider", "product_id": ident, "catalog_id": f"CAT-{ident}",
        "name": "Producto", "catalog_category": "supermercado", "price": price,
        "price_history": rows,
    }


def test_stable_products_are_checked_less_often_than_volatile_products():
    stable = assess_product(product("stable", history(120, lambda _i, _d: 100)), now=NOW)
    volatile = assess_product(product("volatile", history(60, lambda i, _d: 80 if i % 2 else 120)), now=NOW)
    assert stable["tier"] == "dormant"
    assert stable["recommended_interval_hours"] == 168
    assert volatile["tier"] == "high"
    assert volatile["recommended_interval_hours"] == 12


def test_timesfm_offer_probability_raises_priority_only_when_validated():
    rows = history(40, lambda _i, _d: 100)
    forecast = {
        "model": "timesfm", "horizon": 7, "point_forecast": [90] * 7,
        "quantiles": {"0.1": [85] * 7, "0.9": [95] * 7},
        "metadata": {"observation_count": 90}, "generated_at": NOW,
    }
    without_model = assess_product(product("one", rows), forecast, timesfm_validated=False, now=NOW)
    with_model = assess_product(product("one", rows), forecast, timesfm_validated=True, now=NOW)
    assert without_model["score"] == 50
    assert with_model["score"] == 85
    assert with_model["timesfm"]["high_offer_probability"] is True


def test_weekday_promotions_are_detected_from_repeated_observations():
    rows = history(56, lambda _i, moment: 80 if moment.weekday() == 0 else 100)
    patterns = detect_price_patterns(rows, store="lider", category="supermercado")
    weekday = next(item for item in patterns if item["type"] == "weekday_promotion")
    assert "lunes" in weekday["label"]
    assert weekday["samples"] >= 4


def test_timesfm_can_confirm_but_not_invent_a_seasonal_pattern():
    rows = history(56, lambda _i, moment: 80 if moment.weekday() == 0 else 100)
    item = product("weekday", rows, price=100)
    forecast = {
        "model": "timesfm", "horizon": 7, "point_forecast": [90] * 7,
        "quantiles": {"0.1": [85] * 7, "0.9": [95] * 7},
        "metadata": {"observation_count": 90}, "generated_at": NOW,
    }
    assessment = assess_product(item, forecast, timesfm_validated=True, now=NOW)
    assert assessment["timesfm_confirmed_patterns"] == 1
    assert assessment["patterns"][0]["timesfm_consistent"] is True


def test_catalog_priority_uses_the_most_important_product_in_the_query():
    stable = assess_product(product("stable", history(120, lambda _i, _d: 100)), now=NOW)
    volatile_product = product("volatile", history(60, lambda i, _d: 80 if i % 2 else 120))
    volatile_product["catalog_id"] = stable["catalog_id"]
    volatile = assess_product(volatile_product, now=NOW)
    priorities = aggregate_catalog_priorities([stable, volatile], now=NOW)
    assert len(priorities) == 1
    assert priorities[0]["tier"] == "high"
    assert priorities[0]["product_count"] == 2


def test_plan_defers_stable_queries_but_never_uses_an_expired_plan():
    products = [{"id": "high", "query": "A"}, {"id": "stable", "query": "B"}]
    priorities = [
        {"catalog_id": "high", "score": 90, "next_due_at": NOW - timedelta(hours=1), "updated_at": NOW},
        {"catalog_id": "stable", "score": 10, "next_due_at": NOW + timedelta(days=5), "updated_at": NOW},
    ]
    selected, meta = plan_catalog_products(products, priorities, now=NOW)
    assert [item["id"] for item in selected] == ["high"]
    assert meta["deferred"] == 1
    expired = [{**item, "updated_at": NOW - timedelta(days=3)} for item in priorities]
    selected, meta = plan_catalog_products(products, expired, now=NOW)
    assert selected == products
    assert meta["enabled"] is False
