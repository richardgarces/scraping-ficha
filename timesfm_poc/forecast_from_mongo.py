#!/usr/bin/env python3
"""PoC: extrae series desde Mongo, corre TimesFM (si está) y guarda forecasts en Mongo.

Uso básico (simula forecasts sin Mongo):
  python timesfm_poc/forecast_from_mongo.py --simulate --sample 3 --horizon 7

Si Mongo está disponible y quieres conectar:
  MONGODB_URI=mongodb://localhost:27017 MONGODB_DB=scraping python timesfm_poc/forecast_from_mongo.py --sample 10 --horizon 30
"""
import argparse
import datetime
import json
import os
import sys
from collections import Counter
from zoneinfo import ZoneInfo

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mongo-uri", default=os.environ.get("MONGODB_URI", ""))
    p.add_argument("--mongo-db", default=os.environ.get("MONGODB_DB", "scraping"))
    p.add_argument("--collection", default=os.environ.get("PRODUCT_COLLECTION", "products"))
    p.add_argument("--forecasts-collection", default=os.environ.get("FORECASTS_COLLECTION", "forecasts"))
    p.add_argument("--sample", type=int, default=10)
    p.add_argument("--horizon", type=int, default=30)
    p.add_argument("--min-history-days", type=int, default=30)
    p.add_argument("--simulate", action="store_true", help="No usar timesfm, simular forecasts")
    p.add_argument(
        "--include-cyber",
        dest="include_cyber",
        action="store_true",
        default=None,
        help="Prioriza productos de listas Cyber oct/junio 2026",
    )
    p.add_argument(
        "--no-include-cyber",
        dest="include_cyber",
        action="store_false",
        help="No priorizar ni enriquecer con historial Cyber",
    )
    return p.parse_args()


def _enrich_docs_with_cyber_history(uri, dbname, docs):
    """Mezcla cyber_day_price_history en price_history de candidatos Cyber."""
    if not docs:
        return docs
    try:
        from pymongo import MongoClient
        from retail.cyber_forecast import (
            cyber_history_points_for_product,
            forecast_cyber_list_ids,
            merge_price_history_with_cyber,
        )
        from retail.mongo import ProductRepository
    except Exception:
        return docs
    repo = ProductRepository(uri, database=dbname)
    try:
        list_ids = forecast_cyber_list_ids(repo)
        if not list_ids:
            return docs
        for document in docs:
            store = str(document.get("store") or "").strip().lower()
            product_id = str(document.get("product_id") or "").strip()
            if not store or not product_id:
                continue
            cyber_points = cyber_history_points_for_product(
                repo, store, product_id, list_ids=list_ids,
            )
            if not cyber_points:
                continue
            document["price_history"] = merge_price_history_with_cyber(
                document.get("price_history"),
                cyber_points,
            )
            document["_cyber_enriched"] = True
            document["_cyber_observation_count"] = len(cyber_points)
            document["_cyber_list_ids"] = list_ids
    finally:
        repo.close()
    return docs


def read_cyber_products_from_mongo(uri, dbname, collection_name, min_history_days=30):
    """Carga productos ligados a listas Cyber oct/junio 2026 (historial enriquecido)."""
    try:
        from pymongo import MongoClient
        from retail.cyber_forecast import cyber_product_keys, forecast_cyber_list_ids
        from retail.mongo import ProductRepository
    except Exception:
        return []
    repo = ProductRepository(uri, database=dbname)
    try:
        list_ids = forecast_cyber_list_ids(repo)
        keys = cyber_product_keys(repo, list_ids)
        if not keys:
            return []
        client = MongoClient(uri)
        col = client[dbname][collection_name]
        projection = {
            "_id": 1, "store": 1, "product_id": 1, "name": 1, "price": 1,
            "catalog_id": 1,
            "availability": 1, "status": 1, "stock_status": 1,
            "availability_status": 1, "price_history": 1,
        }
        docs = []
        seen = set()
        for store, product_id in keys:
            document = col.find_one({"store": store, "product_id": product_id}, projection)
            if document is None:
                continue
            key = (store, product_id)
            if key in seen:
                continue
            seen.add(key)
            docs.append(document)
        client.close()
        return _enrich_docs_with_cyber_history(uri, dbname, docs)
    finally:
        repo.close()


def read_products_from_mongo(uri, dbname, collection_name, limit, min_history_days=30, include_cyber=True):
    try:
        from pymongo import MongoClient
    except Exception:
        raise
    client = MongoClient(uri)
    db = client[dbname]
    col = db[collection_name]
    minimum_index = max(0, int(min_history_days) - 1)
    query = {
        f"price_history.{minimum_index}": {"$exists": True},
        "store": {"$nin": [None, ""]},
        "product_id": {"$nin": [None, ""]},
        "price": {"$gt": 0},
    }
    projection = {
        "_id": 1, "store": 1, "product_id": 1, "name": 1, "price": 1,
        "catalog_id": 1,
        "availability": 1, "status": 1, "stock_status": 1,
        "availability_status": 1, "price_history": 1,
    }
    # Se examinan más candidatos porque al agrupar por día algunos historiales
    # con muchos registros pueden quedar bajo el mínimo requerido.
    candidate_cap = max(int(limit) * 50, 1000)
    docs = []
    seen_keys = set()
    # Primero: todos los productos de listas Cyber oct/junio 2026 (pronóstico experimental).
    if include_cyber:
        try:
            cyber_docs = read_cyber_products_from_mongo(
                uri, dbname, collection_name, min_history_days=min_history_days,
            )
            for item in cyber_docs:
                key = (
                    str(item.get("store") or "").strip().lower(),
                    str(item.get("product_id") or "").strip(),
                )
                if key in seen_keys or not key[0] or not key[1]:
                    continue
                seen_keys.add(key)
                docs.append(item)
        except Exception as exc:
            print("cyber forecast priority skipped:", exc)
    # El plan de la noche anterior permite dedicar primero la capacidad de
    # TimesFM a consultas volátiles o cercanas a una oportunidad. Si aún no
    # existe un plan, el comportamiento vuelve a ser el recorrido normal.
    try:
        priority_ids = [
            str(item.get("catalog_id") or "")
            for item in db["scrape_priorities"].find(
                {"score": {"$gte": 75}}, {"_id": 0, "catalog_id": 1}
            ).sort("score", -1).limit(500)
            if item.get("catalog_id")
        ]
        if priority_ids:
            for item in col.find({**query, "catalog_id": {"$in": priority_ids}}, projection).limit(candidate_cap):
                key = (
                    str(item.get("store") or "").strip().lower(),
                    str(item.get("product_id") or "").strip(),
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                docs.append(item)
                if len(docs) >= candidate_cap:
                    break
    except Exception:
        pass
    if len(docs) < candidate_cap:
        for item in col.find(query, projection).limit(candidate_cap):
            key = (
                str(item.get("store") or "").strip().lower(),
                str(item.get("product_id") or "").strip(),
            )
            if key in seen_keys:
                continue
            seen_keys.add(key)
            docs.append(item)
            if len(docs) >= candidate_cap:
                break
    client.close()
    return docs


SANTIAGO = ZoneInfo("America/Santiago")
OUT_OF_STOCK_WORDS = ("agotado", "sin stock")


def _parse_date(value):
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.datetime.fromtimestamp(value, tz=datetime.timezone.utc)
    elif value not in (None, ""):
        try:
            parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.timezone.utc)


def daily_series_from_price_history(ph):
    """Serie ordenada con la última observación válida de cada día en Chile."""
    rows = []
    entries = list(ph or [])
    if any(isinstance(item, dict) and item.get("price_basis") == "all_payment" for item in entries):
        entries = [
            item for item in entries
            if isinstance(item, dict) and item.get("price_basis") == "all_payment"
        ]
    for position, item in enumerate(entries):
        if isinstance(item, dict):
            date = item.get("scraped_at") or item.get("date") or item.get("fecha") or item.get("ts")
            price = item.get("price") or item.get("precio") or item.get("value")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            date, price = item[0], item[1]
        else:
            continue
        dt = _parse_date(date)
        try:
            price_f = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_f = None
        if dt is None or price_f is None or price_f <= 0:
            continue
        rows.append((dt, position, price_f))
    rows.sort(key=lambda item: (item[0], item[1]))
    by_day = {}
    for moment, _position, price in rows:
        by_day[moment.astimezone(SANTIAGO).date()] = (moment, price)
    return [
        {"date": day.isoformat(), "scraped_at": moment.isoformat(), "price": price}
        for day, (moment, price) in sorted(by_day.items())
    ]


def series_from_price_history(ph):
    """Compatibilidad: precios diarios ya limpios y ordenados."""
    return [item["price"] for item in daily_series_from_price_history(ph)]


def _out_of_stock(document):
    blob = " ".join(
        str(document.get(field) or "")
        for field in ("name", "availability", "status", "stock_status", "availability_status")
    ).lower()
    return any(word in blob for word in OUT_OF_STOCK_WORDS)


def prepare_product(document, min_history_days=30):
    store = str(document.get("store") or "").strip().lower()
    product_id = str(document.get("product_id") or "").strip()
    if not store or not product_id:
        return None, "missing_identity"
    if _out_of_stock(document):
        return None, "out_of_stock"
    daily = daily_series_from_price_history(document.get("price_history"))
    required = max(2, int(min_history_days))
    if len(daily) < required:
        return None, "not_enough_daily_points"
    first = datetime.date.fromisoformat(daily[0]["date"])
    last = datetime.date.fromisoformat(daily[-1]["date"])
    if (last - first).days < required - 1:
        return None, "history_span_too_short"
    return {
        "forecast_key": f"{store}:{product_id}",
        "store": store,
        "product_id": product_id,
        "source_document_id": str(document.get("_id") or ""),
        "name": str(document.get("name") or ""),
        "dates": [item["date"] for item in daily],
        "series": [float(item["price"]) for item in daily],
        "history_start": daily[0]["date"],
        "history_end": daily[-1]["date"],
        "observation_count": len(daily),
    }, None


def simulate_forecast(series_list, horizon):
    out = []
    for s in series_list:
        if len(s) == 0:
            out.append([0.0] * horizon)
        else:
            last = float(s[-1])
            out.append([last] * horizon)
    return out


def try_timesfm_forecast(series_list, horizon):
    from retail.timesfm_runtime import forecast_with_timesfm3

    return forecast_with_timesfm3(series_list, horizon)


def write_forecasts_to_mongo(uri, dbname, collection_name, forecasts_docs):
    try:
        from pymongo import MongoClient
    except Exception:
        raise
    client = MongoClient(uri)
    db = client[dbname]
    col = db[collection_name]
    col.create_index(
        [("forecast_key", 1), ("horizon", 1), ("model", 1)],
        unique=True,
        partialFilterExpression={"forecast_key": {"$type": "string"}},
        name="forecast_current_key",
    )
    for doc in forecasts_docs:
        col.replace_one(
            {"forecast_key": doc["forecast_key"], "horizon": doc["horizon"], "model": doc["model"]},
            doc,
            upsert=True,
        )
    try:
        from retail.forecast_outcomes import snapshot_forecast_docs
        from retail.mongo import ProductRepository

        repo = ProductRepository(uri, database=dbname)
        try:
            snapshot_forecast_docs(repo, forecasts_docs)
        finally:
            repo.close()
    except Exception as exc:
        print(f"forecast outcomes snapshot skipped: {exc}")
    client.close()


def main():
    args = parse_args()
    include_cyber = (
        args.include_cyber
        if args.include_cyber is not None
        else os.environ.get("FORECAST_INCLUDE_CYBER", "1") != "0"
    )
    docs = generate_forecasts(
        mongo_uri=args.mongo_uri,
        mongo_db=args.mongo_db,
        collection=args.collection,
        forecasts_collection=args.forecasts_collection,
        sample=args.sample,
        horizon=args.horizon,
        min_history_days=args.min_history_days,
        simulate=args.simulate,
        include_cyber=include_cyber,
    )
    # if docs were returned and not written, write to output
    if docs:
        now = datetime.datetime.utcnow()
        out_path = f"output/forecasts_simulated_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        os.makedirs("output", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, default=str, indent=2, ensure_ascii=False)
        print("Forecasts written to:", out_path)


def generate_forecasts(*, mongo_uri: str | None = None, mongo_db: str = "scraping", collection: str = "products", forecasts_collection: str = "forecasts", sample: int = 10, horizon: int = 30, simulate: bool = False, use_timesfm: bool | None = None, min_history_days: int = 30, include_cyber: bool = True) -> list[dict]:
    """Generate forecasts for a sample of products.

    If `mongo_uri` is provided and `simulate` is False, reads products from Mongo.
    If TimesFM is available, will attempt real forecasts unless `use_timesfm` is False.
    Returns the list of forecast documents. If writing to Mongo succeeds, returns an empty list.

    Con `include_cyber` (default), todos los productos elegibles de listas Cyber
    octubre/junio 2026 entran primero (historial enriquecido) y no cuentan contra
    el cupo `sample` del resto del catálogo.
    """
    products: list[dict] = []
    rejected = Counter()
    cyber_prepared = 0
    if not simulate and mongo_uri:
        docs = read_products_from_mongo(
            mongo_uri, mongo_db, collection, sample, min_history_days,
            include_cyber=include_cyber,
        )
        non_cyber_count = 0
        for document in docs:
            is_cyber = bool(
                document.get("_cyber_enriched") or document.get("_cyber_observation_count")
            )
            # Cupo `sample` solo limita productos fuera de Cyber; Cyber va completo.
            if not is_cyber and non_cyber_count >= sample:
                continue
            prepared, reason = prepare_product(document, min_history_days)
            if prepared is None:
                rejected[reason or "invalid"] += 1
                continue
            if is_cyber:
                prepared["cyber_observation_count"] = int(
                    document.get("_cyber_observation_count") or 0
                )
                prepared["cyber_list_ids"] = list(document.get("_cyber_list_ids") or [])
                prepared["source_tag"] = "cyber_day"
                cyber_prepared += 1
            else:
                prepared["source_tag"] = "timesfm_poc"
                non_cyber_count += 1
            products.append(prepared)
        print(
            f"Prepared {len(products)} products "
            f"(cyber={cyber_prepared}, other={non_cyber_count}); rejected: {dict(rejected)}"
        )

    if simulate:
        for i in range(sample):
            product_id = f"SIM-{i+1}"
            base = 100 + i * 5
            values = [base + (j * 0.5) for j in range(max(30, min_history_days))]
            products.append({
                "forecast_key": f"simulation:{product_id}", "store": "simulation",
                "product_id": product_id, "source_document_id": "", "name": product_id,
                "dates": [], "series": values, "history_start": None, "history_end": None,
                "observation_count": len(values),
            })

    if not products:
        print("No products met the data-quality requirements; no forecasts were generated.")
        return []
    series_list = [item["series"] for item in products]

    # run forecast
    forecasts = None
    quantiles = None
    model_used = "simulated"
    want_timesfm = False if use_timesfm is False else (use_timesfm if use_timesfm is not None else (not simulate))
    if want_timesfm:
        try:
            forecasts, quantiles = try_timesfm_forecast(series_list, horizon)
            model_used = "timesfm"
        except Exception as e:
            print("TimesFM failed; using the last-price baseline. Error:", e)
            forecasts = simulate_forecast(series_list, horizon)
            quantiles = None
            model_used = "last_value_baseline"
    else:
        forecasts = simulate_forecast(series_list, horizon)

    now = datetime.datetime.utcnow()
    docs: list[dict] = []
    for i, product in enumerate(products):
        source = product.get("source_tag") or "timesfm_poc"
        metadata = {
            "source": source,
            "frequency": "daily",
            "timezone": "America/Santiago",
            "observation_count": product["observation_count"],
            "history_start": product["history_start"],
            "history_end": product["history_end"],
            "minimum_history_days": min_history_days,
            "one_observation_per_day": True,
        }
        if product.get("cyber_observation_count"):
            metadata["cyber_observation_count"] = product["cyber_observation_count"]
            metadata["cyber_list_ids"] = product.get("cyber_list_ids") or []
        doc = {
            "forecast_key": product["forecast_key"],
            "store": product["store"],
            "product_id": product["product_id"],
            "source_document_id": product["source_document_id"],
            "name": product["name"],
            "horizon": horizon,
            "generated_at": now,
            "model": model_used,
            "point_forecast": forecasts[i],
            "quantiles": quantiles[i] if quantiles is not None else {},
            "metadata": metadata,
        }
        docs.append(doc)

    if not simulate and mongo_uri:
        try:
            write_forecasts_to_mongo(mongo_uri, mongo_db, forecasts_collection, docs)
            print(f"Wrote {len(docs)} forecasts to Mongo collection '{forecasts_collection}' in DB '{mongo_db}'")
            return []
        except Exception as e:
            print("Failed to write to Mongo, returning docs. Error:", e)
            return docs

    return docs


if __name__ == "__main__":
    main()
