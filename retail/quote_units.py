"""Compatibilidad de unidades kg/l/m para cotizaciones B2B.

Reglas documentadas (no se inventan factores arbitrarios):

- ``unidad`` / ``pack``: el catálogo se trata como 1 unidad vendible (como hoy).
- ``litro``: compatible si el aviso declara volumen en ml/cc/l/litro.
  Equivalencias: 1 l = 1000 ml = 1000 cc. Precio comparable =
  ``precio_catálogo / litros_del_envase`` (CLP por litro).
- ``kg``: compatible si declara masa en g/gr/kg.
  Equivalencias: 1 kg = 1000 g. Precio comparable =
  ``precio_catálogo / kg_del_envase``.
- ``metro``: compatible si declara longitud en mm/cm/m/metro.
  Equivalencias: 1 m = 100 cm = 1000 mm. Precio comparable =
  ``precio_catálogo / metros_del_envase``.

Sin cantidad explícita en el nombre/especificaciones del catálogo, la fila
queda pendiente («requiere conversión revisada»): no se asume 1 kg/l/m.
"""

from __future__ import annotations

import re
from typing import Any

_VOLUME_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(ml|cc|litros?|lts?\.?|l)\b",
    re.I,
)
_MASS_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(kg|kilos?|gramos?|grs?\.?|g)\b",
    re.I,
)
_LENGTH_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(metros?|mts?\.?|m|cm|mm)\b",
    re.I,
)

VOLUME_TO_LITRO = {
    "ml": 0.001,
    "cc": 0.001,
    "l": 1.0,
    "lt": 1.0,
    "lts": 1.0,
    "litro": 1.0,
    "litros": 1.0,
}
MASS_TO_KG = {
    "g": 0.001,
    "gr": 0.001,
    "grs": 0.001,
    "gramo": 0.001,
    "gramos": 0.001,
    "kg": 1.0,
    "kilo": 1.0,
    "kilos": 1.0,
}
LENGTH_TO_M = {
    "mm": 0.001,
    "cm": 0.01,
    "m": 1.0,
    "mt": 1.0,
    "mts": 1.0,
    "metro": 1.0,
    "metros": 1.0,
}


def _blob(product: Any) -> str:
    if isinstance(product, dict):
        parts = [
            product.get("name"),
            product.get("brand"),
            " ".join(
                f"{key} {value}"
                for key, value in (product.get("specifications") or {}).items()
            ),
        ]
        return " ".join(str(part or "") for part in parts)
    parts = [
        getattr(product, "name", None),
        getattr(product, "brand", None),
        " ".join(
            f"{key} {value}"
            for key, value in (getattr(product, "specifications", None) or {}).items()
        ),
    ]
    return " ".join(str(part or "") for part in parts)


def _amount(match: re.Match[str]) -> float:
    return float(match.group(1).replace(",", "."))


def detect_catalog_measure(product: Any) -> tuple[str | None, float | None]:
    """Devuelve (familia, magnitud en unidad canónica) o (None, None)."""
    text = _blob(product)
    volume = _VOLUME_RE.search(text)
    if volume:
        unit = volume.group(2).lower().rstrip(".")
        factor = VOLUME_TO_LITRO.get(unit)
        if factor:
            liters = _amount(volume) * factor
            if liters > 0:
                return "litro", liters
    mass = _MASS_RE.search(text)
    if mass:
        unit = mass.group(2).lower().rstrip(".")
        factor = MASS_TO_KG.get(unit)
        if factor:
            kilos = _amount(mass) * factor
            if kilos > 0:
                return "kg", kilos
    length = _LENGTH_RE.search(text)
    if length:
        unit = length.group(2).lower().rstrip(".")
        factor = LENGTH_TO_M.get(unit)
        if factor:
            meters = _amount(length) * factor
            if meters > 0:
                return "metro", meters
    return None, None


def unit_price_for_quote(
    line_unit: str,
    catalog_price: int,
    product: Any,
) -> tuple[bool, int | None, list[str]]:
    """¿Se puede comparar la línea con este aviso? Precio unitario canónico.

    Returns:
        compatible, precio_por_unidad_de_cotización (CLP enteros), issues
    """
    unit = str(line_unit or "unidad").strip().lower()
    if unit in {"unidad", "pack"}:
        return True, int(catalog_price), []
    if unit not in {"kg", "litro", "metro"}:
        return False, None, ["Unidad de cotización no soportada."]
    family, magnitude = detect_catalog_measure(product)
    if family != unit or not magnitude:
        return False, None, [
            f"La unidad «{unit}» requiere conversión explícita desde el envase del catálogo."
        ]
    per_unit = int(round(catalog_price / magnitude))
    if per_unit < 1:
        return False, None, ["El precio por unidad convertida es inválido."]
    return True, per_unit, []
