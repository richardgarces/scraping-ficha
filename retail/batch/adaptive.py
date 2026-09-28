"""Prioridad adaptativa y patrones de precios para el scraping diario."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
from statistics import median, pstdev
from typing import Any, Iterable

from retail.forecast_presentation import forecast_summary
from retail.pricing import SANTIAGO, series
from retail.relevance import fold

PRIORITY_SETTING_KEY = "adaptive_scraping_status"
MAX_PLAN_AGE = timedelta(hours=48)
DUE_GRACE = timedelta(hours=6)


def _daily(history: list[dict[str, Any]] | None) -> list[tuple[datetime, int]]:
    by_day: dict[str, tuple[datetime, int]] = {}
    for moment, price in series(history):
        if moment is None or price <= 0:
            continue
        local = moment.astimezone(SANTIAGO)
        by_day[local.date().isoformat()] = (local, price)
    return [by_day[key] for key in sorted(by_day)]


def _change_age(rows: list[tuple[datetime, int]], now: datetime) -> int:
    if not rows:
        return 0
    current = rows[-1][1]
    start = rows[0][0]
    for index in range(len(rows) - 2, -1, -1):
        if rows[index][1] != current:
            start = rows[index + 1][0]
            break
    return max(0, (now.astimezone(SANTIAGO).date() - start.date()).days)


def price_profile(history: list[dict[str, Any]] | None, *, now: datetime | None = None) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    rows = _daily(history)
    values = [price for _, price in rows]
    recent = values[-90:]
    changes_30 = sum(left != right for left, right in zip(values[-31:-1], values[-30:]))
    volatility = (pstdev(recent) / (sum(recent) / len(recent))) if len(recent) >= 2 and sum(recent) else 0.0
    return {
        "observations": len(rows),
        "history_days": (rows[-1][0].date() - rows[0][0].date()).days + 1 if rows else 0,
        "changes_30d": changes_30,
        "volatility_90d": round(volatility, 4),
        "unchanged_days": _change_age(rows, current_time),
        "last_price": values[-1] if values else None,
        "last_scraped_at": rows[-1][0] if rows else None,
    }


def _relative(values: list[int], baseline: float) -> float:
    return ((median(values) - baseline) * 100 / baseline) if values and baseline > 0 else 0.0


def detect_price_patterns(
    history: list[dict[str, Any]] | None,
    *,
    store: str = "",
    category: str = "",
    name: str = "",
) -> list[dict[str, Any]]:
    rows = _daily(history)
    if len(rows) < 28:
        return []
    values = [price for _, price in rows]
    baseline = float(median(values))
    patterns: list[dict[str, Any]] = []

    weekdays: dict[int, list[int]] = defaultdict(list)
    for moment, price in rows:
        weekdays[moment.weekday()].append(price)
    eligible_days = [(day, prices) for day, prices in weekdays.items() if len(prices) >= 4]
    if eligible_days:
        day, prices = min(eligible_days, key=lambda item: median(item[1]))
        difference = _relative(prices, baseline)
        if difference <= -5:
            labels = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            patterns.append({
                "type": "weekday_promotion", "label": f"Bajas frecuentes los {labels[day]}",
                "difference_percent": round(difference, 1), "samples": len(prices),
                "expected_trend": "down", "active_weekday": day,
                "explanation": f"En {store or 'esta tienda'}, ese día ha sido más barato que el precio habitual.",
            })

    months: dict[int, list[int]] = defaultdict(list)
    for moment, price in rows:
        months[moment.month].append(price)
    if len(rows) >= 300:
        eligible_months = [(month, prices) for month, prices in months.items() if len(prices) >= 7]
        if eligible_months:
            month, prices = min(eligible_months, key=lambda item: median(item[1]))
            difference = _relative(prices, baseline)
            if difference <= -7:
                labels = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
                patterns.append({
                    "type": "seasonal_low", "label": f"Mes históricamente bajo: {labels[month]}",
                    "difference_percent": round(difference, 1), "samples": len(prices),
                    "expected_trend": "down", "active_months": [month],
                    "explanation": "Es una asociación observada en el historial, no una garantía para el próximo año.",
                })

    def in_cyber_window(moment: datetime) -> bool:
        return bool(
            (moment.month == 5 and moment.day >= 20)
            or moment.month == 6
            or (moment.month == 9 and moment.day >= 25)
            or (moment.month == 10 and moment.day <= 10)
        )

    cyber = [price for moment, price in rows if in_cyber_window(moment)]
    outside_cyber = [price for moment, price in rows if not in_cyber_window(moment)]
    if len(cyber) >= 5 and len(outside_cyber) >= 20:
        difference = _relative(cyber, float(median(outside_cyber)))
        if difference <= -7:
            patterns.append({
                "type": "cyber_window", "label": "Bajas observadas cerca de eventos Cyber",
                "difference_percent": round(difference, 1), "samples": len(cyber),
                "expected_trend": "down", "active_months": [5, 6, 9, 10],
                "explanation": "El historial coincide con ventanas habituales de eventos Cyber; no prueba que el evento sea la causa.",
            })

    christmas = [price for moment, price in rows if moment.month == 12 and moment.day <= 24]
    before_christmas = [price for moment, price in rows if moment.month in {9, 10, 11}]
    if len(christmas) >= 7 and len(before_christmas) >= 14:
        difference = _relative(christmas, float(median(before_christmas)))
        if difference >= 7:
            patterns.append({
                "type": "pre_christmas_rise", "label": "Alzas observadas antes de Navidad",
                "difference_percent": round(difference, 1), "samples": len(christmas),
                "expected_trend": "up", "active_months": [12],
                "explanation": "En el historial, diciembre fue más caro que los meses anteriores.",
            })

    product_text = fold(f"{category} {name}")
    if any(word in product_text for word in ("ropa", "moda", "vestuario", "calzado", "zapatilla")):
        season_end = [price for moment, price in rows if moment.month in {3, 9}]
        if len(season_end) >= 7:
            difference = _relative(season_end, baseline)
            if difference <= -7:
                patterns.append({
                    "type": "season_end", "label": "Bajas observadas al final de temporada",
                    "difference_percent": round(difference, 1), "samples": len(season_end),
                    "expected_trend": "down", "active_months": [3, 9],
                    "explanation": "Marzo o septiembre resultaron más baratos en este historial de vestuario o calzado.",
                })

    if any(word in product_text for word in ("tecnologia", "notebook", "celular", "smartphone", "televisor", "consola")) and len(values) >= 90:
        older, recent = values[-90:-30], values[-30:]
        if older and recent:
            difference = _relative(recent, float(median(older)))
            below = sum(price < median(older) for price in recent) / len(recent)
            if difference <= -8 and below >= 0.7:
                patterns.append({
                    "type": "technology_cycle", "label": "Posible ciclo de renovación tecnológica",
                    "difference_percent": round(difference, 1), "samples": len(recent),
                    "expected_trend": "down",
                    "explanation": "Se detectó una baja persistente compatible con un cambio de generación, pero no confirma el lanzamiento de otro modelo.",
                })
    return patterns[:5]


def _forecast_opportunity(forecast: dict[str, Any] | None, current_price: Any) -> dict[str, Any] | None:
    if not forecast or str(forecast.get("model") or "").lower() != "timesfm":
        return None
    summary = forecast_summary(forecast, current_price)
    try:
        current = float(current_price)
        expected = float((summary or {}).get("expected_price"))
        high = float((summary or {}).get("range_high"))
    except (TypeError, ValueError):
        return None
    if not summary or current <= 0 or not summary["range_has_uncertainty"]:
        return None
    drop = (current - expected) * 100 / current
    conservative = (current - high) * 100 / current
    return {
        "expected_drop_percent": round(drop, 1),
        "conservative_drop_percent": round(conservative, 1),
        "high_offer_probability": drop >= 5 and conservative >= 2,
        "confidence": summary["confidence"],
    }


def assess_product(
    product: dict[str, Any],
    forecast: dict[str, Any] | None = None,
    *,
    timesfm_validated: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    profile = price_profile(product.get("price_history"), now=current_time)
    patterns = detect_price_patterns(
        product.get("price_history"), store=str(product.get("store") or ""),
        category=str(product.get("catalog_category") or product.get("category") or ""),
        name=str(product.get("name") or ""),
    )
    score = 50
    reasons: list[str] = []
    if profile["changes_30d"] >= 4 or profile["volatility_90d"] >= 0.08:
        score += 25
        reasons.append("El precio cambia con frecuencia.")
    elif profile["changes_30d"] >= 2:
        score += 10
        reasons.append("El precio ha tenido cambios recientes.")
    if profile["observations"] >= 60 and profile["unchanged_days"] >= 90:
        score -= 30
        reasons.append("Lleva al menos tres meses sin cambiar.")
    elif profile["observations"] >= 30 and profile["unchanged_days"] >= 45:
        score -= 20
        reasons.append("Lleva varias semanas estable.")
    opportunity = _forecast_opportunity(forecast, product.get("price")) if timesfm_validated else None
    if opportunity and opportunity["high_offer_probability"]:
        score += 35
        reasons.append("TimesFM detecta una baja probable dentro de su rango prudente.")
    model_summary = forecast_summary(forecast, product.get("price")) if timesfm_validated and forecast else None
    current_local = current_time.astimezone(SANTIAGO)
    confirmed_patterns = 0
    for pattern in patterns:
        months = pattern.get("active_months") or []
        active = not months or current_local.month in months
        if pattern.get("active_weekday") is not None:
            # Los siguientes siete días siempre contienen el día observado.
            active = True
        if active and model_summary and model_summary.get("trend") == pattern.get("expected_trend"):
            pattern["timesfm_consistent"] = True
            confirmed_patterns += 1
    if confirmed_patterns:
        score += 10
        reasons.append("TimesFM coincide con un patrón temporal observado.")
    score = max(0, min(100, score))
    interval = 12 if score >= 75 else 24 if score >= 45 else 72 if score >= 25 else 168
    tier = "high" if score >= 75 else "normal" if score >= 45 else "low" if score >= 25 else "dormant"
    return {
        "product_key": f"{str(product.get('store') or '').lower()}:{str(product.get('product_id') or '')}",
        "catalog_id": product.get("catalog_id"), "store": product.get("store"),
        "product_id": product.get("product_id"), "name": product.get("name"),
        "score": score, "tier": tier, "recommended_interval_hours": interval,
        "reasons": reasons or ["Se mantiene la frecuencia normal mientras se reúne información."],
        "profile": profile, "timesfm": opportunity, "patterns": patterns,
        "timesfm_confirmed_patterns": confirmed_patterns,
    }


def aggregate_catalog_priorities(assessments: Iterable[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
    current_time = now or datetime.now(timezone.utc)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in assessments:
        catalog_id = str(item.get("catalog_id") or "").strip()
        if catalog_id:
            groups[catalog_id].append(item)
    documents = []
    for catalog_id, items in groups.items():
        leader = max(items, key=lambda item: item.get("score") or 0)
        last_dates = [item["profile"].get("last_scraped_at") for item in items if item.get("profile", {}).get("last_scraped_at")]
        last_scraped = max(last_dates) if last_dates else None
        interval = int(leader["recommended_interval_hours"])
        next_due = (last_scraped + timedelta(hours=interval)) if last_scraped else current_time
        patterns = []
        seen = set()
        for item in sorted(items, key=lambda row: -(row.get("score") or 0)):
            for pattern in item.get("patterns") or []:
                key = pattern.get("type")
                if key not in seen:
                    seen.add(key)
                    patterns.append(pattern)
        documents.append({
            "catalog_id": catalog_id, "score": leader["score"], "tier": leader["tier"],
            "recommended_interval_hours": interval, "next_due_at": next_due,
            "last_scraped_at": last_scraped, "reasons": leader["reasons"],
            "patterns": patterns[:5], "product_count": len(items), "updated_at": current_time,
        })
    return documents


def plan_catalog_products(
    products: list[dict[str, Any]],
    priorities: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_time = now or datetime.now(timezone.utc)
    if not priorities:
        return list(products), {"enabled": False, "reason": "Todavía no existe un plan adaptativo."}
    newest = max((item.get("updated_at") for item in priorities if isinstance(item.get("updated_at"), datetime)), default=None)
    if newest is None or current_time - (newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)) > MAX_PLAN_AGE:
        return list(products), {"enabled": False, "reason": "El plan adaptativo está vencido; se usa el recorrido completo."}
    by_id = {str(item.get("catalog_id") or ""): item for item in priorities}
    due, deferred = [], []
    for position, product in enumerate(products):
        priority = by_id.get(str(product.get("id") or ""))
        if not priority:
            due.append((50, position, product))
            continue
        next_due = priority.get("next_due_at")
        if isinstance(next_due, datetime) and next_due.tzinfo is None:
            next_due = next_due.replace(tzinfo=timezone.utc)
        # El cron comienza a una hora fija, pero una búsqueda puede terminar
        # minutos después. La gracia evita convertir accidentalmente 24 h en 48 h.
        ready = not isinstance(next_due, datetime) or next_due <= current_time + DUE_GRACE
        row = (int(priority.get("score") or 0), position, product)
        (due if ready else deferred).append(row)
    due.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in due], {
        "enabled": True, "scheduled": len(due), "deferred": len(deferred),
        "high_priority": sum(score >= 75 for score, _, _ in due),
        "reason": "Se priorizaron consultas cambiantes o con baja probable; las estables volverán al vencer su intervalo.",
    }
