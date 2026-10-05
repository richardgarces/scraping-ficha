import sys
import types

import numpy as np

from retail.timesfm_runtime import forecast_with_timesfm3


class _FakeForecaster:
    def __init__(self):
        self.config = types.SimpleNamespace(quantiles=[0.1, 0.5])

    @classmethod
    def from_pretrained(cls, pretrained_model_name_or_path, device=None, local_files_only=False):
        return cls()

    def predict_batch(self, contexts, horizon, return_quantiles, make_positive):
        for context in contexts:
            last = float(context[-1])
            yield types.SimpleNamespace(
                forecast=np.asarray([last] * horizon, dtype=float),
                quantiles=np.asarray([[last - 1.0, last] for _ in range(horizon)], dtype=float),
            )


def test_forecast_with_timesfm3_uses_fake_backend(monkeypatch):
    monkeypatch.setitem(sys.modules, "timesfm3", types.SimpleNamespace(TimesFM3Forecaster=_FakeForecaster))

    point, quantiles = forecast_with_timesfm3([[10, 12, 15], []], 3, checkpoint_path="dummy", local_files_only=True)

    assert point == [[15.0, 15.0, 15.0], [0.0, 0.0, 0.0]]
    assert quantiles[0]["0.1"] == [14.0, 14.0, 14.0]
    assert quantiles[0]["0.5"] == [15.0, 15.0, 15.0]
    assert quantiles[1]["0.5"] == [0.0, 0.0, 0.0]


def test_default_timesfm25_maps_quantiles_without_mean(monkeypatch):
    class Model:
        @classmethod
        def from_pretrained(cls, checkpoint, **kwargs):
            assert checkpoint == "google/timesfm-2.5-200m-pytorch"
            return cls()

        def compile(self, config):
            assert config.per_core_batch_size == 1

        def forecast(self, horizon, inputs):
            return np.full((1, horizon), 100.0), np.tile(np.arange(10), (1, horizon, 1))

    monkeypatch.delenv("TIMESFM_CHECKPOINT", raising=False)
    monkeypatch.setitem(sys.modules, "timesfm", types.SimpleNamespace(
        TimesFM_2p5_200M_torch=Model, ForecastConfig=lambda **k: types.SimpleNamespace(**k),
    ))
    points, quantiles = forecast_with_timesfm3([[90, 100]], 2)
    assert points == [[100, 100]]
    assert quantiles[0]["0.1"] == [1, 1]
    assert quantiles[0]["0.9"] == [9, 9]
    assert "0.0" not in quantiles[0]
