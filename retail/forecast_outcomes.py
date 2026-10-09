"""Snapshots y evaluación diaria de cumplimiento de pronósticos experimentales.

Criterio de cumplimiento (por defecto):
- Hit si, dentro del horizonte, algún precio diario observado cae dentro del
  rango pronosticado [range_low, range_high] (banda ±2% si el rango colapsa).
- Alternativa direccional: trend down/up con movimiento ≥2% en esa dirección.
- Miss cuando el horizonte termina sin hit.
- ETA mientras pending: día del horizonte donde el point_forecast primero
  alcanza la zona favorable (o días restantes del horizonte).
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any

from retail.forecast_presentation import forecast_summary
from retail.pricing import parse_moment, santiago_day

STATUS_PENDING = "pending"
STATUS_HIT = "hit"
STATUS_MISS = "miss"
STATUS_EXPIRED = "expired"

_OPEN = {STATUS_PENDING}
_TREND_PCT = 0.02


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_dt(value: Any) -> datetime | None:
    return parse_moment(value)


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def outcome_identity(doc: dict[str, Any]) -> dict[str, Any]:
    generated = _as_dt(doc.get("generated_at") or doc.get("created_at")) or _now()
    try:
        horizon = max(1, int(doc.get("horizon") or len(doc.get("point_forecast") or []) or 1))
    except (TypeError, ValueError, OverflowError):
        horizon = 1
    return {
        "forecast_key": str(doc.get("forecast_key") or "").strip(),
        "model": str(doc.get("model") or "unknown").strip().lower() or "unknown",
        "horizon": horizon,
        "generated_at": generated,
    }


def build_outcome_snapshot(
    forecast_doc: dict[str, Any],
    *,
    baseline_price: float | None = None,
) -> dict[str, Any] | None:
    """Construye un documento inmutable de evaluación a partir de un forecast."""
    if str(forecast_doc.get("model") or "").lower() == "simulated":
        return None
    summary = forecast_summary(forecast_doc, baseline_price)
    if summary is None:
        return None
    ident = outcome_identity(forecast_doc)
    if not ident["forecast_key"]:
        store = str(forecast_doc.get("store") or "").strip().lower()
        product_id = str(forecast_doc.get("product_id") or "").strip()
        if store and product_id:
            ident["forecast_key"] = f"{store}:{product_id}"
        else:
            return None

    points = [float(x) for x in (forecast_doc.get("point_forecast") or []) if _positive(x)]
    low = summary.get("range_low")
    high = summary.get("range_high")
    expected = _positive(summary.get("expected_price"))
    if low is None or high is None:
        if expected is None and points:
            expected = sum(points) / len(points)
        if expected is not None:
            low = expected * (1 - _TREND_PCT)
            high = expected * (1 + _TREND_PCT)
    if low is not None and high is not None and low > high:
        low, high = high, low
    # Rango colapsado → banda ±2%
    if low is not None and high is not None and high <= low * 1.001 and expected:
        low = expected * (1 - _TREND_PCT)
        high = expected * (1 + _TREND_PCT)

    baseline = _positive(baseline_price)
    if baseline is None and points:
        baseline = points[0]
    if baseline is None:
        baseline = expected

    eta_days = _estimate_eta_days(
        points=points,
        trend=str(summary.get("trend") or "stable"),
        range_low=_positive(low),
        range_high=_positive(high),
        baseline=baseline,
        horizon=ident["horizon"],
    )

    return {
        "forecast_key": ident["forecast_key"],
        "store": str(forecast_doc.get("store") or "").strip().lower(),
        "product_id": str(forecast_doc.get("product_id") or "").strip(),
        "name": str(forecast_doc.get("name") or "").strip(),
        "model": ident["model"],
        "horizon": ident["horizon"],
        "generated_at": ident["generated_at"],
        "point_forecast": points,
        "quantiles": forecast_doc.get("quantiles") if isinstance(forecast_doc.get("quantiles"), dict) else {},
        "baseline_price": round(baseline) if baseline else None,
        "expected_price": summary.get("expected_price"),
        "range_low": round(low) if low is not None else None,
        "range_high": round(high) if high is not None else None,
        "trend": summary.get("trend"),
        "mode": summary.get("mode"),
        "mode_label": summary.get("mode_label"),
        "buy_advice": summary.get("buy_advice"),
        "status": STATUS_PENDING,
        "checked_at": None,
        "days_elapsed": 0,
        "days_to_hit": None,
        "eta_days": eta_days,
        "actual_prices": [],
        "hit_day": None,
        "hit_price": None,
        "hit_reason": None,
        "error_pct": None,
        "created_at": _now(),
        "updated_at": _now(),
    }


def _estimate_eta_days(
    *,
    points: list[float],
    trend: str,
    range_low: float | None,
    range_high: float | None,
    baseline: float | None,
    horizon: int,
) -> int:
    """Día 1-based del horizonte donde el punto proyectado primero favorece el hit."""
    if not points:
        return max(1, horizon)
    for index, price in enumerate(points, start=1):
        if range_low is not None and range_high is not None and range_low <= price <= range_high:
            return index
        if baseline and trend == "down" and price <= baseline * (1 - _TREND_PCT):
            return index
        if baseline and trend == "up" and price >= baseline * (1 + _TREND_PCT):
            return index
    return max(1, min(horizon, len(points)))


def _daily_prices_after(
    history: list[dict[str, Any]],
    *,
    generated_at: datetime,
    horizon: int,
) -> list[dict[str, Any]]:
    """Último precio por día Santiago desde el día siguiente a generated_at."""
    start_day = santiago_day(generated_at) + timedelta(days=1)
    end_day = start_day + timedelta(days=max(0, horizon - 1))
    by_day: dict[date, float] = {}
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        price = _positive(entry.get("price"))
        moment = parse_moment(entry.get("scraped_at"))
        if price is None or moment is None:
            continue
        day = santiago_day(moment)
        if day < start_day or day > end_day:
            continue
        by_day[day] = price  # último del día
    rows = []
    for offset in range(horizon):
        day = start_day + timedelta(days=offset)
        if day not in by_day:
            continue
        rows.append(
            {
                "day": day.isoformat(),
                "day_index": offset + 1,
                "price": round(by_day[day]),
            }
        )
    return rows


def _price_hits(
    price: float,
    *,
    range_low: float | None,
    range_high: float | None,
    trend: str,
    baseline: float | None,
) -> tuple[bool, str]:
    if range_low is not None and range_high is not None and range_low <= price <= range_high:
        return True, "range"
    if baseline and trend == "down" and price <= baseline * (1 - _TREND_PCT):
        return True, "direction_down"
    if baseline and trend == "up" and price >= baseline * (1 + _TREND_PCT):
        return True, "direction_up"
    if baseline and trend == "stable" and abs(price - baseline) / baseline <= _TREND_PCT:
        return True, "stable"
    return False, ""


def evaluate_outcome_document(
    outcome: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Devuelve campos actualizados de evaluación (sin mutar el original)."""
    moment = now or _now()
    generated = _as_dt(outcome.get("generated_at")) or moment
    try:
        horizon = max(1, int(outcome.get("horizon") or 1))
    except (TypeError, ValueError, OverflowError):
        horizon = 1

    actual = _daily_prices_after(history, generated_at=generated, horizon=horizon)
    today = santiago_day(moment)
    start_day = santiago_day(generated) + timedelta(days=1)
    days_elapsed = max(0, min(horizon, (today - start_day).days + 1))
    if today < start_day:
        days_elapsed = 0

    range_low = _positive(outcome.get("range_low"))
    range_high = _positive(outcome.get("range_high"))
    baseline = _positive(outcome.get("baseline_price"))
    trend = str(outcome.get("trend") or "stable")
    expected = _positive(outcome.get("expected_price"))

    hit_day = None
    hit_price = None
    hit_reason = None
    for row in actual:
        ok, reason = _price_hits(
            float(row["price"]),
            range_low=range_low,
            range_high=range_high,
            trend=trend,
            baseline=baseline,
        )
        if ok:
            hit_day = int(row["day_index"])
            hit_price = int(row["price"])
            hit_reason = reason
            break

    status = str(outcome.get("status") or STATUS_PENDING)
    days_to_hit = outcome.get("days_to_hit")
    if hit_day is not None:
        status = STATUS_HIT
        days_to_hit = hit_day
    elif days_elapsed >= horizon:
        status = STATUS_MISS
        days_to_hit = None
    else:
        status = STATUS_PENDING

    original_eta = outcome.get("eta_days")
    try:
        original_eta_int = max(1, int(original_eta)) if original_eta is not None else horizon
    except (TypeError, ValueError):
        original_eta_int = horizon
    if status == STATUS_HIT:
        eta_days = 0
    elif status == STATUS_MISS:
        eta_days = 0
    else:
        eta_days = max(0, original_eta_int - days_elapsed)
        if eta_days == 0:
            eta_days = max(0, horizon - days_elapsed)

    error_pct = None
    if actual and expected:
        last_price = float(actual[-1]["price"])
        error_pct = round(abs(last_price - expected) * 100 / expected, 1)

    return {
        "status": status,
        "checked_at": moment,
        "days_elapsed": days_elapsed,
        "days_to_hit": days_to_hit,
        "eta_days": eta_days,
        "actual_prices": actual,
        "hit_day": hit_day,
        "hit_price": hit_price,
        "hit_reason": hit_reason,
        "error_pct": error_pct,
        "updated_at": moment,
    }


def ensure_forecast_outcome_indexes(collection: Any) -> None:
    try:
        collection.create_index(
            [
                ("forecast_key", 1),
                ("model", 1),
                ("horizon", 1),
                ("generated_at", 1),
            ],
            unique=True,
            name="forecast_outcome_identity",
        )
    except Exception:
        pass
    try:
        collection.create_index([("status", 1), ("generated_at", -1)], name="forecast_outcome_status")
    except Exception:
        pass
    try:
        collection.create_index([("model", 1), ("generated_at", -1)], name="forecast_outcome_model")
    except Exception:
        pass


def outcomes_collection(repo: Any) -> Any | None:
    coll = getattr(repo, "forecast_outcomes", None)
    if coll is not None:
        return coll
    db = getattr(repo, "db", None)
    if db is None:
        return None
    return db["forecast_outcomes"]


def snapshot_forecast_docs(repo: Any, docs: list[dict[str, Any]]) -> int:
    """Inserta outcomes nuevos para docs de forecast (idempotente)."""
    coll = outcomes_collection(repo)
    if coll is None or not docs:
        return 0
    ensure_forecast_outcome_indexes(coll)
    inserted = 0
    for doc in docs:
        if str(doc.get("model") or "").lower() == "simulated":
            continue
        baseline = None
        store = str(doc.get("store") or "").strip().lower()
        product_id = str(doc.get("product_id") or "").strip()
        if store and product_id and hasattr(repo, "collection"):
            product = repo.collection.find_one(
                {"store": store, "product_id": product_id},
                {"price": 1, "price_history": {"$slice": -5}},
            )
            if product:
                baseline = _positive(product.get("price"))
                if baseline is None:
                    for entry in reversed(product.get("price_history") or []):
                        baseline = _positive((entry or {}).get("price"))
                        if baseline is not None:
                            break
        snap = build_outcome_snapshot(doc, baseline_price=baseline)
        if snap is None:
            continue
        filter_q = {
            "forecast_key": snap["forecast_key"],
            "model": snap["model"],
            "horizon": snap["horizon"],
            "generated_at": snap["generated_at"],
        }
        existing = coll.find_one(filter_q, {"_id": 1})
        if existing:
            continue
        coll.insert_one(snap)
        inserted += 1
    return inserted


def backfill_outcomes_from_forecasts(repo: Any, *, limit: int = 5000) -> dict[str, int]:
    forecasts = getattr(repo, "forecasts", None)
    if forecasts is None and hasattr(repo, "db"):
        forecasts = repo.db["forecasts"]
    if forecasts is None:
        return {"scanned": 0, "inserted": 0}
    cursor = forecasts.find({"model": {"$ne": "simulated"}}).sort("generated_at", -1).limit(limit)
    docs = list(cursor)
    return {"scanned": len(docs), "inserted": snapshot_forecast_docs(repo, docs)}


def evaluate_open_outcomes(repo: Any, *, limit: int = 2000, now: datetime | None = None) -> dict[str, int]:
    """Evalúa outcomes pending (y rechequea hits recientes no cerrados no aplica)."""
    coll = outcomes_collection(repo)
    if coll is None:
        return {"checked": 0, "hit": 0, "miss": 0, "pending": 0}
    ensure_forecast_outcome_indexes(coll)
    moment = now or _now()
    cursor = coll.find({"status": STATUS_PENDING}).sort("generated_at", 1).limit(limit)
    rows = list(cursor)
    if not rows:
        return {"checked": 0, "hit": 0, "miss": 0, "pending": 0}

    keys: list[tuple[str, str]] = []
    for row in rows:
        store = str(row.get("store") or "")
        product_id = str(row.get("product_id") or "")
        if store and product_id:
            keys.append((store, product_id))
    histories = repo.histories(keys, limit=120) if hasattr(repo, "histories") else {}

    stats = {"checked": 0, "hit": 0, "miss": 0, "pending": 0}
    for row in rows:
        store = str(row.get("store") or "")
        product_id = str(row.get("product_id") or "")
        history = histories.get((store, product_id), [])
        updates = evaluate_outcome_document(row, history, now=moment)
        coll.update_one({"_id": row["_id"]}, {"$set": updates})
        stats["checked"] += 1
        status = updates["status"]
        if status in stats:
            stats[status] += 1
    return stats


def _serialize(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize(v) for v in value]
    return value


def list_outcomes(
    repo: Any,
    *,
    page: int = 1,
    size: int = 40,
    status: str | None = None,
    model: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    coll = outcomes_collection(repo)
    if coll is None:
        return {"items": [], "total": 0, "page": 1, "size": size}
    ensure_forecast_outcome_indexes(coll)
    query: dict[str, Any] = {}
    if status:
        query["status"] = str(status).strip().lower()
    if model:
        query["model"] = str(model).strip().lower()
    needle = str(q or "").strip()
    if needle:
        safe = re.escape(needle)
        query["$or"] = [
            {"name": {"$regex": safe, "$options": "i"}},
            {"product_id": {"$regex": safe, "$options": "i"}},
            {"forecast_key": {"$regex": safe, "$options": "i"}},
            {"store": {"$regex": safe, "$options": "i"}},
        ]
    total = coll.count_documents(query)
    page = max(1, int(page or 1))
    size = max(1, min(100, int(size or 40)))
    skip = (page - 1) * size
    cursor = coll.find(query).sort([("generated_at", -1), ("_id", -1)]).skip(skip).limit(size)
    items = []
    for row in cursor:
        row.pop("_id", None)
        items.append(_serialize(row))
    return {"items": items, "total": total, "page": page, "size": size}


def outcome_stats(repo: Any) -> dict[str, Any]:
    coll = outcomes_collection(repo)
    empty = {
        "total": 0,
        "by_status": {},
        "hit_rate": None,
        "by_model": [],
        "median_days_to_hit": None,
        "pending_eta_median": None,
    }
    if coll is None:
        return empty
    ensure_forecast_outcome_indexes(coll)
    total = coll.count_documents({})
    by_status: dict[str, int] = {}
    for status in (STATUS_PENDING, STATUS_HIT, STATUS_MISS, STATUS_EXPIRED):
        by_status[status] = coll.count_documents({"status": status})
    decided = by_status.get(STATUS_HIT, 0) + by_status.get(STATUS_MISS, 0)
    hit_rate = round(by_status.get(STATUS_HIT, 0) * 100 / decided, 1) if decided else None

    by_model = []
    for row in coll.aggregate(
        [
            {"$group": {
                "_id": "$model",
                "total": {"$sum": 1},
                "hit": {"$sum": {"$cond": [{"$eq": ["$status", STATUS_HIT]}, 1, 0]}},
                "miss": {"$sum": {"$cond": [{"$eq": ["$status", STATUS_MISS]}, 1, 0]}},
                "pending": {"$sum": {"$cond": [{"$eq": ["$status", STATUS_PENDING]}, 1, 0]}},
                "days": {"$push": "$days_to_hit"},
            }},
            {"$sort": {"total": -1}},
        ]
    ):
        days = [int(d) for d in (row.get("days") or []) if isinstance(d, (int, float)) and d is not None]
        model_decided = int(row.get("hit") or 0) + int(row.get("miss") or 0)
        by_model.append(
            {
                "model": row.get("_id") or "unknown",
                "total": int(row.get("total") or 0),
                "hit": int(row.get("hit") or 0),
                "miss": int(row.get("miss") or 0),
                "pending": int(row.get("pending") or 0),
                "hit_rate": round(int(row.get("hit") or 0) * 100 / model_decided, 1) if model_decided else None,
                "median_days_to_hit": round(median(days), 1) if days else None,
            }
        )

    hit_days = []
    for row in coll.find({"status": STATUS_HIT, "days_to_hit": {"$ne": None}}, {"days_to_hit": 1}):
        try:
            hit_days.append(int(row["days_to_hit"]))
        except (TypeError, ValueError, KeyError):
            pass
    pending_etas = []
    for row in coll.find({"status": STATUS_PENDING}, {"eta_days": 1}):
        try:
            if row.get("eta_days") is not None:
                pending_etas.append(int(row["eta_days"]))
        except (TypeError, ValueError):
            pass

    return {
        "total": total,
        "by_status": by_status,
        "hit_rate": hit_rate,
        "by_model": by_model,
        "median_days_to_hit": round(median(hit_days), 1) if hit_days else None,
        "pending_eta_median": round(median(pending_etas), 1) if pending_etas else None,
        "decided": decided,
    }


def run_daily_outcome_pass(repo: Any) -> dict[str, Any]:
    """Backfill + evaluación; pensado para cron BMAX."""
    backfill = backfill_outcomes_from_forecasts(repo)
    evaluated = evaluate_open_outcomes(repo)
    return {"backfill": backfill, "evaluate": evaluated}
