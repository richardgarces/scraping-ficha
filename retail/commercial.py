"""Normalización comercial común a todas las tiendas.

Los parsers de cada comercio siguen siendo la fuente principal. Estas reglas
completan datos ausentes sin inventarlos y dejan trazabilidad de su origen.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

CONDITIONS = {"new", "refurbished", "open_box", "display", "used", "unknown"}

_CONDITION_RULES = (
    ("refurbished", (
        "reacondicionado", "refurbished", "renewed", "grado a", "grado b",
        "detalles esteticos", "saldo de tienda", "producto saldo",
    )),
    ("open_box", (
        "open box", "caja abierta", "devolucion de cliente", "embalaje abierto",
        "empaque danado", "empaque abierto",
    )),
    ("display", ("exhibicion", "producto de muestra", "equipo demo", "vitrina")),
    ("used", ("usado", "segunda mano", "pre owned", "pre-owned")),
)

CARD_NAMES = {
    "falabella": "CMR Falabella",
    "sodimac": "CMR Falabella",
    "tottus": "CMR Falabella",
    "paris": "Cencosud Scotiabank",
    "easy": "Cencosud Scotiabank",
    "ripley": "Tarjeta Ripley",
    "ahumada": "CMR Falabella",
}

_MONEY = r"(?:\$\s*)?(\d{1,3}(?:[.\s]\d{3})+|\d{3,8})"
_SHIPPING_RE = re.compile(rf"(?:despacho|env[ií]o|delivery)\s*(?:desde|por|a)?\s*{_MONEY}", re.I)
_FREE_THRESHOLD_RE = re.compile(
    rf"(?:despacho|env[ií]o)\s+gratis[^\d]{{0,45}}(?:sobre|desde|por compras? (?:sobre|desde))\s*{_MONEY}",
    re.I,
)
_UNCONDITIONAL_FREE_RE = re.compile(r"(?:despacho|env[ií]o)\s+gratis(?![^.]{0,50}(?:sobre|desde))", re.I)
_PICKUP_RE = re.compile(r"retiro\s+(?:gratis\s+)?en\s+(?:tienda|local)|click\s*(?:&|y)\s*collect", re.I)
_LOW_STOCK_RE = re.compile(r"(?:[uú]ltimas?\s+\d+\s+unidades?|[uú]ltimas?\s+unidades?|poco stock)", re.I)
_CAE_RE = re.compile(r"\bCAE\s*:?[\s\xa0]*(\d{1,3}(?:[.,]\d+)?)\s*%", re.I)
_INSTALLMENTS_RE = re.compile(r"\b(\d{1,3})\s*cuotas?\b", re.I)
_FINANCED_TOTAL_RE = re.compile(
    rf"(?:costo|valor|monto|precio)\s+total(?:\s+del\s+cr[eé]dito)?[^\d]{{0,30}}{_MONEY}", re.I
)


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", text).strip()


def normalize_condition(value: Any) -> str:
    raw = fold(value).replace(" ", "_")
    aliases = {
        "nuevo": "new", "new": "new", "reacondicionado": "refurbished",
        "refurbished": "refurbished", "openbox": "open_box", "open_box": "open_box",
        "exhibicion": "display", "display": "display", "usado": "used", "used": "used",
    }
    normalized = aliases.get(raw, raw)
    return normalized if normalized in CONDITIONS else "unknown"


def detect_condition(*values: Any) -> tuple[str, float, str | None]:
    text = fold(" ".join(str(value or "") for value in values))
    for condition, words in _CONDITION_RULES:
        if any(word in text for word in words):
            return condition, 0.98, "rule"
    # En retail, "nuevo" solo se acepta cuando está escrito expresamente.
    if re.search(r"\b(?:producto|equipo|estado)?\s*nuevo\b", text):
        return "new", 0.9, "rule"
    return "unknown", 0.0, None


def condition_group(value: Any) -> str:
    """Unknown puede compararse con nuevo, nunca con una condición de uso explícita."""
    condition = normalize_condition(value)
    return "new_or_unknown" if condition in {"new", "unknown"} else condition


def conditions_compatible(left: Any, right: Any) -> bool:
    return condition_group(left) == condition_group(right)


def parse_money(value: Any) -> int | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return int(digits) if digits else None


def extract_shipping(text: Any) -> dict[str, Any]:
    raw = str(text or "")
    result: dict[str, Any] = {}
    threshold = _FREE_THRESHOLD_RE.search(raw)
    if threshold:
        result["shipping_free_threshold"] = parse_money(threshold.group(1))
    elif _UNCONDITIONAL_FREE_RE.search(raw):
        result["shipping_cost"] = 0
    priced = _SHIPPING_RE.search(raw)
    if priced and "shipping_cost" not in result:
        result["shipping_cost"] = parse_money(priced.group(1))
    if _PICKUP_RE.search(raw):
        result["pickup_available"] = True
    if result:
        result["shipping_source"] = "visible_text"
    return result


def extract_financing(text: Any) -> dict[str, Any]:
    """Extrae letra chica visible sin calcular ni inferir una tasa."""
    raw = str(text or "")
    result: dict[str, Any] = {}
    cae = _CAE_RE.search(raw)
    installments = _INSTALLMENTS_RE.search(raw)
    total = _FINANCED_TOTAL_RE.search(raw)
    if cae:
        result["financial_cae"] = float(cae.group(1).replace(",", "."))
    if installments:
        result["installment_count"] = int(installments.group(1))
    if total:
        result["installment_total"] = parse_money(total.group(1))
    if result:
        sentences = re.split(r"(?<=[.!?])\s+", raw)
        relevant = next(
            (sentence.strip() for sentence in sentences if re.search(r"\b(?:CAE|cuotas?|costo total)\b", sentence, re.I)),
            "",
        )
        result["payment_conditions"] = relevant[:300] or None
    return result


def shipping_comparable(rows: list[Any]) -> bool:
    """Solo compara despacho conocido y referido a una misma región."""
    def value(row: Any, field: str) -> Any:
        return row.get(field) if isinstance(row, dict) else getattr(row, field, None)

    if not rows or any(value(row, "shipping_cost") is None for row in rows):
        return False
    regions = {fold(value(row, "shipping_region")) for row in rows}
    regions.discard("")
    if not regions:
        return True
    return len(regions) == 1 and all(bool(fold(value(row, "shipping_region"))) for row in rows)


def detects_low_stock(*values: Any) -> bool:
    return bool(_LOW_STOCK_RE.search(" ".join(str(value or "") for value in values)))


def normalize_variants(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    found: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or raw.get("title") or raw.get("value") or raw.get("sku") or "").strip()
        sku = str(raw.get("sku") or raw.get("sku_id") or raw.get("id") or "").strip()
        stock = raw.get("stock")
        if stock is None:
            stock = raw.get("available_quantity", raw.get("availableQuantity"))
        if stock is None:
            stock = raw.get("inventory_quantity")
        try:
            stock = max(0, int(float(stock))) if stock not in (None, "") and not isinstance(stock, bool) else None
        except (TypeError, ValueError):
            stock = None
        available = raw.get("available")
        if available is None and stock is not None:
            available = stock > 0
        found.append({
            "id": str(raw.get("id") or sku),
            "sku": sku,
            "name": name,
            "stock": stock,
            "available": available if isinstance(available, bool) else None,
        })
    return found


def landed_price(price: Any, shipping_cost: Any) -> int | None:
    try:
        base = int(price)
        shipping = int(shipping_cost)
    except (TypeError, ValueError):
        return None
    return base + max(0, shipping) if base > 0 else None
