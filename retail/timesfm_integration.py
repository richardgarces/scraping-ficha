"""Helpers to integrate TimesFM forecasting into the `retail` app."""
from __future__ import annotations

from timesfm_poc.forecast_from_mongo import generate_forecasts
from retail.timesfm_runtime import forecast_with_timesfm3


def forecast_series(series_list: list[list[float]], horizon: int = 30) -> tuple[list[list[float]], list[dict[str, list[float]]]]:
    """Forecast an in-memory batch of price series using TimesFM 3 when available."""
    return forecast_with_timesfm3(series_list, horizon)


def generate_and_return(sample: int = 10, horizon: int = 30, simulate: bool = True, use_timesfm: bool | None = None, min_history_days: int = 30) -> list[dict]:
    """Return generated forecast documents (does not write to Mongo)."""
    return generate_forecasts(mongo_uri=None, sample=sample, horizon=horizon, simulate=simulate, use_timesfm=use_timesfm, min_history_days=min_history_days)


def generate_and_store(mongo_uri: str, mongo_db: str = "scraping", sample: int = 10, horizon: int = 30, use_timesfm: bool | None = None, min_history_days: int = 30) -> None:
    """Generate forecasts and store into Mongo using given `mongo_uri`."""
    generate_forecasts(mongo_uri=mongo_uri, mongo_db=mongo_db, sample=sample, horizon=horizon, simulate=False, use_timesfm=use_timesfm, min_history_days=min_history_days)
