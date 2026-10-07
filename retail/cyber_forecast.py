"""Une el historial Cyber (`cyber_day_price_history`) con el pronóstico experimental.

Las listas objetivo (octubre 2026 y junio 2026) se resuelven por slug/nombre con
tolerancia a variantes (`cyber_oct2026`, `cyber_octubre2026`, etc.). Las
observaciones de mejor precio se vuelcan al `price_history` del producto de
catálogo y priorizan la generación TimesFM / baseline.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.mongo import HISTORY_LIMIT, should_record

# Slugs conocidos + patrones tolerantes (nombre/título/slug).
KNOWN_FORECAST_CYBER_SLUGS = (
    "cyber_oct2026",
    "cyber_octubre2026",
    "cyber_octubre_2026",
    "cyber_junio2026",
    "cyber_jun2026",
    "cyber_junio_2026",
)
_FORECAST_LIST_PATTERNS = (
    re.compile(r"cyber.*(?:oct|octubre).*(?:2026|26)", re.I),
    re.compile(r"cyber.*(?:jun|junio).*(?:2026|26)", re.I),
)

# Si un producto acumula tantos puntos Cyber y aún no hay pronóstico, se fuerza
# un intento de generación (baseline en el worker; TimesFM en el cron BMAX).
MANY_CYBER_CHANGES = max(3, int(os.environ.get("CYBER_FORECAST_MANY_CHANGES") or "5"))
CYBER_FORECAST_MIN_HISTORY_DAYS = max(
    7, int(os.environ.get("CYBER_FORECAST_MIN_HISTORY_DAYS") or "30")
)
CYBER_FORECAST_REFRESH_HOURS = max(
    1, int(os.environ.get("CYBER_FORECAST_REFRESH_HOURS") or "12")
)
CYBER_FORECAST_HORIZON = max(1, int(os.environ.get("CYBER_FORECAST_HORIZON") or "7"))

# Ventana Cyber (~3 días): basta con muchas observaciones/vueltas del mismo día
# para un horizonte corto + consejo comprar/esperar, sin exigir 30 días calendario.
CYBER_EVENT_DAYS = max(1, int(os.environ.get("CYBER_EVENT_DAYS") or "3"))
CYBER_EVENT_HORIZON = max(1, int(os.environ.get("CYBER_EVENT_HORIZON") or str(CYBER_EVENT_DAYS)))
CYBER_FORECAST_MIN_OBSERVATIONS = max(
    3, int(os.environ.get("CYBER_FORECAST_MIN_OBSERVATIONS") or "3")
)
CYBER_EVENT_REFRESH_HOURS = max(
    1, int(os.environ.get("CYBER_EVENT_REFRESH_HOURS") or "2")
)
CYBER_EVENT_MODEL = "cyber_event_trend"
CYBER_BUY_DROP_THRESHOLD_PCT = float(os.environ.get("CYBER_BUY_DROP_THRESHOLD_PCT") or "2")
CYBER_BUY_NEAR_LOW_PCT = float(os.environ.get("CYBER_BUY_NEAR_LOW_PCT") or "2")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm_store(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_product_id(value: Any) -> str:
    return str(value or "").strip()


def _as_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            return None
    return number if number > 0 else None


def _day_key(moment: datetime | None) -> str:
    from retail.pricing import santiago_day

    return santiago_day(moment or _now()).isoformat()


def matches_forecast_cyber_list(slug: str, name: str = "", title: str = "") -> bool:
    """True si la lista es Cyber octubre 2026 o junio 2026 (o alias cercano)."""
    key = str(slug or "").strip().lower()
    if not key:
        return False
    if key in {item.lower() for item in KNOWN_FORECAST_CYBER_SLUGS}:
        return True
    blob = " ".join(part for part in (key, name, title) if part)
    return any(pattern.search(blob) for pattern in _FORECAST_LIST_PATTERNS)


def forecast_cyber_list_ids(repo: Any) -> list[str]:
    """Lista de slugs Cyber a incluir en el pronóstico experimental."""
    from retail.cyber_day import ensure_default_list, list_all_lists, products_count

    ensure_default_list(repo)
    found: list[str] = []
    seen: set[str] = set()
    for meta in list_all_lists(repo):
        slug = str(meta.get("slug") or meta.get("list_id") or "").strip()
        if not slug or slug in seen:
            continue
        if matches_forecast_cyber_list(
            slug,
            name=str(meta.get("name") or ""),
            title=str(meta.get("title") or ""),
        ):
            found.append(slug)
            seen.add(slug)
    for slug in KNOWN_FORECAST_CYBER_SLUGS:
        if slug in seen:
            continue
        try:
            if products_count(repo, slug) > 0:
                found.append(slug)
                seen.add(slug)
        except Exception:
            continue
    return found


def _match_keys_from_last_matches(last_matches: Any) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if isinstance(last_matches, dict):
        for raw_key in last_matches:
            text = str(raw_key or "")
            if ":" not in text:
                continue
            store, product_id = text.split(":", 1)
            store_n = _norm_store(store)
            product_n = _norm_product_id(product_id)
            if store_n and product_n:
                keys.append((store_n, product_n))
    return keys


def cyber_product_keys(repo: Any, list_ids: list[str] | None = None) -> list[tuple[str, str]]:
    """Identidades `store:product_id` vistas en las listas Cyber objetivo."""
    from retail.cyber_day import history_collection, products_collection, resolve_list_id

    lids = list(list_ids or forecast_cyber_list_ids(repo))
    if not lids:
        return []
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []

    def _add(store: str, product_id: str) -> None:
        key = (_norm_store(store), _norm_product_id(product_id))
        if not key[0] or not key[1] or key in seen:
            return
        seen.add(key)
        ordered.append(key)

    coll = products_collection(repo)
    for lid in lids:
        resolved = resolve_list_id(repo, lid)
        for item in coll.find(
            {"list_id": resolved},
            {"last_matches": 1, "best_store": 1, "last_product_id": 1, "n": 1},
        ):
            for store, product_id in _match_keys_from_last_matches(item.get("last_matches")):
                _add(store, product_id)
            # Algunos resúmenes guardan el ganador aparte.
            _add(str(item.get("best_store") or ""), str(item.get("last_product_id") or ""))

    history = history_collection(repo)
    for row in history.find(
        {"list_id": {"$in": lids}, "product_id": {"$nin": [None, ""]}, "store": {"$nin": [None, ""]}},
        {"store": 1, "product_id": 1},
    ):
        _add(str(row.get("store") or ""), str(row.get("product_id") or ""))
    return ordered


def cyber_history_points_for_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Puntos Cyber compatibles con `price_history` (último precio del producto ese instante)."""
    from retail.cyber_day import history_collection

    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    if not store_n or not product_n:
        return []
    lids = list(list_ids or forecast_cyber_list_ids(repo))
    if not lids:
        return []
    query = {
        "list_id": {"$in": lids},
        "product_id": product_n,
        "$or": [
            {"store": store_n},
            {"store": store},
            {"store": {"$regex": f"^{re.escape(store_n)}$", "$options": "i"}},
        ],
    }
    points: list[dict[str, Any]] = []
    for row in history_collection(repo).find(query).sort([("at", 1)]):
        price = _as_int(row.get("price"))
        if price is None:
            continue
        at = row.get("at")
        if not isinstance(at, datetime):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        normal = _as_int(row.get("price_normal"))
        points.append({
            "price": price,
            "price_offer": price,
            "price_normal": normal,
            "price_basis": "all_payment",
            "scraped_at": at,
            "source": "cyber_day",
            "cyber_list_id": row.get("list_id"),
            "cyber_n": row.get("n"),
            "cyber_day": row.get("day"),
        })
    return points


def merge_price_history_with_cyber(
    price_history: list[dict[str, Any]] | None,
    cyber_points: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Fusiona historial de catálogo + Cyber; el más reciente del día gana."""
    merged = [dict(item) for item in (price_history or []) if isinstance(item, dict)]
    for point in cyber_points or []:
        if isinstance(point, dict):
            merged.append(dict(point))
    return merged


def feed_cyber_observation_to_product_history(
    repo: Any,
    observation: dict[str, Any] | None,
) -> bool:
    """Empuja un punto Cyber al `price_history` del producto de catálogo."""
    if not observation:
        return False
    store = _norm_store(observation.get("store"))
    product_id = _norm_product_id(observation.get("product_id"))
    price = _as_int(observation.get("price"))
    if not store or not product_id or price is None:
        return False
    coll = getattr(repo, "collection", None)
    if coll is None:
        return False

    at = observation.get("at")
    if not isinstance(at, datetime):
        at = _now()
    elif at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    day = str(observation.get("day") or _day_key(at))
    price_normal = _as_int(observation.get("price_normal"))

    previous = None
    if hasattr(repo, "last_points"):
        previous = repo.last_points([(store, product_id)]).get((store, product_id))
    if previous is None:
        # Fallback si el repo de prueba no implementa last_points.
        doc = coll.find_one(
            {"store": store, "product_id": product_id},
            {"price_history": {"$slice": -1}},
        ) or coll.find_one(
            {"store": {"$regex": f"^{re.escape(store)}$", "$options": "i"}, "product_id": product_id},
            {"price_history": {"$slice": -1}, "store": 1},
        )
        if doc:
            store = _norm_store(doc.get("store") or store)
            points = doc.get("price_history") or []
            if points:
                last = points[-1]
                previous = (
                    last.get("price"),
                    _day_key(last.get("scraped_at")) if isinstance(last.get("scraped_at"), datetime)
                    else str(last.get("scraped_at") or "")[:10],
                    last.get("price_normal"),
                )
    if not should_record(previous, price, day, price_normal):
        return False

    point = {
        "price": price,
        "price_offer": price,
        "price_normal": price_normal,
        "price_basis": "all_payment",
        "scraped_at": at,
        "source": "cyber_day",
        "cyber_list_id": observation.get("list_id"),
        "cyber_n": observation.get("n"),
        "cyber_day": day,
        "search_query": observation.get("query"),
    }
    update = {
        "$set": {
            "price": price,
            "updated_at": _now(),
        },
        "$push": {"price_history": {"$each": [point], "$slice": -HISTORY_LIMIT}},
    }
    if price_normal is not None:
        update["$set"]["price_normal"] = price_normal
    result = coll.update_one(
        {"store": store, "product_id": product_id},
        update,
    )
    if result.matched_count == 0:
        result = coll.update_one(
            {
                "store": {"$regex": f"^{re.escape(store)}$", "$options": "i"},
                "product_id": product_id,
            },
            update,
        )
    return bool(result.matched_count)


def cyber_change_count(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
) -> int:
    from retail.cyber_day import history_collection

    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    lids = list(list_ids or forecast_cyber_list_ids(repo))
    if not store_n or not product_n or not lids:
        return 0
    return int(
        history_collection(repo).count_documents({
            "list_id": {"$in": lids},
            "product_id": product_n,
            "$or": [
                {"store": store_n},
                {"store": {"$regex": f"^{re.escape(store_n)}$", "$options": "i"}},
            ],
        })
    )


def latest_forecast(repo: Any, store: str, product_id: str) -> dict[str, Any] | None:
    forecasts = getattr(repo, "forecasts", None)
    if forecasts is None and hasattr(repo, "db"):
        forecasts = repo.db["forecasts"]
    if forecasts is None:
        return None
    key = f"{_norm_store(store)}:{_norm_product_id(product_id)}"
    return forecasts.find_one(
        {"forecast_key": key, "model": {"$ne": "simulated"}},
        sort=[("generated_at", -1)],
    )


def _forecast_is_fresh(doc: dict[str, Any] | None, *, hours: int = CYBER_FORECAST_REFRESH_HOURS) -> bool:
    if not doc:
        return False
    generated = doc.get("generated_at") or doc.get("created_at")
    if not isinstance(generated, datetime):
        return False
    if generated.tzinfo is None:
        generated = generated.replace(tzinfo=timezone.utc)
    return generated >= _now() - timedelta(hours=hours)


def _is_cyber_event_forecast(doc: dict[str, Any] | None) -> bool:
    if not doc:
        return False
    if str(doc.get("model") or "") == CYBER_EVENT_MODEL:
        return True
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return str(metadata.get("mode") or "") == "cyber_event"


def _linear_slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    return numerator / denominator if denominator else 0.0


def cyber_distinct_days(cyber_points: list[dict[str, Any]]) -> list[str]:
    days: list[str] = []
    seen: set[str] = set()
    for point in cyber_points:
        day = str(point.get("cyber_day") or "").strip()
        if not day:
            at = point.get("scraped_at")
            if isinstance(at, datetime):
                day = _day_key(at)
        if day and day not in seen:
            seen.add(day)
            days.append(day)
    return days


def remaining_cyber_horizon(cyber_points: list[dict[str, Any]], *, event_days: int = CYBER_EVENT_DAYS) -> int:
    """Días restantes de la ventana Cyber (1..event_days) según días distintos observados."""
    distinct = len(cyber_distinct_days(cyber_points))
    if distinct <= 0:
        return max(1, event_days)
    # Día actual cuenta como en curso: proyectamos el resto de la ventana.
    remaining = event_days - distinct + 1
    return max(1, min(event_days, remaining))


def project_cyber_event_prices(
    prices: list[float],
    *,
    horizon: int,
    span_seconds: float,
) -> list[float]:
    """Proyecta precios día a día en la ventana Cyber a partir de la pendiente por observación."""
    if not prices:
        return [0.0] * horizon
    last = float(prices[-1])
    if len(prices) < 2:
        return [last] * horizon
    slope_per_obs = _linear_slope(prices)
    # Escala: cuántas observaciones equivalen a ~1 día calendario Cyber.
    span_days = max(span_seconds / 86400.0, 1.0 / 24.0)  # mínimo ~1 hora
    obs_per_day = max(len(prices) / span_days, 1.0)
    daily_delta = slope_per_obs * obs_per_day
    projected: list[float] = []
    for step in range(1, horizon + 1):
        value = last + daily_delta * step
        projected.append(max(1.0, round(value, 2)))
    return projected


def cyber_buy_advice(
    *,
    current: float,
    prices: list[float],
    point_forecast: list[float],
) -> dict[str, Any]:
    """Consejo comprar / esperar / observar según trayectoria Cyber del evento."""
    if current <= 0 or not prices:
        return {
            "advice": "observar",
            "label": "Sin señal clara",
            "reason": "Aún no hay precios Cyber suficientes para opinar.",
        }
    cyber_low = min(prices)
    cyber_high = max(prices)
    expected = sum(point_forecast) / len(point_forecast) if point_forecast else current
    change_pct = ((expected - current) * 100 / current) if current else 0.0
    near_low = cyber_low > 0 and (current - cyber_low) * 100 / cyber_low <= CYBER_BUY_NEAR_LOW_PCT
    at_low = current <= cyber_low

    if change_pct <= -CYBER_BUY_DROP_THRESHOLD_PCT:
        return {
            "advice": "esperar",
            "label": "Mejor esperar",
            "reason": (
                f"En la ventana Cyber (~{CYBER_EVENT_DAYS} días) la trayectoria apunta a una baja "
                f"de cerca de {abs(round(change_pct, 1))}%. Conviene esperar al día Cyber que viene."
            ),
            "expected_change_percent": round(change_pct, 1),
            "cyber_low": round(cyber_low),
            "cyber_high": round(cyber_high),
        }
    if at_low or near_low:
        return {
            "advice": "comprar",
            "label": "Conviene comprar",
            "reason": (
                "Está en el mínimo visto en este Cyber."
                if at_low
                else (
                    f"Está a un {round((current - cyber_low) * 100 / cyber_low, 1)}% "
                    "del mínimo visto en este Cyber."
                )
            ),
            "expected_change_percent": round(change_pct, 1),
            "cyber_low": round(cyber_low),
            "cyber_high": round(cyber_high),
        }
    if change_pct >= CYBER_BUY_DROP_THRESHOLD_PCT:
        return {
            "advice": "comprar",
            "label": "Conviene comprar",
            "reason": (
                f"La trayectoria Cyber apunta a un alza de cerca de {round(change_pct, 1)}% "
                "en los días que quedan del evento."
            ),
            "expected_change_percent": round(change_pct, 1),
            "cyber_low": round(cyber_low),
            "cyber_high": round(cyber_high),
        }
    return {
        "advice": "observar",
        "label": "Sin señal clara",
        "reason": (
            "En este Cyber el precio se ve estable frente a lo proyectado para los días restantes. "
            "Revisa otra vuelta o el mínimo del evento."
        ),
        "expected_change_percent": round(change_pct, 1),
        "cyber_low": round(cyber_low),
        "cyber_high": round(cyber_high),
    }


def prepare_cyber_event_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
    min_observations: int = CYBER_FORECAST_MIN_OBSERVATIONS,
) -> tuple[dict[str, Any] | None, str | None]:
    """Serie densa de vueltas Cyber (sin exigir 30 días calendario) para horizonte corto."""
    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    coll = getattr(repo, "collection", None)
    if coll is None or not store_n or not product_n:
        return None, "missing_identity"

    document = coll.find_one({"store": store_n, "product_id": product_n})
    if document is None:
        document = coll.find_one({
            "store": {"$regex": f"^{re.escape(store_n)}$", "$options": "i"},
            "product_id": product_n,
        })
    if document is None:
        return None, "product_not_found"

    lids = list(list_ids or forecast_cyber_list_ids(repo))
    cyber_points = cyber_history_points_for_product(repo, store_n, product_n, list_ids=lids)
    if len(cyber_points) < min_observations:
        return None, "not_enough_cyber_observations"

    prices = [float(point["price"]) for point in cyber_points]
    times = [point["scraped_at"] for point in cyber_points if isinstance(point.get("scraped_at"), datetime)]
    first_at = times[0] if times else _now()
    last_at = times[-1] if times else _now()
    span_seconds = max(0.0, (last_at - first_at).total_seconds())
    horizon = remaining_cyber_horizon(cyber_points)
    point_forecast = project_cyber_event_prices(prices, horizon=horizon, span_seconds=span_seconds)
    current = prices[-1]
    advice = cyber_buy_advice(current=current, prices=prices, point_forecast=point_forecast)
    distinct_days = cyber_distinct_days(cyber_points)

    return {
        "forecast_key": f"{store_n}:{product_n}",
        "store": store_n,
        "product_id": product_n,
        "source_document_id": str(document.get("_id") or ""),
        "name": str(document.get("name") or ""),
        "dates": [at.isoformat() if hasattr(at, "isoformat") else str(at) for at in times],
        "series": prices,
        "history_start": first_at.date().isoformat() if hasattr(first_at, "date") else str(first_at)[:10],
        "history_end": last_at.date().isoformat() if hasattr(last_at, "date") else str(last_at)[:10],
        "observation_count": len(prices),
        "cyber_observation_count": len(cyber_points),
        "cyber_list_ids": lids,
        "cyber_distinct_days": distinct_days,
        "cyber_span_seconds": span_seconds,
        "point_forecast": point_forecast,
        "horizon": horizon,
        "buy_advice": advice,
        "mode": "cyber_event",
    }, None


def prepare_cyber_enriched_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
    min_history_days: int = CYBER_FORECAST_MIN_HISTORY_DAYS,
) -> tuple[dict[str, Any] | None, str | None]:
    """Carga el producto, mezcla historial Cyber y prepara la serie de forecast."""
    from timesfm_poc.forecast_from_mongo import prepare_product

    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    coll = getattr(repo, "collection", None)
    if coll is None or not store_n or not product_n:
        return None, "missing_identity"
    document = coll.find_one({"store": store_n, "product_id": product_n})
    if document is None:
        document = coll.find_one({
            "store": {"$regex": f"^{re.escape(store_n)}$", "$options": "i"},
            "product_id": product_n,
        })
    if document is None:
        return None, "product_not_found"

    lids = list(list_ids or forecast_cyber_list_ids(repo))
    cyber_points = cyber_history_points_for_product(repo, store_n, product_n, list_ids=lids)
    enriched = dict(document)
    enriched["store"] = _norm_store(enriched.get("store") or store_n)
    enriched["product_id"] = _norm_product_id(enriched.get("product_id") or product_n)
    enriched["price_history"] = merge_price_history_with_cyber(
        enriched.get("price_history"),
        cyber_points,
    )
    prepared, reason = prepare_product(enriched, min_history_days)
    if prepared is None:
        return None, reason or "invalid"
    prepared["cyber_observation_count"] = len(cyber_points)
    prepared["cyber_list_ids"] = lids
    return prepared, None


def write_forecast_docs(repo: Any, docs: list[dict[str, Any]]) -> int:
    if not docs:
        return 0
    forecasts = getattr(repo, "forecasts", None)
    if forecasts is None and hasattr(repo, "db"):
        forecasts = repo.db["forecasts"]
    if forecasts is None:
        return 0
    written = 0
    for doc in docs:
        forecasts.replace_one(
            {
                "forecast_key": doc["forecast_key"],
                "horizon": doc["horizon"],
                "model": doc["model"],
            },
            doc,
            upsert=True,
        )
        written += 1
    return written


def build_forecast_document(
    prepared: dict[str, Any],
    *,
    horizon: int = CYBER_FORECAST_HORIZON,
    model: str = "last_value_baseline",
    point_forecast: list[float] | None = None,
    quantiles: dict[str, Any] | None = None,
    min_history_days: int = CYBER_FORECAST_MIN_HISTORY_DAYS,
) -> dict[str, Any]:
    series = [float(value) for value in prepared.get("series") or []]
    last = series[-1] if series else 0.0
    points = point_forecast if point_forecast is not None else [last] * horizon
    mode = str(prepared.get("mode") or "daily")
    is_event = mode == "cyber_event"
    metadata: dict[str, Any] = {
        "source": "cyber_day",
        "mode": mode,
        "frequency": "intra_event" if is_event else "daily",
        "timezone": "America/Santiago",
        "observation_count": prepared.get("observation_count"),
        "history_start": prepared.get("history_start"),
        "history_end": prepared.get("history_end"),
        "minimum_history_days": 0 if is_event else min_history_days,
        "one_observation_per_day": not is_event,
        "cyber_observation_count": prepared.get("cyber_observation_count") or 0,
        "cyber_list_ids": prepared.get("cyber_list_ids") or [],
        "cyber_event_days": CYBER_EVENT_DAYS if is_event else None,
        "cyber_distinct_days": prepared.get("cyber_distinct_days") or [],
        "cyber_span_seconds": prepared.get("cyber_span_seconds"),
        "buy_advice": prepared.get("buy_advice"),
    }
    return {
        "forecast_key": prepared["forecast_key"],
        "store": prepared["store"],
        "product_id": prepared["product_id"],
        "source_document_id": prepared.get("source_document_id") or "",
        "name": prepared.get("name") or "",
        "horizon": horizon,
        "generated_at": _now(),
        "model": model,
        "point_forecast": points,
        "quantiles": quantiles or {},
        "metadata": metadata,
        "buy_advice": prepared.get("buy_advice"),
    }


def _write_cyber_event_forecast(
    repo: Any,
    prepared: dict[str, Any],
    *,
    changes: int,
) -> dict[str, Any]:
    horizon = int(prepared.get("horizon") or CYBER_EVENT_HORIZON)
    points = list(prepared.get("point_forecast") or [])
    if len(points) != horizon:
        prices = [float(value) for value in prepared.get("series") or []]
        points = project_cyber_event_prices(
            prices,
            horizon=horizon,
            span_seconds=float(prepared.get("cyber_span_seconds") or 0.0),
        )
    doc = build_forecast_document(
        prepared,
        horizon=horizon,
        model=CYBER_EVENT_MODEL,
        point_forecast=points,
        min_history_days=0,
    )
    write_forecast_docs(repo, [doc])
    advice = prepared.get("buy_advice") or {}
    return {
        "ok": True,
        "action": "written",
        "forecast_key": doc["forecast_key"],
        "model": CYBER_EVENT_MODEL,
        "mode": "cyber_event",
        "observation_count": prepared.get("observation_count"),
        "cyber_changes": changes,
        "cyber_observation_count": prepared.get("cyber_observation_count") or 0,
        "horizon": horizon,
        "buy_advice": advice.get("advice"),
    }


def ensure_forecast_for_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
    min_history_days: int = CYBER_FORECAST_MIN_HISTORY_DAYS,
    horizon: int = CYBER_FORECAST_HORIZON,
    use_timesfm: bool = False,
    force: bool = False,
    many_changes_threshold: int = MANY_CYBER_CHANGES,
    prefer_cyber_event: bool = True,
) -> dict[str, Any]:
    """Genera/actualiza pronóstico: diario (≥30 días) o Cyber-evento (vueltas densas)."""
    lids = list(list_ids or forecast_cyber_list_ids(repo))
    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    changes = cyber_change_count(repo, store_n, product_n, list_ids=lids)
    existing = latest_forecast(repo, store_n, product_n)
    refresh_hours = (
        CYBER_EVENT_REFRESH_HOURS
        if _is_cyber_event_forecast(existing) or prefer_cyber_event
        else CYBER_FORECAST_REFRESH_HOURS
    )
    if existing and _forecast_is_fresh(existing, hours=refresh_hours) and not force:
        return {
            "ok": True,
            "action": "fresh",
            "forecast_key": f"{store_n}:{product_n}",
            "cyber_changes": changes,
            "model": existing.get("model"),
            "mode": "cyber_event" if _is_cyber_event_forecast(existing) else "daily",
        }

    # Intentar si: force, muchos cambios Cyber, no hay forecast, o el vigente está viejo.
    needs_check = (
        force
        or changes >= many_changes_threshold
        or changes >= CYBER_FORECAST_MIN_OBSERVATIONS
        or existing is None
        or not _forecast_is_fresh(existing, hours=refresh_hours)
    )
    if not needs_check:
        return {
            "ok": True,
            "action": "skip",
            "forecast_key": f"{store_n}:{product_n}",
            "cyber_changes": changes,
            "has_forecast": existing is not None,
        }

    # 1) Camino Cyber-evento primero: muchas vueltas / puntos del mismo día bastan
    # (sin depender de timesfm_poc ni de 30 días calendario).
    event_block_reason = None
    if prefer_cyber_event:
        event_prepared, event_reason = prepare_cyber_event_product(
            repo,
            store_n,
            product_n,
            list_ids=lids,
        )
        if event_prepared is not None:
            return _write_cyber_event_forecast(repo, event_prepared, changes=changes)
        event_block_reason = event_reason

    # 2) Camino diario clásico (TimesFM / baseline con ≥30 días).
    prepared = None
    reason = event_block_reason or "invalid"
    try:
        prepared, reason = prepare_cyber_enriched_product(
            repo,
            store_n,
            product_n,
            list_ids=lids,
            min_history_days=min_history_days,
        )
    except ModuleNotFoundError as exc:
        # En web/cyber-worker a veces no está timesfm_poc; el camino evento ya cubrió el gap.
        reason = event_block_reason or f"daily_prepare_unavailable:{exc.name or 'module'}"
        prepared = None
    if prepared is None:
        return {
            "ok": False,
            "action": "blocked",
            "reason": event_block_reason or reason or "invalid",
            "forecast_key": f"{store_n}:{product_n}",
            "cyber_changes": changes,
            "has_forecast": existing is not None,
        }

    model = "last_value_baseline"
    point_forecast = None
    quantiles = None
    if use_timesfm:
        try:
            from timesfm_poc.forecast_from_mongo import try_timesfm_forecast

            points, qmap = try_timesfm_forecast([prepared["series"]], horizon)
            point_forecast = points[0]
            quantiles = (qmap or [None])[0] or {}
            model = "timesfm"
        except Exception as exc:
            print(f"cyber-forecast: TimesFM falló {store_n}/{product_n}: {exc}", flush=True)

    doc = build_forecast_document(
        prepared,
        horizon=horizon,
        model=model,
        point_forecast=point_forecast,
        quantiles=quantiles,
        min_history_days=min_history_days,
    )
    write_forecast_docs(repo, [doc])
    return {
        "ok": True,
        "action": "written",
        "forecast_key": doc["forecast_key"],
        "model": model,
        "mode": "daily",
        "observation_count": prepared.get("observation_count"),
        "cyber_changes": changes,
        "cyber_observation_count": prepared.get("cyber_observation_count") or 0,
    }


def ensure_cyber_list_forecasts(
    repo: Any,
    *,
    list_id: str | None = None,
    use_timesfm: bool = False,
    force: bool = False,
    limit: int | None = None,
    prefer_cyber_event: bool = True,
) -> dict[str, Any]:
    """Recorre productos de las listas Cyber objetivo y asegura pronóstico experimental."""
    if list_id:
        lids = [str(list_id).strip()] if matches_forecast_cyber_list(str(list_id).strip()) else []
        if not lids:
            # Permite forzar una lista concreta aunque el nombre no matchee el patrón.
            lids = [str(list_id).strip()]
    else:
        lids = forecast_cyber_list_ids(repo)
    keys = cyber_product_keys(repo, lids)
    if limit is not None:
        keys = keys[: max(0, int(limit))]
    stats = {
        "ok": True,
        "list_ids": lids,
        "candidates": len(keys),
        "written": 0,
        "written_cyber_event": 0,
        "fresh": 0,
        "blocked": 0,
        "missing_forecast_with_many_changes": 0,
        "results": [],
    }
    for store, product_id in keys:
        try:
            result = ensure_forecast_for_product(
                repo,
                store,
                product_id,
                list_ids=lids,
                use_timesfm=use_timesfm,
                force=force,
                prefer_cyber_event=prefer_cyber_event,
            )
        except Exception as exc:
            result = {
                "ok": False,
                "action": "blocked",
                "reason": f"error:{exc}",
                "forecast_key": f"{store}:{product_id}",
                "has_forecast": False,
            }
        action = result.get("action")
        if action == "written":
            stats["written"] += 1
            if result.get("mode") == "cyber_event" or result.get("model") == CYBER_EVENT_MODEL:
                stats["written_cyber_event"] += 1
        elif action == "fresh":
            stats["fresh"] += 1
        elif action == "blocked":
            stats["blocked"] += 1
            if int(result.get("cyber_changes") or 0) >= MANY_CYBER_CHANGES and not result.get("has_forecast"):
                stats["missing_forecast_with_many_changes"] += 1
        stats["results"].append(result)
    return stats


def record_cyber_lap_samples(
    repo: Any,
    list_id: str,
    lap: int,
    *,
    at: datetime | None = None,
) -> dict[str, Any]:
    """Al cerrar una vuelta: una muestra de precio por producto aunque no haya cambiado.

    El historial Cyber solo guarda cambios; sin muestras por vuelta el pronóstico de
    evento no ve las ~50–70 vueltas si el precio se mantiene. Una fila por
    (list_id, n, day, lap) alimenta la serie densa del camino cyber_event.
    """
    from retail.cyber_day import history_collection, products_collection, resolve_list_id

    lid = resolve_list_id(repo, list_id)
    if not matches_forecast_cyber_list(lid):
        return {"ok": True, "skipped": True, "reason": "list_not_in_forecast_scope", "inserted": 0}
    moment = at or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    day = _day_key(moment)
    lap_n = max(0, int(lap or 0))
    coll = history_collection(repo)
    inserted = 0
    fed = 0
    for item in products_collection(repo).find({"list_id": lid}):
        price = _as_int(item.get("last_price"))
        if price is None:
            continue
        try:
            query_n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        store = _norm_store(item.get("best_store"))
        product_id = _norm_product_id(item.get("last_product_id"))
        if not store or not product_id:
            for match_store, match_pid in _match_keys_from_last_matches(item.get("last_matches")):
                store = store or match_store
                product_id = product_id or match_pid
                break
        if not store or not product_id:
            continue
        existing = coll.find_one({
            "list_id": lid,
            "n": query_n,
            "day": day,
            "lap": lap_n,
            "kind": "lap_sample",
        })
        if existing is not None:
            continue
        price_normal = _as_int(item.get("last_price_normal"))
        doc = {
            "list_id": lid,
            "n": query_n,
            "query": str(item.get("query") or "").strip(),
            "day": day,
            "at": moment,
            "price": price,
            "price_normal": price_normal,
            "store": store,
            "product_id": product_id,
            "name": str(item.get("name") or item.get("query") or "").strip() or None,
            "kind": "lap_sample",
            "lap": lap_n,
        }
        try:
            coll.insert_one(doc)
            inserted += 1
        except Exception as exc:
            print(f"cyber-forecast: lap sample falló n={query_n}: {exc}", flush=True)
            continue
        if feed_cyber_observation_to_product_history(repo, doc):
            fed += 1
    return {
        "ok": True,
        "list_id": lid,
        "lap": lap_n,
        "day": day,
        "inserted": inserted,
        "fed_history": fed,
    }


def maybe_refresh_after_cyber_observation(
    repo: Any,
    observation: dict[str, Any] | None,
    *,
    use_timesfm: bool = False,
) -> dict[str, Any] | None:
    """Tras registrar un cambio Cyber: alimenta historial y revisa pronóstico si aplica."""
    if not observation:
        return None
    fed = feed_cyber_observation_to_product_history(repo, observation)
    store = _norm_store(observation.get("store"))
    product_id = _norm_product_id(observation.get("product_id"))
    if not store or not product_id:
        return {"fed_history": fed, "forecast": None}
    lids = forecast_cyber_list_ids(repo)
    observation_list = str(observation.get("list_id") or "").strip()
    if observation_list and observation_list not in lids and matches_forecast_cyber_list(observation_list):
        lids = [*lids, observation_list]
    changes = cyber_change_count(repo, store, product_id, list_ids=lids)
    existing = latest_forecast(repo, store, product_id)
    refresh_hours = (
        CYBER_EVENT_REFRESH_HOURS
        if _is_cyber_event_forecast(existing) or changes >= CYBER_FORECAST_MIN_OBSERVATIONS
        else CYBER_FORECAST_REFRESH_HOURS
    )
    should_ensure = (
        changes >= MANY_CYBER_CHANGES
        or changes >= CYBER_FORECAST_MIN_OBSERVATIONS
        or (existing is not None and not _forecast_is_fresh(existing, hours=refresh_hours))
    )
    forecast_result = None
    if should_ensure:
        forecast_result = ensure_forecast_for_product(
            repo,
            store,
            product_id,
            list_ids=lids or None,
            use_timesfm=use_timesfm,
            force=changes >= CYBER_FORECAST_MIN_OBSERVATIONS and (
                existing is None or not _is_cyber_event_forecast(existing)
            ),
            prefer_cyber_event=True,
        )
    return {"fed_history": fed, "cyber_changes": changes, "forecast": forecast_result}
