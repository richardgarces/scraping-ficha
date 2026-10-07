from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse

# Id interno del agregador: se mantiene en Mongo/API, nunca se muestra en la UI.
_HIDDEN_AGGREGATOR_IDS = frozenset({"knasta"})
_PUBLIC_FALLBACK_TITLE = "Otro"
# Sufijo de marca país en títulos de retail («Easy Chile» → «Easy»).
# No toca compuestos (Chileautos) ni marcas que empiezan por Chile (Chile Perfume).
_CHILE_SUFFIX = re.compile(r"(?i)\s+Chile\s*$")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def clean_store_display_name(label: str | None) -> str:
    """Quita el sufijo «Chile» del nombre visible; no altera ids/slugs internos."""
    text = _clean(label)
    if not text:
        return ""
    cleaned = _CHILE_SUFFIX.sub("", text).strip()
    return cleaned or text


def public_store_key(store_id: str | None) -> str:
    """Clave visible cuando la UI imprimiría un id crudo (nunca el agregador)."""
    key = _clean(store_id).lower()
    if key in _HIDDEN_AGGREGATOR_IDS:
        return "otro"
    return key


def public_store_label(store_id: str | None, titles: Mapping[str, str] | None = None) -> str:
    """Nombre visible para un id de tienda sin filtrar por producto."""
    key = _clean(store_id).lower()
    if key in _HIDDEN_AGGREGATOR_IDS:
        return _PUBLIC_FALLBACK_TITLE
    known = dict(titles or {})
    if not known and key:
        known, _sites = _catalog()
    return clean_store_display_name(known.get(key) or key or _PUBLIC_FALLBACK_TITLE)


def _catalog() -> tuple[dict[str, str], dict[str, str]]:
    from retail.registry import list_stores

    titles: dict[str, str] = {}
    sites: dict[str, str] = {}
    for spec in list_stores():
        titles[spec.id] = clean_store_display_name(spec.title or spec.id)
        host = str(spec.site or "").lower().removeprefix("www.").split("/", 1)[0]
        if host:
            sites[host] = spec.id
    # Algunos enlaces de afiliación usan un dominio regional distinto al de
    # la ficha configurada en el scraper.
    sites.setdefault("falabella.com", "falabella")
    return titles, sites


def _knasta_destination(row: Mapping[str, Any]) -> tuple[str, str]:
    titles, sites = _catalog()
    # Normalizar seller («Falabella Chile» → «Falabella») antes de mapear al catálogo.
    seller = clean_store_display_name(row.get("seller") or row.get("retail_label"))
    seller_key = seller.casefold()
    if seller and seller_key not in {"knasta", "otro", "otros"}:
        for store_id, title in titles.items():
            if seller_key in {store_id.casefold(), title.casefold()}:
                return store_id, title
        return "otro", seller

    try:
        host = urlparse(_clean(row.get("url"))).hostname or ""
    except ValueError:
        host = ""
    host = host.lower().removeprefix("www.")
    if host and not host.endswith("knasta.cl"):
        for site, store_id in sites.items():
            if host == site or host.endswith("." + site) or site.endswith("." + host):
                return store_id, titles.get(store_id, store_id)
        label = re.sub(r"[^a-z0-9]+", " ", host.split(".")[0], flags=re.I).strip().title()
        if label:
            return "otro", clean_store_display_name(label)
    return "otro", _PUBLIC_FALLBACK_TITLE


def display_store(row: Mapping[str, Any], titles: Mapping[str, str] | None = None) -> tuple[str, str]:
    """ID y nombre públicos, ocultando al agregador interno.

    El agregador no es quien vende el producto. Se muestra el comercio de
    destino informado en el aviso o deducido de su enlace; si falta, “Otro”.
    """
    store_id = _clean(row.get("store")).lower()
    if store_id in _HIDDEN_AGGREGATOR_IDS:
        return _knasta_destination(row)
    known = dict(titles or {})
    if not known:
        known, _sites = _catalog()
    title = _clean(row.get("store_title")) or known.get(store_id) or store_id or _PUBLIC_FALLBACK_TITLE
    if title.casefold() in {"knasta", "knaste"}:
        title = _PUBLIC_FALLBACK_TITLE
    return store_id, clean_store_display_name(title)


def display_store_title(row: Mapping[str, Any], titles: Mapping[str, str] | None = None) -> str:
    return display_store(row, titles)[1]
