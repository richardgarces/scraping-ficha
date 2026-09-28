"""Enlaces breves persistentes para fichas incluidas en notificaciones."""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote


def public_product_url(store: Any, product_id: Any) -> str:
    if not store or not product_id:
        return ""
    site = os.environ.get("PUBLIC_SITE_URL", "https://precios.meincart.cl").rstrip("/")
    return f"{site}/producto?store={quote(str(store), safe='')}&id={quote(str(product_id), safe='')}"


def short_product_url(repo: Any, store: Any, product_id: Any) -> str:
    """Devuelve el enlace corto o la ficha normal si Mongo no está disponible."""
    fallback = public_product_url(store, product_id)
    if not fallback or repo is None or not hasattr(repo, "product_short_code"):
        return fallback
    try:
        code = str(repo.product_short_code(str(store), str(product_id)) or "")
    except Exception:
        return fallback
    if not code:
        return fallback
    base = (
        os.environ.get("SHORT_LINK_BASE_URL")
        or os.environ.get("PUBLIC_SITE_URL")
        or "https://precios.meincart.cl"
    ).rstrip("/")
    return f"{base}/o/{quote(code, safe='')}"


def attach_short_url(payload: dict[str, Any], repo: Any) -> dict[str, Any]:
    extra = payload.get("extra") or {}
    store = extra.get("store") or payload.get("store")
    product_id = extra.get("product_id") or payload.get("product_id")
    url = short_product_url(repo, store, product_id)
    if url:
        payload["short_url"] = url
    return payload
