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
CYBER_DENSE_MODEL = "cyber_event_dense"
CYBER_FUTURE_MODEL = "cyber_future_transfer"
CYBER_BUCKET_MINUTES = max(5, int(os.environ.get("CYBER_BUCKET_MINUTES") or "15"))
CYBER_DENSE_MIN_POINTS = max(3, int(os.environ.get("CYBER_DENSE_MIN_POINTS") or "8"))
CYBER_DENSE_MIN_CHANGES = max(1, int(os.environ.get("CYBER_DENSE_MIN_CHANGES") or "3"))
CYBER_FUTURE_MIN_EVENTS = max(2, int(os.environ.get("CYBER_FUTURE_MIN_EVENTS") or "2"))
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
    model = str(doc.get("model") or "")
    if model in {CYBER_EVENT_MODEL, CYBER_DENSE_MODEL}:
        return True
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return str(metadata.get("mode") or "") == "cyber_event"


def _is_cyber_future_forecast(doc: dict[str, Any] | None) -> bool:
    if not doc:
        return False
    if str(doc.get("model") or "") == CYBER_FUTURE_MODEL:
        return True
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    return str(metadata.get("mode") or "") == "cyber_future"


def count_price_changes(prices: list[float]) -> int:
    changes = 0
    prev: float | None = None
    for raw in prices:
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if prev is not None and price != prev:
            changes += 1
        prev = price
    return changes


def bucket_relative_series(
    points: list[dict[str, Any]],
    *,
    bucket_minutes: int = CYBER_BUCKET_MINUTES,
) -> list[dict[str, Any]]:
    """Serie densa en eje relativo al evento: bucket 0 = primer punto."""
    timed: list[tuple[datetime, float]] = []
    for point in points or []:
        at = point.get("scraped_at")
        price = _as_int(point.get("price"))
        if not isinstance(at, datetime) or price is None:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        timed.append((at, float(price)))
    if not timed:
        return []
    timed.sort(key=lambda item: item[0])
    t0 = timed[0][0]
    width = max(1, int(bucket_minutes)) * 60
    buckets: dict[int, list[float]] = {}
    for at, price in timed:
        idx = int(max(0.0, (at - t0).total_seconds()) // width)
        buckets.setdefault(idx, []).append(price)
    rows: list[dict[str, Any]] = []
    for idx in sorted(buckets):
        vals = sorted(buckets[idx])
        median = vals[len(vals) // 2]
        rows.append({
            "bucket": idx,
            "offset_hours": round((idx * width) / 3600.0, 4),
            "price": float(median),
        })
    return rows


def is_dense_enough(
    points: list[dict[str, Any]],
    bucketed: list[dict[str, Any]] | None = None,
) -> bool:
    """True si hay muchas muestras y cambios reales de precio en el día/evento."""
    prices = [float(p["price"]) for p in points if _as_int(p.get("price"))]
    if len(prices) >= CYBER_DENSE_MIN_POINTS and count_price_changes(prices) >= CYBER_DENSE_MIN_CHANGES:
        return True
    series = bucketed if bucketed is not None else bucket_relative_series(points)
    bucket_prices = [float(item["price"]) for item in series]
    return (
        len(bucket_prices) >= max(3, CYBER_DENSE_MIN_POINTS // 2)
        and count_price_changes(bucket_prices) >= CYBER_DENSE_MIN_CHANGES
    )


def project_dense_event_prices(
    bucketed: list[dict[str, Any]],
    *,
    horizon: int,
    current: float | None = None,
    bucket_minutes: int = CYBER_BUCKET_MINUTES,
) -> list[float]:
    """Proyecta resto del evento desde curva densificada (pendiente + ancla al mínimo)."""
    prices = [float(item["price"]) for item in bucketed]
    if not prices:
        return [0.0] * max(1, horizon)
    last = float(current) if current and current > 0 else prices[-1]
    event_low = min(prices)
    if len(prices) < 2:
        return [last] * max(1, horizon)
    slope = _linear_slope(prices)
    buckets_per_day = max(1.0, (24 * 60) / max(1, bucket_minutes))
    daily_delta = slope * buckets_per_day
    projected: list[float] = []
    for step in range(1, max(1, horizon) + 1):
        value = last + daily_delta * step
        if daily_delta < 0:
            value = max(event_low * 0.97, value)
        projected.append(max(1.0, round(value, 2)))
    return projected


def group_cyber_points_by_event(points: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for point in points or []:
        lid = str(point.get("cyber_list_id") or "").strip()
        if not lid:
            continue
        grouped.setdefault(lid, []).append(point)
    for lid in list(grouped):
        grouped[lid] = sorted(
            grouped[lid],
            key=lambda row: row.get("scraped_at") or datetime.min.replace(tzinfo=timezone.utc),
        )
    return grouped


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * max(0.0, min(1.0, pct))
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return sorted_vals[low] * (1 - frac) + sorted_vals[high] * frac


def build_future_transfer_curve(
    event_curves: list[dict[str, Any]],
    *,
    scale_price: float,
    horizon: int = CYBER_EVENT_DAYS,
) -> tuple[list[float], dict[str, Any]]:
    """Mediana de curvas normalizadas (precio/apertura) escalada al precio base."""
    if scale_price <= 0 or not event_curves:
        return [], {}
    # Rejilla: un punto por día relativo del horizonte Cyber.
    grid = list(range(max(1, horizon)))
    ratio_rows: list[list[float]] = []
    source_events: list[str] = []
    min_offsets: list[float] = []
    for curve in event_curves:
        bucketed = curve.get("bucketed") or []
        open_price = float(curve.get("open") or 0)
        if open_price <= 0 or len(bucketed) < 2:
            continue
        source_events.append(str(curve.get("list_id") or ""))
        # Mapear offset_hours → ratio; muestrear a días 0..horizon-1
        by_day: dict[int, list[float]] = {}
        for item in bucketed:
            day_idx = int(float(item.get("offset_hours") or 0) // 24)
            by_day.setdefault(day_idx, []).append(float(item["price"]) / open_price)
        row: list[float] = []
        last_ratio = 1.0
        for day in grid:
            vals = by_day.get(day)
            if vals:
                last_ratio = sum(vals) / len(vals)
            row.append(last_ratio)
        ratio_rows.append(row)
        low_item = min(bucketed, key=lambda item: float(item["price"]))
        min_offsets.append(float(low_item.get("offset_hours") or 0))
    if len(ratio_rows) < CYBER_FUTURE_MIN_EVENTS:
        return [], {"source_events": source_events, "event_count": len(ratio_rows)}
    median_ratios: list[float] = []
    p20: list[float] = []
    p80: list[float] = []
    for day in grid:
        col = sorted(row[day] for row in ratio_rows)
        med = _percentile(col, 0.5)
        median_ratios.append(max(1.0, round(scale_price * med, 2)))
        p20.append(max(1.0, round(scale_price * _percentile(col, 0.2), 2)))
        p80.append(max(1.0, round(scale_price * _percentile(col, 0.8), 2)))
    typical_min_hour = _percentile(sorted(min_offsets), 0.5) if min_offsets else None
    return median_ratios, {
        "source_events": [item for item in source_events if item],
        "event_count": len(ratio_rows),
        "typical_min_offset_hours": round(typical_min_hour, 2) if typical_min_hour is not None else None,
        "quantiles": {"0.2": p20, "0.8": p80},
    }


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
        "model": CYBER_EVENT_MODEL,
    }, None


def prepare_cyber_dense_event_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
    current_price: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Pronóstico denso del resto del Cyber actual (buckets relativos + muchos cambios)."""
    base, reason = prepare_cyber_event_product(repo, store, product_id, list_ids=list_ids)
    if base is None:
        return None, reason
    lids = list(list_ids or forecast_cyber_list_ids(repo))
    cyber_points = cyber_history_points_for_product(
        repo, _norm_store(store), _norm_product_id(product_id), list_ids=lids,
    )
    bucketed = bucket_relative_series(cyber_points)
    if not is_dense_enough(cyber_points, bucketed):
        return None, "not_dense_enough"
    current = float(_as_int(current_price) or base["series"][-1])
    horizon = int(base.get("horizon") or remaining_cyber_horizon(cyber_points))
    point_forecast = project_dense_event_prices(bucketed, horizon=horizon, current=current)
    advice = cyber_buy_advice(
        current=current,
        prices=[float(item["price"]) for item in bucketed],
        point_forecast=point_forecast,
    )
    reason_txt = str(advice.get("reason") or "")
    if "serie densa" not in reason_txt.lower():
        advice = {
            **advice,
            "reason": (reason_txt + " Basado en serie densa de vueltas del evento Cyber.").strip(),
        }
    prepared = {
        **base,
        "series": [float(item["price"]) for item in bucketed],
        "bucketed": bucketed,
        "point_forecast": point_forecast,
        "horizon": horizon,
        "buy_advice": advice,
        "mode": "cyber_event",
        "model": CYBER_DENSE_MODEL,
        "observation_count": len(bucketed),
        "cyber_observation_count": len(cyber_points),
        "dense": True,
        "price_changes": count_price_changes([float(p["price"]) for p in cyber_points]),
    }
    return prepared, None


def prepare_cyber_future_transfer_product(
    repo: Any,
    store: str,
    product_id: str,
    *,
    list_ids: list[str] | None = None,
    scale_price: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Patrón de Cybers pasados densos → trayectoria tipica del próximo evento."""
    store_n = _norm_store(store)
    product_n = _norm_product_id(product_id)
    if not store_n or not product_n:
        return None, "missing_identity"
    coll = getattr(repo, "collection", None)
    if coll is None:
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
    grouped = group_cyber_points_by_event(cyber_points)
    event_curves: list[dict[str, Any]] = []
    for lid, group in grouped.items():
        bucketed = bucket_relative_series(group)
        if not is_dense_enough(group, bucketed):
            continue
        event_curves.append({
            "list_id": lid,
            "bucketed": bucketed,
            "open": float(bucketed[0]["price"]),
            "low": min(float(item["price"]) for item in bucketed),
        })
    if len(event_curves) < CYBER_FUTURE_MIN_EVENTS:
        return None, "need_another_dense_cyber"

    scale = float(
        _as_int(scale_price)
        or _as_int(document.get("price"))
        or event_curves[-1]["open"]
    )
    horizon = CYBER_EVENT_DAYS
    point_forecast, meta = build_future_transfer_curve(
        event_curves, scale_price=scale, horizon=horizon,
    )
    if not point_forecast:
        return None, "need_another_dense_cyber"

    current = scale
    advice = cyber_buy_advice(
        current=current,
        prices=point_forecast,
        point_forecast=point_forecast,
    )
    advice = {
        **advice,
        "reason": (
            f"Patrón transferido de {meta.get('event_count')} Cybers previos con historial denso. "
            + str(advice.get("reason") or "")
        ).strip(),
        "label": advice.get("label") or "Sin señal clara",
    }
    times = [p["scraped_at"] for p in cyber_points if isinstance(p.get("scraped_at"), datetime)]
    first_at = times[0] if times else _now()
    last_at = times[-1] if times else _now()
    return {
        "forecast_key": f"{store_n}:{product_n}",
        "store": store_n,
        "product_id": product_n,
        "source_document_id": str(document.get("_id") or ""),
        "name": str(document.get("name") or ""),
        "dates": [],
        "series": [float(curve["open"]) for curve in event_curves],
        "history_start": first_at.date().isoformat() if hasattr(first_at, "date") else str(first_at)[:10],
        "history_end": last_at.date().isoformat() if hasattr(last_at, "date") else str(last_at)[:10],
        "observation_count": sum(len(curve["bucketed"]) for curve in event_curves),
        "cyber_observation_count": len(cyber_points),
        "cyber_list_ids": lids,
        "cyber_distinct_days": cyber_distinct_days(cyber_points),
        "cyber_span_seconds": max(0.0, (last_at - first_at).total_seconds()),
        "point_forecast": point_forecast,
        "horizon": horizon,
        "buy_advice": advice,
        "mode": "cyber_future",
        "model": CYBER_FUTURE_MODEL,
        "source_events": meta.get("source_events") or [],
        "typical_min_offset_hours": meta.get("typical_min_offset_hours"),
        "quantiles": meta.get("quantiles") or {},
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
    is_event = mode in {"cyber_event", "cyber_future"}
    if mode == "cyber_future":
        frequency = "event_transfer"
    elif mode == "cyber_event":
        frequency = "intra_event"
    else:
        frequency = "daily"
    metadata: dict[str, Any] = {
        "source": "cyber_day",
        "mode": mode,
        "frequency": frequency,
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
        "source_events": prepared.get("source_events") or [],
        "typical_min_offset_hours": prepared.get("typical_min_offset_hours"),
        "dense": bool(prepared.get("dense")),
        "price_changes": prepared.get("price_changes"),
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
        "quantiles": quantiles if quantiles is not None else (prepared.get("quantiles") or {}),
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
    model = str(prepared.get("model") or CYBER_EVENT_MODEL)
    mode = str(prepared.get("mode") or "cyber_event")
    if len(points) != horizon:
        if model == CYBER_DENSE_MODEL and prepared.get("bucketed"):
            points = project_dense_event_prices(
                list(prepared.get("bucketed") or []),
                horizon=horizon,
                current=float((prepared.get("series") or [0])[-1] or 0) or None,
            )
        else:
            prices = [float(value) for value in prepared.get("series") or []]
            points = project_cyber_event_prices(
                prices,
                horizon=horizon,
                span_seconds=float(prepared.get("cyber_span_seconds") or 0.0),
            )
    doc = build_forecast_document(
        prepared,
        horizon=horizon,
        model=model,
        point_forecast=points,
        quantiles=prepared.get("quantiles") if isinstance(prepared.get("quantiles"), dict) else None,
        min_history_days=0,
    )
    write_forecast_docs(repo, [doc])
    advice = prepared.get("buy_advice") or {}
    return {
        "ok": True,
        "action": "written",
        "forecast_key": doc["forecast_key"],
        "model": model,
        "mode": mode,
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

    # 1) Serie densa del evento actual (muchos cambios / buckets).
    # 2) Transferencia a Cyber futuro (≥2 eventos densos previos).
    # 3) cyber_event_trend simple.
    # 4) Diario TimesFM / baseline (≥30 días).
    event_block_reason = None
    if prefer_cyber_event:
        dense_prepared, dense_reason = prepare_cyber_dense_event_product(
            repo, store_n, product_n, list_ids=lids,
        )
        if dense_prepared is not None:
            written = _write_cyber_event_forecast(repo, dense_prepared, changes=changes)
            future_prepared, _future_reason = prepare_cyber_future_transfer_product(
                repo, store_n, product_n, list_ids=lids,
            )
            if future_prepared is not None:
                future_result = _write_cyber_event_forecast(
                    repo, future_prepared, changes=changes,
                )
                written["future"] = future_result
            return written
        event_block_reason = dense_reason

        future_prepared, future_reason = prepare_cyber_future_transfer_product(
            repo, store_n, product_n, list_ids=lids,
        )
        if future_prepared is not None:
            return _write_cyber_event_forecast(repo, future_prepared, changes=changes)
        if event_block_reason in {None, "not_dense_enough"}:
            event_block_reason = future_reason or event_block_reason

        event_prepared, event_reason = prepare_cyber_event_product(
            repo,
            store_n,
            product_n,
            list_ids=lids,
        )
        if event_prepared is not None:
            return _write_cyber_event_forecast(repo, event_prepared, changes=changes)
        event_block_reason = event_reason or event_block_reason

    # 4) Camino diario clásico (TimesFM / baseline con ≥30 días).
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
        "written_cyber_dense": 0,
        "written_cyber_future": 0,
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
            model = str(result.get("model") or "")
            mode = str(result.get("mode") or "")
            if mode == "cyber_event" or model in {CYBER_EVENT_MODEL, CYBER_DENSE_MODEL}:
                stats["written_cyber_event"] += 1
            if model == CYBER_DENSE_MODEL:
                stats["written_cyber_dense"] += 1
            if mode == "cyber_future" or model == CYBER_FUTURE_MODEL:
                stats["written_cyber_future"] += 1
            future = result.get("future") if isinstance(result.get("future"), dict) else None
            if future and future.get("action") == "written":
                stats["written_cyber_future"] += 1
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


def cyber_history_points_for_query(
    repo: Any,
    list_id: str,
    n: Any,
) -> list[dict[str, Any]]:
    """Observaciones Cyber de una query (día actual + muestras previas del evento)."""
    from retail.cyber_day import history_collection, resolve_list_id

    try:
        query_n = int(n)
    except (TypeError, ValueError):
        return []
    if query_n < 1:
        return []
    lid = resolve_list_id(repo, list_id)
    points: list[dict[str, Any]] = []
    for row in history_collection(repo).find({"list_id": lid, "n": query_n}).sort([("at", 1)]):
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
            "cyber_day": row.get("day") or _day_key(at),
            "store": _norm_store(row.get("store")),
            "product_id": _norm_product_id(row.get("product_id")),
        })
    return points


def resolve_cyber_query_product_identity(
    product: dict[str, Any] | None,
    history_points: list[dict[str, Any]] | None = None,
    day_observations: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    """Resuelve store:product_id desde la query Cyber o sus observaciones."""
    if isinstance(product, dict):
        store = _norm_store(product.get("best_store"))
        product_id = _norm_product_id(product.get("last_product_id"))
        if store and product_id:
            return store, product_id
        for match_store, match_pid in _match_keys_from_last_matches(product.get("last_matches")):
            if match_store and match_pid:
                return match_store, match_pid
    for source in (day_observations or [], history_points or []):
        for row in reversed(list(source)):
            if not isinstance(row, dict):
                continue
            store = _norm_store(row.get("store"))
            product_id = _norm_product_id(row.get("product_id"))
            if store and product_id:
                return store, product_id
    return "", ""


def _summary_from_cyber_points(
    points: list[dict[str, Any]],
    *,
    current_price: Any = None,
    store: str = "",
    product_id: str = "",
    list_id: str = "",
) -> dict[str, Any] | None:
    """Construye un resumen experimental a partir de puntos Cyber (sin persistir)."""
    from retail.forecast_presentation import forecast_summary

    if len(points) < CYBER_FORECAST_MIN_OBSERVATIONS:
        return None
    prices = [float(point["price"]) for point in points]
    times = [point["scraped_at"] for point in points if isinstance(point.get("scraped_at"), datetime)]
    first_at = times[0] if times else _now()
    last_at = times[-1] if times else _now()
    span_seconds = max(0.0, (last_at - first_at).total_seconds())
    horizon = remaining_cyber_horizon(points)
    bucketed = bucket_relative_series(points)
    dense = is_dense_enough(points, bucketed)
    current = float(current_price) if _as_int(current_price) else prices[-1]
    if dense:
        point_forecast = project_dense_event_prices(bucketed, horizon=horizon, current=current)
        model = CYBER_DENSE_MODEL
        series_for_advice = [float(item["price"]) for item in bucketed]
    else:
        point_forecast = project_cyber_event_prices(prices, horizon=horizon, span_seconds=span_seconds)
        model = CYBER_EVENT_MODEL
        series_for_advice = prices
    advice = cyber_buy_advice(current=current, prices=series_for_advice, point_forecast=point_forecast)
    if dense:
        advice = {
            **advice,
            "reason": (
                str(advice.get("reason") or "")
                + " Basado en serie densa de vueltas del evento Cyber."
            ).strip(),
        }
    doc = {
        "forecast_key": f"{store}:{product_id}" if store and product_id else f"cyber_query:{list_id}",
        "store": store,
        "product_id": product_id,
        "horizon": horizon,
        "generated_at": _now(),
        "model": model,
        "point_forecast": point_forecast,
        "quantiles": {},
        "buy_advice": advice,
        "metadata": {
            "source": "cyber_day_evolution",
            "mode": "cyber_event",
            "observation_count": len(series_for_advice),
            "cyber_observation_count": len(points),
            "cyber_list_ids": [list_id] if list_id else [],
            "cyber_event_days": CYBER_EVENT_DAYS,
            "cyber_distinct_days": cyber_distinct_days(points),
            "cyber_span_seconds": span_seconds,
            "buy_advice": advice,
            "dense": dense,
            "ephemeral": True,
        },
    }
    return forecast_summary(doc, current)


def _future_summary_for_identity(
    repo: Any,
    store: str,
    product_id: str,
    *,
    current_price: Any = None,
) -> dict[str, Any] | None:
    from retail.forecast_presentation import forecast_summary

    if not store or not product_id:
        return None
    prepared, reason = prepare_cyber_future_transfer_product(
        repo, store, product_id, scale_price=current_price,
    )
    if prepared is None:
        existing = latest_forecast_for_model(repo, store, product_id, CYBER_FUTURE_MODEL)
        if existing is not None:
            return forecast_summary(existing, current_price)
        return None
    doc = build_forecast_document(
        prepared,
        horizon=int(prepared.get("horizon") or CYBER_EVENT_DAYS),
        model=CYBER_FUTURE_MODEL,
        point_forecast=list(prepared.get("point_forecast") or []),
        quantiles=prepared.get("quantiles") if isinstance(prepared.get("quantiles"), dict) else None,
        min_history_days=0,
    )
    doc["metadata"] = {**(doc.get("metadata") or {}), "ephemeral": True}
    return forecast_summary(doc, current_price or prepared.get("series", [None])[-1])


def latest_forecast_for_model(
    repo: Any,
    store: str,
    product_id: str,
    model: str,
) -> dict[str, Any] | None:
    forecasts = getattr(repo, "forecasts", None)
    if forecasts is None and hasattr(repo, "db"):
        forecasts = repo.db["forecasts"]
    if forecasts is None:
        return None
    key = f"{_norm_store(store)}:{_norm_product_id(product_id)}"
    return forecasts.find_one(
        {"forecast_key": key, "model": model},
        sort=[("generated_at", -1)],
    )


def experimental_forecast_for_cyber_query(
    repo: Any,
    *,
    list_id: str,
    n: Any,
    product: dict[str, Any] | None = None,
    day_observations: list[dict[str, Any]] | None = None,
    current_price: Any = None,
) -> dict[str, Any]:
    """Pronóstico experimental para el informe diario Cyber de una query.

    Prioridad del resumen actual:
    1. Serie densa / trend de la query
    2. Pronóstico guardado del producto vinculado
    Además intenta ``future_summary`` (transferencia entre Cybers).
    """
    from retail.cyber_day import resolve_list_id
    from retail.forecast_presentation import forecast_summary

    lid = resolve_list_id(repo, list_id)
    history_points = cyber_history_points_for_query(repo, lid, n)
    store, product_id = resolve_cyber_query_product_identity(
        product, history_points, day_observations,
    )
    current = _as_int(current_price)
    if current is None and history_points:
        current = _as_int(history_points[-1].get("price"))
    if current is None and isinstance(product, dict):
        current = _as_int(product.get("last_price"))

    future_summary = _future_summary_for_identity(
        repo, store, product_id, current_price=current,
    )

    query_summary = _summary_from_cyber_points(
        history_points,
        current_price=current,
        store=store,
        product_id=product_id,
        list_id=lid,
    )
    if query_summary is not None:
        return {
            "ok": True,
            "summary": query_summary,
            "future_summary": future_summary,
            "source": "query_history",
            "store": store or None,
            "product_id": product_id or None,
            "observation_count": len(history_points),
            "empty_reason": None,
            "future_empty_reason": (
                None if future_summary
                else "Hace falta otro Cyber con historial denso para proyectar el próximo evento."
            ),
        }

    stored_summary = None
    if store and product_id:
        for model in (CYBER_DENSE_MODEL, CYBER_EVENT_MODEL, "timesfm", "last_value_baseline"):
            existing = latest_forecast_for_model(repo, store, product_id, model)
            if existing is None:
                continue
            if str(existing.get("model") or "").lower() == "simulated":
                continue
            stored_summary = forecast_summary(existing, current)
            if stored_summary is not None:
                break
        if stored_summary is None:
            existing = latest_forecast(repo, store, product_id)
            if existing is not None and str(existing.get("model") or "").lower() != "simulated":
                stored_summary = forecast_summary(existing, current)
    if stored_summary is not None:
        return {
            "ok": True,
            "summary": stored_summary,
            "future_summary": future_summary,
            "source": "stored_forecast",
            "store": store,
            "product_id": product_id,
            "observation_count": len(history_points),
            "empty_reason": None,
            "future_empty_reason": (
                None if future_summary
                else "Hace falta otro Cyber con historial denso para proyectar el próximo evento."
            ),
        }

    needed = CYBER_FORECAST_MIN_OBSERVATIONS
    have = len(history_points)
    if have <= 0:
        empty_reason = (
            "Todavía no hay precios del día para estimar un pronóstico. "
            "Cuando el worker registre observaciones Cyber, aparecerá aquí."
        )
    else:
        empty_reason = (
            f"Aún hay pocas observaciones ({have} de {needed} mínimas) para un "
            "pronóstico confiable de la ventana Cyber. Seguí el informe cuando "
            "haya más vueltas."
        )
    return {
        "ok": True,
        "summary": None,
        "future_summary": future_summary,
        "source": "none",
        "store": store or None,
        "product_id": product_id or None,
        "observation_count": have,
        "empty_reason": empty_reason,
        "future_empty_reason": (
            None if future_summary
            else "Hace falta otro Cyber con historial denso para proyectar el próximo evento."
        ),
    }
