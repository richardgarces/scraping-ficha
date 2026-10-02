from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from retail.forecast_presentation import forecast_summary

VALIDATION_KEY = "timesfm_validation"
MIN_VALIDATED_SERIES = 30
MIN_BASELINE_IMPROVEMENT = 5.0
MIN_DIRECTION_ACCURACY = 0.55
MIN_ANTICIPATED_SERIES = 50
MIN_ANTICIPATED_BASELINE_IMPROVEMENT = 10.0
MIN_ANTICIPATED_DIRECTION_ACCURACY = 0.70
MAX_FORECAST_AGE = timedelta(hours=48)


def validation_metrics(predictions: list[list[float]], actuals: list[list[float]], contexts: list[list[float]]) -> dict[str, Any]:
    model_errors: list[float] = []
    baseline_errors: list[float] = []
    directions: list[bool] = []
    for predicted, actual, context in zip(predictions, actuals, contexts):
        size = min(len(predicted), len(actual))
        if size <= 0 or not context:
            continue
        predicted = [float(value) for value in predicted[:size]]
        actual = [float(value) for value in actual[:size]]
        last = float(context[-1])
        model_errors.append(sum(abs(left - right) for left, right in zip(predicted, actual)) / size)
        baseline_errors.append(sum(abs(last - right) for right in actual) / size)
        predicted_change = (sum(predicted) / size) - last
        actual_change = (sum(actual) / size) - last
        directions.append((predicted_change > 0) == (actual_change > 0) if actual_change != 0 else abs(predicted_change) < max(1, last * 0.02))
    evaluated = len(model_errors)
    model_mae = sum(model_errors) / evaluated if evaluated else 0.0
    baseline_mae = sum(baseline_errors) / evaluated if evaluated else 0.0
    improvement = ((baseline_mae - model_mae) * 100 / baseline_mae) if baseline_mae > 0 else 0.0
    return {
        "model": "timesfm",
        "evaluated_series": evaluated,
        "model_mae": round(model_mae, 2),
        "baseline_mae": round(baseline_mae, 2),
        "improvement_vs_baseline_percent": round(improvement, 2),
        "direction_accuracy": round(sum(directions) / evaluated, 4) if evaluated else 0.0,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }


def predictive_validation_status(repo: Any) -> dict[str, Any]:
    raw = repo.get_app_setting(VALIDATION_KEY) if hasattr(repo, "get_app_setting") else None
    data = raw if isinstance(raw, dict) else {}
    try:
        evaluated = int(data.get("evaluated_series") or 0)
        improvement = float(data.get("improvement_vs_baseline_percent") or 0)
        direction = float(data.get("direction_accuracy") or 0)
    except (TypeError, ValueError):
        evaluated, improvement, direction = 0, 0.0, 0.0
    enabled = bool(
        data.get("model") == "timesfm"
        and evaluated >= MIN_VALIDATED_SERIES
        and improvement >= MIN_BASELINE_IMPROVEMENT
        and direction >= MIN_DIRECTION_ACCURACY
    )
    if enabled:
        reason = "TimesFM superó la referencia básica en la validación registrada."
    elif evaluated < MIN_VALIDATED_SERIES:
        reason = f"Faltan series evaluadas ({evaluated}/{MIN_VALIDATED_SERIES})."
    elif improvement < MIN_BASELINE_IMPROVEMENT:
        reason = "TimesFM todavía no supera suficientemente la referencia básica."
    else:
        reason = "La precisión para anticipar la dirección del precio aún es insuficiente."
    return {
        "enabled": enabled,
        "reason": reason,
        "evaluated_series": evaluated,
        "improvement_vs_baseline_percent": round(improvement, 1),
        "direction_accuracy": round(direction, 3),
        "validated_at": data.get("validated_at"),
    }


def anticipated_drop_validation_status(repo: Any) -> dict[str, Any]:
    """Bloqueo reforzado para afirmar que existe una posibilidad alta de baja."""
    raw = repo.get_app_setting(VALIDATION_KEY) if hasattr(repo, "get_app_setting") else None
    data = raw if isinstance(raw, dict) else {}
    try:
        evaluated = int(data.get("evaluated_series") or 0)
        improvement = float(data.get("improvement_vs_baseline_percent") or 0)
        direction = float(data.get("direction_accuracy") or 0)
    except (TypeError, ValueError):
        evaluated, improvement, direction = 0, 0.0, 0.0
    enabled = bool(
        data.get("model") == "timesfm"
        and evaluated >= MIN_ANTICIPATED_SERIES
        and improvement >= MIN_ANTICIPATED_BASELINE_IMPROVEMENT
        and direction >= MIN_ANTICIPATED_DIRECTION_ACCURACY
    )
    if enabled:
        reason = "TimesFM alcanzó la validación reforzada para anticipar bajas."
    elif evaluated < MIN_ANTICIPATED_SERIES:
        reason = f"Faltan series para alertas anticipadas ({evaluated}/{MIN_ANTICIPATED_SERIES})."
    elif improvement < MIN_ANTICIPATED_BASELINE_IMPROVEMENT:
        reason = "TimesFM aún no supera en 10% la referencia básica."
    else:
        reason = "TimesFM aún no alcanza 70% de acierto en la dirección del precio."
    return {
        "enabled": enabled,
        "reason": reason,
        "evaluated_series": evaluated,
        "improvement_vs_baseline_percent": round(improvement, 1),
        "direction_accuracy": round(direction, 3),
        "validated_at": data.get("validated_at"),
    }


def _first_days(forecast: dict[str, Any], days: int = 7) -> dict[str, Any]:
    item = dict(forecast)
    item["horizon"] = days
    item["point_forecast"] = list(forecast.get("point_forecast") or [])[:days]
    quantiles = forecast.get("quantiles")
    if isinstance(quantiles, dict):
        item["quantiles"] = {
            key: (list(values)[:days] if isinstance(values, (list, tuple)) else values)
            for key, values in quantiles.items()
        }
    return item


def _forecast_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif value not in (None, ""):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _fresh_forecast(forecast: dict[str, Any], now: datetime | None = None) -> bool:
    generated = _forecast_date(forecast.get("generated_at") or forecast.get("created_at"))
    current = now or datetime.now(timezone.utc)
    return bool(
        generated
        and generated <= current + timedelta(minutes=10)
        and current - generated <= MAX_FORECAST_AGE
    )


def _upper_quantile(forecast: dict[str, Any]) -> list[float]:
    quantiles = forecast.get("quantiles")
    if not isinstance(quantiles, dict):
        return []
    candidates: list[tuple[float, list[float]]] = []
    for key, raw in quantiles.items():
        try:
            quantile = float(key)
        except (TypeError, ValueError):
            continue
        if quantile < 0.8 or not isinstance(raw, (list, tuple)):
            continue
        values: list[float] = []
        for value in list(raw)[:7]:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number) and number > 0:
                values.append(number)
        if values:
            candidates.append((quantile, values))
    return max(candidates, key=lambda item: item[0])[1] if candidates else []


def anticipated_drop_signal(
    forecast: dict[str, Any],
    current_price: Any,
    normal_price: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Señal conservadora: sin oferta actual y baja respaldada por el rango alto."""
    if str(forecast.get("model") or "").lower() != "timesfm" or not _fresh_forecast(forecast, now):
        return None
    try:
        current = float(current_price)
        normal = float(normal_price)
    except (TypeError, ValueError):
        return None
    if current <= 0 or normal <= 0:
        return None
    current_discount = max(0.0, (normal - current) * 100 / normal)
    if current_discount >= 10.0:
        return None

    summary = forecast_summary(_first_days(forecast), current)
    points = []
    for value in list(forecast.get("point_forecast") or [])[:7]:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            points.append(number)
    upper = _upper_quantile(forecast)
    if not summary or summary["confidence"] != "high" or len(points) < 3 or len(upper) < 3:
        return None

    expected = sum(points) / len(points)
    projected_drop = (current - expected) * 100 / current
    supporting_days = sum(value <= current * 0.98 for value in upper)
    required_days = max(3, math.ceil(len(upper) * 0.60))
    if projected_drop < 5.0 or supporting_days < required_days:
        return None
    return {
        "projected_drop_percent": round(projected_drop, 1),
        "supporting_days": supporting_days,
        "evaluated_days": len(upper),
        "current_discount_percent": round(current_discount, 1),
        "confidence": "high",
    }


def predictive_message(
    forecast: dict[str, Any],
    current_price: Any,
    normal_price: Any = None,
    *,
    allow_anticipated: bool = False,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    if not _fresh_forecast(forecast, now):
        return None
    summary = forecast_summary(_first_days(forecast), current_price)
    if not summary or str(forecast.get("model") or "").lower() != "timesfm":
        return None
    name = str(forecast.get("name") or "Producto")
    store = str(forecast.get("store") or "tienda")
    current = int(current_price or 0)
    if summary["range_has_uncertainty"] and current and current < int(summary["range_low"] or 0):
        return (
            "buy_now",
            f"Precio actual menor que el rango esperado. Buen momento para comprar: {name} está a ${current:,} en {store}.".replace(",", "."),
        )
    anticipated = (
        anticipated_drop_signal(forecast, current_price, normal_price, now=now)
        if allow_anticipated else None
    )
    if anticipated:
        return (
            "anticipated_drop",
            (
                f"Este producto aún no está en oferta, pero existe una posibilidad alta de que baje durante "
                f"los próximos días. TimesFM estima cerca de {anticipated['projected_drop_percent']:.0f}% de baja "
                f"para {name}; incluso su rango más prudente apunta hacia abajo en "
                f"{anticipated['supporting_days']} de {anticipated['evaluated_days']} días. "
                "Conviene esperar. Es una estimación, no una garantía."
            ),
        )
    return None


def dispatch_predictive_alerts(repo: Any) -> dict[str, Any]:
    status = predictive_validation_status(repo)
    if not status["enabled"]:
        return {"enabled": False, "sent": 0, "reason": status["reason"]}

    from retail.batch.alerts import _notification_text, product_email_html, send_email, send_to_user
    from retail.batch.rules import load_rules
    from retail.short_links import attach_short_url

    users = [
        user for user in repo.list_notification_users()
        if "predictive" in ((user.get("notification_preferences") or {}).get("kinds") or [])
    ]
    if not users:
        return {"enabled": True, "sent": 0, "reason": "No hay usuarios suscritos."}

    # Medios de alerta del admin: sin «Correo» no se manda email predictivo.
    system_channels = set(load_rules().get("channels") or [])
    email_enabled = "email" in system_channels
    push_enabled = "push" in system_channels
    anticipated_status = anticipated_drop_validation_status(repo)
    forecasts = repo.db.get_collection("forecasts")
    sends = getattr(repo, "predictive_alert_sends", repo.db.get_collection("predictive_alert_sends"))
    sent = 0
    seen_forecasts: set[str] = set()
    for forecast in forecasts.find(
        {"model": "timesfm", "forecast_key": {"$type": "string"}}
    ).sort("generated_at", -1):
        forecast_key = str(forecast.get("forecast_key") or "")
        if not forecast_key or forecast_key in seen_forecasts:
            continue
        seen_forecasts.add(forecast_key)
        product = repo.collection.find_one(
            {"store": forecast.get("store"), "product_id": forecast.get("product_id")},
            {"price": 1, "price_normal": 1, "url": 1, "image_url": 1, "compare_code": 1},
        ) or {}
        candidate = predictive_message(
            forecast,
            product.get("price"),
            product.get("price_normal"),
            allow_anticipated=anticipated_status["enabled"],
        )
        if not candidate:
            continue
        kind, message = candidate
        generated = str(forecast.get("generated_at") or "")
        payload = {
            "name": forecast.get("name"), "store": forecast.get("store"),
            "product_id": forecast.get("product_id"),
            "price": product.get("price"), "price_normal": product.get("price_normal"),
            "message": message, "url": product.get("url"), "image_url": product.get("image_url"),
        }
        attach_short_url(payload, repo)
        text = _notification_text(payload)
        entity_key = str(product.get("compare_code") or f"product:{forecast.get('store')}:{forecast.get('product_id')}")
        for user in users:
            user_id = str(user.get("_id") or user.get("id") or "")
            key = {"user_id": user_id, "forecast_key": forecast["forecast_key"], "kind": kind, "generated_at": generated}
            if sends.find_one(key, {"_id": 1}):
                continue
            channels = (user.get("notification_preferences") or {}).get("channels") or []
            delivered = False
            if "telegram" in channels:
                claimed = not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                    user_id, "telegram", entity_key, product.get("price"),
                )
                if claimed:
                    delivered = send_to_user(user, text, image_url=product.get("image_url")) or delivered
            email = str(user.get("email") or "").strip()
            if email_enabled and "email" in channels and email:
                claimed = not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                    user_id, "email", entity_key, product.get("price"),
                )
                heading = "Probable baja de precio" if kind == "anticipated_drop" else "Buen momento para comprar"
                delivered = (claimed and send_email(
                    email,
                    f"Pronóstico de precio: {forecast.get('name') or 'producto'}",
                    text,
                    html=product_email_html(payload, eyebrow="Estimación de precio", heading=heading),
                )) or delivered
            if push_enabled and "push" in channels and user.get("push_subscriptions"):
                from retail.web_push import send_user_push

                claimed = not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                    user_id, "push", entity_key, product.get("price"),
                )
                if claimed:
                    delivered = send_user_push(user, payload, repo=repo, tag=entity_key) or delivered
            if delivered:
                sends.insert_one({**key, "sent_at": datetime.now(timezone.utc), "channels": channels})
                sent += 1
    return {
        "enabled": True,
        "sent": sent,
        "reason": "Proceso completado.",
        "anticipated": anticipated_status,
    }
