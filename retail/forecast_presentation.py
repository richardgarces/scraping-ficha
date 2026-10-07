from __future__ import annotations

import math
from typing import Any


def _numbers(value: Any) -> list[float]:
    if isinstance(value, (list, tuple)):
        found: list[float] = []
        for item in value:
            found.extend(_numbers(item))
        return found
    try:
        number = float(value)
    except (TypeError, ValueError):
        return []
    return [number] if math.isfinite(number) and number > 0 else []


def _quantile_range(raw: Any) -> tuple[float | None, float | None]:
    if not isinstance(raw, dict):
        return None, None
    groups: list[tuple[float, list[float]]] = []
    for key, values in raw.items():
        try:
            quantile = float(key)
        except (TypeError, ValueError):
            continue
        clean = _numbers(values)
        if clean:
            groups.append((quantile, clean))
    if not groups:
        return None, None
    groups.sort(key=lambda item: item[0])
    return min(groups[0][1]), max(groups[-1][1])


def forecast_summary(item: dict[str, Any], current_price: Any = None) -> dict[str, Any] | None:
    points = _numbers(item.get("point_forecast"))
    if not points:
        return None
    try:
        current = float(current_price) if current_price not in (None, "") else points[0]
    except (TypeError, ValueError):
        current = points[0]
    if not math.isfinite(current) or current <= 0:
        current = points[0]
    expected = sum(points) / len(points)
    change = ((expected - current) * 100 / current) if current > 0 else 0.0
    trend = "stable"
    if change <= -2:
        trend = "down"
    elif change >= 2:
        trend = "up"

    low, high = _quantile_range(item.get("quantiles"))
    has_uncertainty = low is not None and high is not None
    if not has_uncertainty:
        low, high = min(points), max(points)

    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    try:
        observations = max(0, int(metadata.get("observation_count") or 0))
    except (TypeError, ValueError):
        observations = 0
    model = str(item.get("model") or "").lower()
    confidence = "low"
    confidence_reason = "Hay pocos datos o falta un rango de incertidumbre calculado por el modelo."
    if model == "timesfm" and has_uncertainty and observations >= 90:
        confidence = "high"
        confidence_reason = "Se usaron al menos 90 días y el modelo entregó un rango de incertidumbre."
    elif model == "timesfm" and has_uncertainty and observations >= 30:
        confidence = "medium"
        confidence_reason = "Se usaron al menos 30 días y el modelo entregó un rango de incertidumbre."

    generated = item.get("generated_at") or item.get("created_at")
    try:
        horizon = max(1, int(item.get("horizon") or len(points)))
    except (TypeError, ValueError, OverflowError):
        horizon = len(points)

    buy_advice = item.get("buy_advice")
    if not isinstance(buy_advice, dict):
        buy_advice = metadata.get("buy_advice") if isinstance(metadata.get("buy_advice"), dict) else None
    mode = str(metadata.get("mode") or "")
    if model == "cyber_event_trend" or mode == "cyber_event":
        cyber_obs = 0
        try:
            cyber_obs = max(0, int(metadata.get("cyber_observation_count") or observations or 0))
        except (TypeError, ValueError):
            cyber_obs = observations
        if cyber_obs >= 20:
            confidence = "medium"
            confidence_reason = (
                f"Pronóstico de ventana Cyber con {cyber_obs} observaciones de vueltas "
                "(horizonte corto del evento, sin exigir 30 días calendario)."
            )
        else:
            confidence = "low"
            confidence_reason = (
                "Pronóstico de ventana Cyber con pocas vueltas aún; la señal puede cambiar "
                "en la próxima corrida."
            )
        if observations < cyber_obs:
            observations = cyber_obs

    result = {
        "trend": trend,
        "change_percent": round(change, 1),
        "expected_price": round(expected),
        "range_low": round(low) if low is not None else None,
        "range_high": round(high) if high is not None else None,
        "range_has_uncertainty": has_uncertainty,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
        "generated_at": generated.isoformat() if hasattr(generated, "isoformat") else generated,
        "horizon_days": horizon,
        "model": model or "unknown",
        "observation_count": observations,
        "experimental": True,
        "mode": mode or ("cyber_event" if model == "cyber_event_trend" else "daily"),
    }
    if isinstance(buy_advice, dict) and buy_advice.get("advice"):
        result["buy_advice"] = {
            "advice": str(buy_advice.get("advice") or "observar"),
            "label": str(buy_advice.get("label") or ""),
            "reason": str(buy_advice.get("reason") or ""),
            "expected_change_percent": buy_advice.get("expected_change_percent"),
            "cyber_low": buy_advice.get("cyber_low"),
            "cyber_high": buy_advice.get("cyber_high"),
        }
    return result
