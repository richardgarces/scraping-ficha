"""Señal experimental de TimesFM para complementar ofertas ya clasificadas."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from retail.forecast_presentation import forecast_summary

MAX_FORECAST_AGE = timedelta(hours=48)
CYBER_FORECAST_MODELS = frozenset(
    {"cyber_event_dense", "cyber_event_trend", "cyber_future_transfer"}
)


def _date(value: Any) -> datetime | None:
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


def _trim_forecast_item(forecast: dict[str, Any]) -> dict[str, Any]:
    item = dict(forecast)
    item["horizon"] = min(7, max(1, int(forecast.get("horizon") or 7)))
    item["point_forecast"] = list(forecast.get("point_forecast") or [])[:7]
    quantiles = forecast.get("quantiles")
    if isinstance(quantiles, dict):
        item["quantiles"] = {
            key: list(values)[:7] if isinstance(values, (list, tuple)) else values
            for key, values in quantiles.items()
        }
    return item


def offer_forecast_signal(
    forecast: dict[str, Any],
    current_price: Any,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Compara la oferta actual con el rango del pronóstico sin reclasificarla."""
    model = str(forecast.get("model") or "").lower()
    if model != "timesfm" and model not in CYBER_FORECAST_MODELS:
        return None
    generated = _date(forecast.get("generated_at") or forecast.get("created_at"))
    current_time = now or datetime.now(timezone.utc)
    if generated is None or generated > current_time + timedelta(minutes=10):
        return None
    if current_time - generated > MAX_FORECAST_AGE:
        return None

    item = _trim_forecast_item(forecast)
    summary = forecast_summary(item, current_price)
    if not summary:
        return None
    if model == "timesfm" and not summary["range_has_uncertainty"]:
        return None
    try:
        current = float(current_price)
        expected = float(summary["expected_price"])
        low = float(summary["range_low"])
        high = float(summary["range_high"])
    except (TypeError, ValueError):
        return None
    if min(current, expected, low, high) <= 0:
        return None

    difference = round((current - expected) * 100 / expected, 1)
    source_label = summary.get("mode_label") or ("TimesFM" if model == "timesfm" else "Pronóstico Cyber")
    if current < low:
        status = "exceptional"
        label = "Caída excepcional"
        explanation = (
            f"El precio actual está incluso por debajo del rango que {source_label} esperaba. "
            "Es una señal adicional de que la oferta podría ser especialmente conveniente."
        )
    elif current > high:
        status = "above_expected"
        label = "Precio sobre lo esperado"
        explanation = (
            f"Aunque aparece como oferta, el precio actual sigue sobre el rango esperado por {source_label}. "
            "Conviene revisar el historial y las otras tiendas antes de comprar."
        )
    else:
        status = "within_expected"
        label = "Dentro del rango esperado"
        explanation = (
            f"El precio actual está dentro de lo que {source_label} considera esperable. "
            "La oferta se sostiene por el análisis histórico y entre tiendas, sin una señal excepcional del modelo."
        )
    return {
        "status": status,
        "label": label,
        "explanation": explanation,
        "current_price": round(current),
        "expected_price": round(expected),
        "range_low": round(low),
        "range_high": round(high),
        "difference_percent": difference,
        "confidence": summary["confidence"],
        "generated_at": summary["generated_at"],
        "experimental": True,
        "forecast_model": model,
        "mode_label": summary.get("mode_label"),
    }


def attach_offer_forecast_signals(
    cards: list[dict[str, Any]],
    forecasts: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> int:
    """Adjunta la última señal disponible y deja intacto el análisis original."""
    prefer = (
        "timesfm",
        "cyber_event_dense",
        "cyber_event_trend",
        "cyber_future_transfer",
    )
    by_key: dict[str, list[dict[str, Any]]] = {}
    for forecast in forecasts:
        key = str(forecast.get("forecast_key") or "")
        if not key:
            continue
        by_key.setdefault(key, []).append(forecast)

    attached = 0
    for card in cards:
        key = f"{str(card.get('store') or '').strip().lower()}:{str(card.get('product_id') or '').strip()}"
        candidates = by_key.get(key) or []
        if not candidates:
            continue
        candidates.sort(
            key=lambda row: (
                prefer.index(str(row.get("model") or ""))
                if str(row.get("model") or "") in prefer
                else 99,
                -(
                    _date(row.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc)
                ).timestamp(),
            ),
        )
        signal = None
        for forecast in candidates:
            signal = offer_forecast_signal(forecast, card.get("price"), now=now)
            if signal:
                break
        if signal:
            card["timesfm_signal"] = signal
            attached += 1
    return attached
