from copy import deepcopy
from datetime import datetime, timedelta, timezone

from retail.offer_forecast_signal import attach_offer_forecast_signals, offer_forecast_signal


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


def forecast(**overrides):
    item = {
        "forecast_key": "lider:SKU-1",
        "model": "timesfm",
        "horizon": 7,
        "point_forecast": [100] * 7,
        "quantiles": {"0.1": [90] * 7, "0.9": [110] * 7},
        "metadata": {"observation_count": 90},
        "generated_at": NOW - timedelta(hours=2),
    }
    item.update(overrides)
    return item


def test_price_below_timesfm_range_is_exceptional():
    signal = offer_forecast_signal(forecast(), 80, now=NOW)
    assert signal["status"] == "exceptional"
    assert signal["label"] == "Caída excepcional"


def test_price_above_timesfm_range_warns_without_reclassifying():
    signal = offer_forecast_signal(forecast(), 120, now=NOW)
    assert signal["status"] == "above_expected"
    assert "sigue sobre el rango esperado" in signal["explanation"]


def test_price_inside_range_is_a_neutral_complement():
    signal = offer_forecast_signal(forecast(), 100, now=NOW)
    assert signal["status"] == "within_expected"


def test_stale_or_non_timesfm_forecast_is_not_used():
    assert offer_forecast_signal(forecast(model="last_value_baseline"), 80, now=NOW) is None
    assert offer_forecast_signal(forecast(generated_at=NOW - timedelta(days=3)), 80, now=NOW) is None
    assert offer_forecast_signal(forecast(quantiles={}), 80, now=NOW) is None


def test_attaching_signal_preserves_existing_offer_analysis():
    card = {
        "store": "lider", "product_id": "SKU-1", "price": 80,
        "kinds": ["comparacion", "historial"], "gap_percent": 35.0, "discount": 40.0,
    }
    original = deepcopy(card)
    assert attach_offer_forecast_signals([card], [forecast()], now=NOW) == 1
    for key, value in original.items():
        assert card[key] == value
    assert card["timesfm_signal"]["status"] == "exceptional"
