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
