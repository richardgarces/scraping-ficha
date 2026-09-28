from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _add_local_timesfm_src() -> None:
    candidates = []
    env_path = os.environ.get("TIMESFM_SRC_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(__file__).resolve().parents[2] / "timesfm" / "src")
    for candidate in candidates:
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return


def import_timesfm3_module():
    try:
        return importlib.import_module("timesfm3")
    except ModuleNotFoundError:
        _add_local_timesfm_src()
        return importlib.import_module("timesfm3")


def forecast_with_timesfm3(
    series_list: list[list[float]],
    horizon: int,
    *,
    checkpoint_path: str | None = None,
    device: str | None = None,
    local_files_only: bool | None = None,
) -> tuple[list[list[float]], list[dict[str, list[float]]]]:
    np = importlib.import_module("numpy")
    timesfm3 = import_timesfm3_module()
    checkpoint = checkpoint_path or os.environ.get("TIMESFM_CHECKPOINT") or "google/timesfm-3.0-pytorch"
    runtime_device = device or os.environ.get("TIMESFM_DEVICE")
    if local_files_only is None:
        local_files_only = os.environ.get("TIMESFM_LOCAL_FILES_ONLY", "0") in {"1", "true", "True"}

    forecaster = timesfm3.TimesFM3Forecaster.from_pretrained(
        pretrained_model_name_or_path=checkpoint,
        device=runtime_device,
        local_files_only=local_files_only,
    )

    contexts = []
    for series in series_list:
        if series:
            contexts.append(np.asarray(series, dtype=np.float32))
        else:
            contexts.append(np.zeros((1,), dtype=np.float32))

    outputs = list(
        forecaster.predict_batch(
            contexts=contexts,
            horizon=horizon,
            return_quantiles=True,
            make_positive=True,
        )
    )

    quantile_names = [str(q) for q in getattr(forecaster.config, "quantiles", [])]
    point_forecasts: list[list[float]] = []
    quantile_forecasts: list[dict[str, list[float]]] = []
    for output in outputs:
        forecast = np.asarray(output.forecast if output.forecast is not None else np.zeros((horizon,)), dtype=float)
        point_forecasts.append([float(x) for x in forecast[:horizon]])

        item_quantiles: dict[str, list[float]] = {}
        if output.quantiles is not None and quantile_names:
            matrix = np.asarray(output.quantiles, dtype=float)
            for index, name in enumerate(quantile_names):
                item_quantiles[name] = [float(x) for x in matrix[:horizon, index]]
        quantile_forecasts.append(item_quantiles)

    return point_forecasts, quantile_forecasts