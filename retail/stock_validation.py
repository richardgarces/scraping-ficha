"""Validación acotada de stock sin crear carritos ni órdenes.

VTEX expone un endpoint de simulación de checkout. Se usa únicamente para
tiendas permitidas y productos cuya cantidad no viene publicada en la ficha.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from retail.http import HttpSession
from retail.registry import list_stores

MAX_PROBE_QUANTITY = max(1, min(100, int(os.environ.get("STOCK_VALIDATION_MAX", "50"))))
DEFAULT_STORES = "easy"


class _ProbeUnavailable(RuntimeError):
    pass


def enabled_stores() -> set[str]:
    raw = os.environ.get("STOCK_VALIDATION_STORES", DEFAULT_STORES)
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def find_quantity(probe: Callable[[int], bool], *, maximum: int = MAX_PROBE_QUANTITY) -> int:
    """Encuentra el máximo disponible con crecimiento exponencial y búsqueda binaria."""
    maximum = max(1, int(maximum))
    if not probe(1):
        return 0
    low, high = 1, 2
    while high <= maximum and probe(high):
        low, high = high, high * 2
    high = min(high, maximum + 1)
    if low >= maximum:
        return maximum
    while low + 1 < high:
        middle = (low + high) // 2
        if probe(middle):
            low = middle
        else:
            high = middle
    return low


def _vtex_available(payload: dict[str, Any], requested: int) -> bool:
    items = payload.get("items") or []
    if not items or not isinstance(items[0], dict):
        return False
    item = items[0]
    availability = str(item.get("availability") or "").casefold()
    if availability and availability not in {"available", "disponible"}:
        return False
    messages = " ".join(str(row.get("text") or row.get("code") or "") for row in payload.get("messages") or [] if isinstance(row, dict)).casefold()
    if any(token in messages for token in ("sin stock", "out of stock", "cantidad no disponible", "without stock")):
        return False
    try:
        returned = int(item.get("quantity", requested))
    except (TypeError, ValueError):
        returned = requested
    return returned >= requested


def probe_vtex_quantity(site: str, sku_id: str, *, maximum: int = MAX_PROBE_QUANTITY) -> int | None:
    base = str(site or "").strip().rstrip("/")
    if not base:
        return None
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    session = HttpSession(timeout=8, headers={"Origin": base, "Referer": f"{base}/"})
    endpoint = f"{base}/api/checkout/pub/orderForms/simulation"

    def probe(quantity: int) -> bool:
        status, _content_type, text = session.post(
            endpoint,
            json_body={
                "items": [{"id": str(sku_id), "quantity": quantity, "seller": "1"}],
                "country": "CHL",
            },
        )
        if status in {401, 403, 404, 405, 408, 429} or status >= 500:
            raise _ProbeUnavailable(f"checkout simulation HTTP {status}")
        if status != 200:
            return False
        try:
            return _vtex_available(json.loads(text), quantity)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False

    try:
        return find_quantity(probe, maximum=maximum)
    except Exception:
        return None
    finally:
        session.close()


def validate_result_stock(result: dict[str, Any], *, max_offers: int = 4) -> int:
    """Completa cantidades desconocidas en un resultado de búsqueda en vivo."""
    allowed = enabled_stores()
    specs = {spec.id: spec for spec in list_stores()}
    checked = 0
    for group in result.get("groups") or []:
        for offer in group.get("offers") or []:
            if checked >= max_offers:
                return checked
            store = str(offer.get("store") or "").lower()
            spec = specs.get(store)
            if (
                store not in allowed
                or spec is None
                or (spec.platform != "vtex" and store != "easy")
                or offer.get("stock") not in (None, "")
            ):
                continue
            sku = offer.get("sku_id") or offer.get("product_id")
            quantity = probe_vtex_quantity(spec.site, str(sku or "")) if sku else None
            if quantity is None:
                continue
            offer["stock"] = quantity
            offer["availability"] = "En stock" if quantity > 0 else "Sin stock"
            offer["stock_verified"] = True
            offer["stock_checked_at"] = datetime.now(timezone.utc).isoformat()
            checked += 1
    return checked
