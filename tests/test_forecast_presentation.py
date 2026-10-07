from datetime import datetime, timezone

from retail.forecast_presentation import forecast_summary


def test_forecast_summary_exposes_trend_range_confidence_and_date():
    summary = forecast_summary(
        {
            "model": "timesfm",
            "horizon": 3,
            "generated_at": datetime(2026, 9, 20, tzinfo=timezone.utc),
            "point_forecast": [90, 88, 87],
            "quantiles": {"0.1": [80, 79, 78], "0.9": [101, 100, 99]},
            "metadata": {"observation_count": 45},
        },
        current_price=100,
    )
    assert summary["trend"] == "down"
    assert summary["range_low"] == 78
    assert summary["range_high"] == 101
    assert summary["confidence"] == "medium"
    assert summary["generated_at"].startswith("2026-09-20")
    assert summary["experimental"] is True


def test_forecast_without_quantiles_is_low_confidence():
    summary = forecast_summary(
        {"model": "last_value_baseline", "horizon": 2, "point_forecast": [100, 100], "metadata": {"observation_count": 120}},
        current_price=100,
    )
    assert summary["trend"] == "stable"
    assert summary["range_low"] == summary["range_high"] == 100
    assert summary["range_has_uncertainty"] is False
    assert summary["confidence"] == "low"


def test_legacy_text_quantiles_do_not_create_false_confidence():
    summary = forecast_summary(
        {"model": "timesfm", "point_forecast": [90, 95], "quantiles": "[not structured]", "metadata": {"observation_count": 100}},
        current_price=100,
    )
    assert summary["range_has_uncertainty"] is False
    assert summary["confidence"] == "low"


def test_invalid_current_price_and_horizon_do_not_break_summary():
    summary = forecast_summary(
        {"model": "timesfm", "point_forecast": [100, 90], "horizon": "invalid"},
        current_price=float("nan"),
    )
    assert summary["horizon_days"] == 2
    assert summary["change_percent"] == -5.0


def test_cyber_event_summary_exposes_buy_advice():
    summary = forecast_summary(
        {
            "model": "cyber_event_trend",
            "horizon": 3,
            "generated_at": datetime(2026, 10, 6, tzinfo=timezone.utc),
            "point_forecast": [90_000, 88_000, 86_000],
            "metadata": {
                "mode": "cyber_event",
                "observation_count": 24,
                "cyber_observation_count": 24,
                "buy_advice": {
                    "advice": "esperar",
                    "label": "Mejor esperar",
                    "reason": "Trayectoria a la baja en la ventana Cyber.",
                },
            },
        },
        current_price=95_000,
    )
    assert summary["mode"] == "cyber_event"
    assert summary["trend"] == "down"
    assert summary["confidence"] == "medium"
    assert summary["buy_advice"]["advice"] == "esperar"
    assert summary["buy_advice"]["label"] == "Mejor esperar"
