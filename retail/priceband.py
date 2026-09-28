"""Banda de precio que la consulta implica, para no mezclar $15.000 con $2.000.000.

Buscar "tv" o "lavaplatos" trae el aparato y, a veces, un accesorio barato o un
modelo comercial enorme. Acá se mira el grueso de los precios que ya pasaron el
filtro de relevancia y se descarta lo que queda fuera de esa nube.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Cuántas veces puede alejarse un precio del centro del grupo y seguir contando.
SPAN = 2.5
# Si el más caro no llega a esto veces el más barato, no hay mezcla que cortar.
COMPACT = 8
MIN_PRICES = 3

_LOW = ("barato", "barata", "baratos", "baratas", "economico", "economica", "economicos", "economicas")
_HIGH = ("gamer", "gaming", "premium", "profesional", "profesionales")
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


@dataclass(frozen=True, slots=True)
class Band:
    low: int
    high: int
    typical: int
    preference: str | None


def preference(query: str) -> str | None:
    tokens = set(_TOKEN_RE.findall(_fold(query)))
    if tokens & set(_LOW):
        return "low"
    if tokens & set(_HIGH):
        return "high"
    return None


def _window(prices: list[int], center: int) -> list[int]:
    lo = center / SPAN
    hi = center * SPAN
    return [price for price in prices if lo <= price <= hi]


def fit(prices: list[int], want: str | None) -> Band | None:
    """La nube de precios donde vive esta búsqueda, o None si no conviene recortar."""
    values = sorted(price for price in prices if price)
    if len(values) < MIN_PRICES:
        return None
    if want is None and values[-1] / values[0] <= COMPACT:
        return None

    scored: list[tuple[int, int, int]] = []
    for center in values:
        members = _window(values, center)
        scored.append((len(members), center, int(round(sum(members) / len(members)))))
    needed = max(MIN_PRICES, (len(values) + 2) // 4)
    viable = [row for row in scored if row[0] >= needed] or scored

    if want == "low":
        size, _, typical = min(viable, key=lambda row: (row[2], -row[0]))
    elif want == "high":
        size, _, typical = max(viable, key=lambda row: (row[2], row[0]))
    else:
        # El grupo más poblado; si empatan, el más cercano a la mediana.
        median = values[len(values) // 2]
        size, _, typical = max(viable, key=lambda row: (row[0], -abs(row[2] - median)))

    if size < MIN_PRICES:
        return None
    low = max(1, int(typical / SPAN))
    high = int(typical * SPAN)
    if want is None and values[0] >= low and values[-1] <= high:
        return None
    return Band(low=low, high=high, typical=typical, preference=want)


def _money(value: int) -> str:
    return f"${value:,}".replace(",", ".")


def conflict(price: int | None, band: Band | None) -> str | None:
    if band is None or price in (None, 0):
        return None
    if band.low <= price <= band.high:
        return None
    if price < band.low:
        if band.preference == "high":
            return f"sale {_money(price)} y pediste gama alta, el grueso está en {_money(band.typical)}"
        return f"sale {_money(price)} y el grueso de esta búsqueda está en {_money(band.typical)}"
    if band.preference == "low":
        return f"sale {_money(price)} y pediste algo barato, el grueso está en {_money(band.typical)}"
    return f"sale {_money(price)} y el grueso de esta búsqueda está en {_money(band.typical)}"
