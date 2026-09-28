from retail.notification_preferences import normalize_preferences
from datetime import datetime, timedelta, timezone

from retail.predictive_alerts import (
    anticipated_drop_signal,
    anticipated_drop_validation_status,
    predictive_message,
    predictive_validation_status,
    validation_metrics,
)


NOW = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)


class Repo:
    def __init__(self, setting=None):
        self.setting = setting

    def get_app_setting(self, key):
        assert key == "timesfm_validation"
        return self.setting


def test_predictive_notifications_are_user_selectable():
    prefs = normalize_preferences({"channels": ["email"], "kinds": ["predictive"]})
    assert prefs["kinds"] == ["predictive"]


def test_validation_gate_requires_enough_series_and_better_accuracy():
    assert predictive_validation_status(Repo())["enabled"] is False
    approved = predictive_validation_status(Repo({
        "model": "timesfm", "evaluated_series": 30,
        "improvement_vs_baseline_percent": 8, "direction_accuracy": 0.6,
    }))
    assert approved["enabled"] is True


def test_anticipated_drop_uses_a_stricter_validation_gate():
    regular_only = Repo({
        "model": "timesfm", "evaluated_series": 30,
        "improvement_vs_baseline_percent": 8, "direction_accuracy": 0.6,
    })
    assert predictive_validation_status(regular_only)["enabled"] is True
    assert anticipated_drop_validation_status(regular_only)["enabled"] is False
    strict = Repo({
        "model": "timesfm", "evaluated_series": 50,
        "improvement_vs_baseline_percent": 12, "direction_accuracy": 0.72,
    })
    assert anticipated_drop_validation_status(strict)["enabled"] is True


def test_validation_compares_timesfm_with_last_price_baseline():
    metrics = validation_metrics(
        predictions=[[90, 80], [110, 120]],
        actuals=[[88, 82], [112, 118]],
        contexts=[[100, 100], [100, 100]],
    )
    assert metrics["evaluated_series"] == 2
    assert metrics["model_mae"] < metrics["baseline_mae"]
    assert metrics["improvement_vs_baseline_percent"] > 0
    assert metrics["direction_accuracy"] == 1


def test_predictive_messages_cover_wait_and_buy_now():
    base = {
        "model": "timesfm", "name": "Notebook", "store": "falabella", "horizon": 7,
        "metadata": {"observation_count": 90}, "generated_at": NOW - timedelta(hours=2),
    }
    wait = predictive_message(
        {**base, "point_forecast": [90] * 7, "quantiles": {"0.1": [80] * 7, "0.9": [95] * 7}},
        110,
        112,
        allow_anticipated=True,
        now=NOW,
    )
    assert wait[0] == "anticipated_drop"
    assert "aún no está en oferta" in wait[1]
    assert "posibilidad alta" in wait[1]
    assert "Conviene esperar" in wait[1]

    buy = predictive_message(
        {**base, "point_forecast": [120] * 7, "quantiles": {"0.1": [110] * 7, "0.9": [130] * 7}},
        100,
        now=NOW,
    )
    assert buy[0] == "buy_now"
    assert "Precio actual menor que el rango esperado" in buy[1]
    assert "Buen momento para comprar" in buy[1]


def test_anticipated_drop_rejects_weak_or_already_discounted_cases():
    strong = {
        "model": "timesfm", "horizon": 7, "generated_at": NOW - timedelta(hours=1),
        "metadata": {"observation_count": 90}, "point_forecast": [90] * 7,
        "quantiles": {"0.1": [80] * 7, "0.9": [95] * 7},
    }
    assert anticipated_drop_signal(strong, 110, 112, now=NOW)["confidence"] == "high"
    assert predictive_message(strong, 110, 112, now=NOW) is None
    assert anticipated_drop_signal(strong, 90, 120, now=NOW) is None
    assert anticipated_drop_signal({**strong, "quantiles": {"0.1": [80] * 7, "0.9": [112] * 7}}, 110, 112, now=NOW) is None
    assert anticipated_drop_signal({**strong, "generated_at": NOW - timedelta(days=3)}, 110, 112, now=NOW) is None
