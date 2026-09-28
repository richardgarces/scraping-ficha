from datetime import datetime, timedelta, timezone

from timesfm_poc.forecast_from_mongo import daily_series_from_price_history, prepare_product


def history(days=30):
    start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    return [
        {"price": 1000 + day, "scraped_at": (start + timedelta(days=day)).isoformat()}
        for day in range(days)
    ]


def test_daily_series_reads_scraped_at_sorts_and_keeps_last_price_of_day():
    rows = history(2)
    rows.extend([
        {"price": 9999, "scraped_at": "2026-01-01T20:00:00+00:00"},
        {"price": -1, "scraped_at": "2026-01-03T12:00:00+00:00"},
        {"price": 5000, "scraped_at": "invalid"},
    ])
    rows.reverse()

    daily = daily_series_from_price_history(rows)

    assert [item["date"] for item in daily] == ["2026-01-01", "2026-01-02"]
    assert [item["price"] for item in daily] == [9999.0, 1001.0]


def test_timesfm_does_not_mix_card_history_with_all_payment_history():
    rows = history(30)
    rows.extend([
        {"price": 900, "price_basis": "card", "scraped_at": "2026-02-01T12:00:00+00:00"},
        {"price": 1200, "price_basis": "all_payment", "scraped_at": "2026-02-01T13:00:00+00:00"},
        {"price": 1100, "price_basis": "all_payment", "scraped_at": "2026-02-02T13:00:00+00:00"},
    ])
    daily = daily_series_from_price_history(rows)
    assert [item["price"] for item in daily] == [1200.0, 1100.0]


def test_prepare_product_requires_stable_identity_and_30_daily_points():
    base = {"store": "Falabella", "product_id": "SKU-1", "name": "Notebook", "price_history": history(30)}
    prepared, reason = prepare_product(base)
    assert reason is None
    assert prepared["forecast_key"] == "falabella:SKU-1"
    assert prepared["observation_count"] == 30
    assert prepared["history_start"] == "2026-01-01"
    assert prepared["history_end"] == "2026-01-30"

    assert prepare_product({**base, "product_id": ""})[1] == "missing_identity"
    assert prepare_product({**base, "price_history": history(29)})[1] == "not_enough_daily_points"
    assert prepare_product({**base, "stock_status": "Sin stock"})[1] == "out_of_stock"
