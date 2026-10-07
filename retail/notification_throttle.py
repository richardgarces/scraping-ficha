"""Throttle compartido para alertas push / Telegram / correo.

Regla:
- Enviar si no hubo envío previo, o si pasaron ≥ cooldown_days desde el último.
- Excepción: si el precio nuevo es estrictamente menor al último notificado
  (nueva bajada), permitir otro envío aunque siga dentro de la ventana.
- Subidas (o mismo precio) dentro de la ventana: no reenviar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_COOLDOWN_DAYS = 5


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def should_send_price_notification(
    *,
    last_sent_at: datetime | None,
    last_notified_price: int | float | None,
    new_price: int | float | None,
    now: datetime | None = None,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> bool:
    """True si corresponde reservar/enviar la alerta de precio."""
    sent_at = _as_aware(last_sent_at)
    if sent_at is None:
        return True
    clock = _as_aware(now) or datetime.now(timezone.utc)
    days = max(1, int(cooldown_days))
    if sent_at <= clock - timedelta(days=days):
        return True
    if new_price is None or last_notified_price is None:
        return False
    try:
        return int(new_price) < int(last_notified_price)
    except (TypeError, ValueError):
        return False


def mongo_claim_filter(
    *,
    user_id: str,
    channel: str,
    entity_key: str,
    price: int | None,
    cutoff: datetime,
) -> dict[str, Any]:
    """Filtro atómico equivalente a should_send_price_notification para update/upsert."""
    key = {
        "user_id": str(user_id),
        "channel": str(channel),
        "entity_key": str(entity_key),
    }
    allowed: list[dict[str, Any]] = [
        {"last_sent_at": {"$exists": False}},
        {"last_sent_at": None},
        {"last_sent_at": {"$lte": cutoff}},
    ]
    if price is not None:
        # Nueva bajada respecto al último precio notificado.
        allowed.append({"last_price": {"$gt": int(price)}})
    return {**key, "$or": allowed}
