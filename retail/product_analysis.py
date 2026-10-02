from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


OUT_OF_STOCK = ("sin stock", "agotado", "no disponible", "out of stock", "unavailable")
IN_STOCK = ("en stock", "disponible", "available", "in stock")
FICHA_QUERY_MAX = 500
TEXT_QUERY_MAX = 160


def parse_ficha_ref(raw: str) -> tuple[str, str] | None:
    """Detecta URI de ficha `/producto?store=…&id=…` (absoluta o relativa)."""
    text = " ".join(str(raw or "").split()).strip()
    if not text or len(text) > FICHA_QUERY_MAX:
        return None

    candidate = text
    lowered = text.casefold()
    if lowered.startswith("/producto?") or lowered.startswith("/producto#"):
        candidate = f"https://local.invalid{text}"
    elif lowered.startswith("producto?"):
        candidate = f"https://local.invalid/{text}"
    elif "://" not in text and "/producto?" in lowered:
        # Pegaron host+ruta sin esquema, p. ej. precios.meincart.cl/producto?...
        candidate = f"https://{text.lstrip('/')}"
    elif "://" not in text:
        return None

    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return None
    path = (parsed.path or "").rstrip("/") or "/"
    if path.casefold() != "/producto":
        return None

    params = parse_qs(parsed.query, keep_blank_values=False)
    store = unquote((params.get("store") or [""])[0]).strip().lower()[:80]
    product_id = unquote((params.get("id") or [""])[0]).strip()[:180]
    if not store or not product_id:
        return None
    return store, product_id


def analysis_search_text(document: dict[str, Any]) -> str:
    """Texto de búsqueda a partir del producto semilla de una ficha."""
    from retail.ficha_sweep import search_query

    return search_query(document)


def _quantity(value: Any) -> int | None:
    """Solo acepta cantidades reales; un booleano expresa disponibilidad."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        amount = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return max(0, amount)


def _availability_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, bool):
        return "En stock" if value else "Sin stock"
    if isinstance(value, str):
        text = value.strip()
        if text == "[object Object]":
            return ""
        code = text.casefold().replace("_", " ").replace("-", " ")
        if code in {"available", "in stock", "instock", "disponible"}:
            return "En stock"
        if code in {"unavailable", "out of stock", "outofstock", "agotado", "no disponible"}:
            return "Sin stock"
        return text
    if isinstance(value, list):
        labels = dict.fromkeys(filter(None, (_availability_text(item) for item in value)))
        return " · ".join(labels)
    if isinstance(value, dict):
        for key in (
            "message", "text", "label", "name", "description", "displayName",
            "statusText", "stockStatus", "status", "type", "availability", "value",
        ):
            if key in value:
                text = _availability_text(value.get(key))
                if text:
                    return text
        for key in ("available", "isAvailable", "inStock", "isInStock"):
            if isinstance(value.get(key), bool):
                return "En stock" if value[key] else "Sin stock"
    return ""


def stock_state(stock: Any, availability: Any) -> dict[str, Any]:
    quantity = _quantity(stock)
    text = _availability_text(availability)
    folded = text.casefold()
    if quantity is not None:
        return {
            "quantity": quantity,
            "quantity_kind": "exact",
            "quantity_label": f"{quantity} unidad{'es' if quantity != 1 else ''}",
            "availability": text or ("En stock" if quantity > 0 else "Sin stock"),
        }
    if isinstance(stock, bool):
        available = stock
    elif any(token in folded for token in OUT_OF_STOCK):
        available = False
    elif any(token in folded for token in IN_STOCK):
        available = True
    else:
        available = None
    if available is False:
        return {
            "quantity": 0,
            "quantity_kind": "unavailable",
            "quantity_label": "0 unidades",
            "availability": text or "Sin stock",
        }
    if available is True:
        return {
            "quantity": None,
            "quantity_kind": "available",
            "quantity_label": "Disponible; cantidad no publicada",
            "availability": text or "En stock",
        }
    return {
        "quantity": None,
        "quantity_kind": "unknown",
        "quantity_label": "No informada por la tienda",
        "availability": text or "Sin información",
    }


def build_product_analysis(result: dict[str, Any], store_titles: dict[str, str]) -> dict[str, Any]:
    from retail.store_display import display_store

    groups: list[dict[str, Any]] = []
    all_offers: list[dict[str, Any]] = []
    for group in result.get("groups") or []:
        offers: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for raw in group.get("offers") or []:
            store = str(raw.get("store") or "")
            product_id = str(raw.get("product_id") or "")
            key = (store, product_id)
            if not store or key in seen:
                continue
            seen.add(key)
            stock = stock_state(raw.get("stock"), raw.get("availability"))
            display_id, display_title = display_store(raw, store_titles)
            offer = {
                "store": store,
                "display_store": display_id,
                "store_title": display_title,
                "product_id": product_id,
                "sku_id": raw.get("sku_id"),
                "name": raw.get("name") or group.get("name") or "Producto",
                "url": raw.get("url"),
                "price": raw.get("price"),
                "price_normal": raw.get("price_normal"),
                "price_all_payment": raw.get("price_all_payment") or raw.get("price_internet") or raw.get("price"),
                "price_card": raw.get("price_card") or raw.get("price_cmr"),
                "payment_card_name": raw.get("payment_card_name"),
                "condition": raw.get("condition") or "unknown",
                "shipping_cost": raw.get("shipping_cost"),
                "shipping_free_threshold": raw.get("shipping_free_threshold"),
                "pickup_available": raw.get("pickup_available"),
                "low_stock": bool(raw.get("low_stock")),
                "variants": raw.get("variants") or [],
                "stock_verified": bool(raw.get("stock_verified")),
                "stock_checked_at": raw.get("stock_checked_at"),
                "entity_confidence": raw.get("entity_confidence") or group.get("entity_confidence"),
                "entity_match_method": raw.get("entity_match_method") or group.get("entity_match_method"),
                "entity_override": raw.get("entity_override"),
                "checked_live": bool(raw.get("from_scrape")),
                **stock,
            }
            offers.append(offer)
            all_offers.append(offer)
        offers.sort(key=lambda item: (item.get("price") is None, item.get("price") or 10**15, item["store_title"]))
        if offers:
            groups.append(
                {
                    "name": group.get("name") or offers[0]["name"],
                    "compare_code": group.get("compare_code"),
                    "entity_confidence": group.get("entity_confidence"),
                    "entity_match_method": group.get("entity_match_method"),
                    "store_count": len({item["store"] for item in offers}),
                    "offers": offers,
                }
            )
    groups.sort(key=lambda item: (-item["store_count"], item["name"]))
    return {
        "query": result.get("query") or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "group_count": len(groups),
        "offer_count": len(all_offers),
        "store_count": len({item["store"] for item in all_offers}),
        "exact_quantity_count": sum(item["quantity_kind"] == "exact" for item in all_offers),
        "groups": groups,
        "warnings": result.get("warnings") or [],
        "store_errors": result.get("store_errors") or [],
    }
