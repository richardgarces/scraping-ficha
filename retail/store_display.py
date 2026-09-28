from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import urlparse


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _catalog() -> tuple[dict[str, str], dict[str, str]]:
    from retail.registry import list_stores

    titles: dict[str, str] = {}
    sites: dict[str, str] = {}
    for spec in list_stores():
        titles[spec.id] = spec.title or spec.id
        host = str(spec.site or "").lower().removeprefix("www.").split("/", 1)[0]
        if host:
            sites[host] = spec.id
    # Algunos enlaces de afiliación usan un dominio regional distinto al de
    # la ficha configurada en el scraper.
    sites.setdefault("falabella.com", "falabella")
    return titles, sites


def _knasta_destination(row: Mapping[str, Any]) -> tuple[str, str]:
    titles, sites = _catalog()
    seller = _clean(row.get("seller") or row.get("retail_label"))
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
            return "otro", label
    return "otro", "Otro"


def display_store(row: Mapping[str, Any], titles: Mapping[str, str] | None = None) -> tuple[str, str]:
    """ID y nombre públicos, ocultando al agregador Knasta.

    Knasta no es quien vende el producto. Se muestra el comercio de destino
    informado en el aviso o deducido de su enlace; si falta, se usa “Otro”.
    """
    store_id = _clean(row.get("store")).lower()
    if store_id == "knasta":
        return _knasta_destination(row)
    known = dict(titles or {})
    if not known:
        known, _sites = _catalog()
    return store_id, _clean(row.get("store_title")) or known.get(store_id) or store_id or "Otro"


def display_store_title(row: Mapping[str, Any], titles: Mapping[str, str] | None = None) -> str:
    return display_store(row, titles)[1]
