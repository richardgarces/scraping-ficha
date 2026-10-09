#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retail.predictive_alerts import VALIDATION_KEY, validation_metrics
from retail.mongo import ProductRepository
from retail.timesfm_runtime import forecast_with_timesfm3
from timesfm_poc.forecast_from_mongo import prepare_product, read_products_from_mongo


def main() -> None:
    sample = max(30, int(os.environ.get("FORECAST_VALIDATION_SAMPLE", "50")))
    holdout = max(3, int(os.environ.get("FORECAST_VALIDATION_HORIZON", "7")))
    minimum = max(30, int(os.environ.get("FORECAST_MIN_HISTORY_DAYS", "30")))
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    db = os.environ.get("MONGODB_DB", "scraping")
    documents = read_products_from_mongo(uri, db, "products", sample, minimum)
    contexts, actuals = [], []
    for document in documents:
        product, _reason = prepare_product(document, minimum)
        if not product or len(product["series"]) < holdout + 14:
            continue
        contexts.append(product["series"][:-holdout])
        actuals.append(product["series"][-holdout:])
        if len(contexts) >= sample:
            break
    result = {"model": "timesfm", "evaluated_series": 0, "error": None, "last_error": None}
    if contexts:
        try:
            predictions, _quantiles = forecast_with_timesfm3(contexts, holdout)
            result = validation_metrics(predictions, actuals, contexts)
            result["last_error"] = None
        except Exception as exc:
            message = str(exc)[:500]
            result["error"] = message
            result["last_error"] = message
    else:
        message = "No hay productos con historial suficiente para validar."
        result["error"] = message
        result["last_error"] = message
    repo = ProductRepository()
    try:
        if not repo.ping():
            raise SystemExit("MongoDB no está disponible para guardar la validación.")
        repo.save_app_setting(VALIDATION_KEY, result)
    finally:
        repo.close()
    print(json.dumps(result, ensure_ascii=False, default=str))
    if result.get("last_error"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
