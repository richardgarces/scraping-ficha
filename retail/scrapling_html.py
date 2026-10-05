"""Piloto Scrapling para tiendas con HTML frágil (no anti-bot / CAPTCHA).

Activa con ``SCRAPLING_STORES=hites,santaritaonline`` (coma-separado).
Requiere el extra opcional ``pip install -e '.[scrapling]'`` (batch/soyo).
No usa FlareSolverr ni evasión de desafíos: solo fetch HTML + parsers existentes
→ mismo ``Product`` / Mongo.

Tiendas del piloto (evidencia):
- ``hites``: Demandware/SFCC; grilla y rutas de imagen cambian (regex frágil).
- ``santaritaonline``: WooCommerce HTML porque la Store API suele devolver 500.
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

# Solo estas dos en el piloto. Ampliar solo con evidencia de HTML frágil (no CAPTCHA).
PILOT_STORES = frozenset({"hites", "santaritaonline"})


def scrapling_store_ids() -> set[str]:
    raw = os.environ.get("SCRAPLING_STORES", "").strip()
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def scrapling_enabled_for(store_id: str) -> bool:
    store = str(store_id or "").strip().lower()
    if not store or store not in scrapling_store_ids():
        return False
    if store not in PILOT_STORES:
        logger.warning(
            "SCRAPLING_STORES incluye %s fuera del piloto (%s); se ignora.",
            store,
            ",".join(sorted(PILOT_STORES)),
        )
        return False
    return True


def scrapling_available() -> bool:
    try:
        from scrapling.fetchers import Fetcher  # noqa: F401

        return True
    except Exception:
        return False


def _absolute_url(url: str, params: dict[str, Any] | None = None) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    query = urlencode({str(k): v for k, v in params.items() if v is not None})
    if parsed.query:
        query = f"{parsed.query}&{query}" if query else parsed.query
    return urlunparse(parsed._replace(query=query))


def fetch_html(url: str, *, params: dict[str, Any] | None = None, timeout: float = 30.0) -> str:
    """Obtiene HTML con Scrapling ``Fetcher`` (sin StealthyFetcher / bypass)."""
    from scrapling.fetchers import Fetcher

    target = _absolute_url(url, params)
    # Timeout en segundos; Scrapling usa kwargs del fetcher HTTP subyacente.
    page = Fetcher.get(target, timeout=int(max(1.0, timeout) * 1000))
    html = getattr(page, "html", None) or getattr(page, "body", None) or str(page)
    if not isinstance(html, str) or not html.strip():
        raise RuntimeError(f"Scrapling no devolvió HTML para {target}")
    return html


def fetch_html_optional(
    store_id: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> str | None:
    """Si el piloto está activo y Scrapling está instalado, devuelve HTML; si no, ``None``."""
    if not scrapling_enabled_for(store_id):
        return None
    if not scrapling_available():
        logger.info(
            "SCRAPLING_STORES activo para %s pero scrapling no está instalado; "
            "se usa HTTP habitual.",
            store_id,
        )
        return None
    try:
        return fetch_html(url, params=params, timeout=timeout)
    except Exception as exc:
        logger.info("Scrapling falló para %s (%s); se usará HTTP habitual.", store_id, exc)
        return None
