"""Actualización puntual de precio de una ficha (enqueue, no sync largo)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

from retail.models import Target

logger = logging.getLogger(__name__)

_inflight: set[tuple[str, str]] = set()
_lock = threading.Lock()


def claim_refresh(store: str, product_id: str) -> bool:
    key = (store, product_id)
    with _lock:
        if key in _inflight:
            return False
        _inflight.add(key)
        return True


def release_refresh(store: str, product_id: str) -> None:
    with _lock:
        _inflight.discard((store, product_id))


def _destination_refresh_target(store: str, product_id: str, document: dict[str, Any]) -> tuple[str, str] | None:
    """Para agregadores (knasta), el precio real vive en la tienda de destino."""
    if str(store or "").lower() != "knasta":
        return None
    retail, sep, sku = str(product_id or "").partition("#")
    if sep and retail and sku:
        return retail.lower(), sku
    url = str(document.get("url") or "")
    if "falabella.com" in url and "/product/" in url:
        parts = [part for part in url.split("/") if part]
        try:
            return "falabella", parts[parts.index("product") + 1]
        except (ValueError, IndexError):
            return None
    return None


def _scrape_product(store: str, product_id: str, raw_url: str | None) -> Any | None:
    from retail.registry import get_client

    client = get_client(store, delay=0, timeout=12, retries=1)
    try:
        products = client.scrape(
            Target(kind="product", product_id=product_id, raw_url=raw_url),
            max_pages=1,
            max_items=1,
        )
    finally:
        try:
            client.close()
        except Exception:
            pass
    if not products:
        return None
    return next(
        (
            item for item in products
            if str(getattr(item, "product_id", "") or "") == str(product_id)
            or str(getattr(item, "sku_id", "") or "") == str(product_id)
        ),
        products[0],
    )


def refresh_product_price(repo: Any, store: str, product_id: str) -> dict[str, Any]:
    """Scrape de la ficha en tienda + upsert + cola de oferta real."""
    document = repo.product_detail(store, product_id)
    if document is None:
        return {"ok": False, "detail": "Producto no encontrado."}

    product = None
    try:
        product = _scrape_product(store, product_id, document.get("url"))
    except Exception as exc:
        logger.info("Refresh precio falló %s/%s: %s", store, product_id, exc)

    # Knasta a menudo cae por Cloudflare; el aviso apunta a Falabella/Paris/etc.
    if product is None:
        destination = _destination_refresh_target(store, product_id, document)
        if destination:
            dest_store, dest_id = destination
            try:
                product = _scrape_product(dest_store, dest_id, document.get("url"))
            except Exception as exc:
                logger.info(
                    "Refresh destino falló %s/%s via %s/%s: %s",
                    store, product_id, dest_store, dest_id, exc,
                )
            if product is not None:
                # Conservar la clave del aviso agregado; solo traer precios frescos.
                product.store = store
                product.product_id = product_id
                if not product.sku_id:
                    product.sku_id = dest_id

    if product is None:
        return {"ok": False, "detail": "No se pudo consultar el precio ahora."}

    saved = repo.upsert_many([product], extra={"source": "ficha_refresh"})
    offer = product.to_dict(flatten_specs=False) if hasattr(product, "to_dict") else {}
    # La oferta real/historial deben quedar bajo la clave de la ficha abierta.
    offer["store"] = store
    offer["product_id"] = product_id
    queue = {"candidates": 0, "enqueued": 0}
    try:
        if offer.get("price") and offer.get("price_normal"):
            queue = repo.enqueue_real_offer_candidates([offer])
    except Exception:
        pass
    # Adelanta prioridad del catálogo si existe.
    catalog_id = str(document.get("catalog_id") or "").strip()
    if catalog_id:
        now = datetime.now(timezone.utc)
        repo.scrape_priorities.update_one(
            {"catalog_id": catalog_id},
            {
                "$set": {
                    "score": 95,
                    "tier": "high",
                    "next_due_at": now,
                    "updated_at": now,
                    "boost_reason": "ficha_refresh",
                }
            },
            upsert=False,
        )
    fresh = repo.product_detail(store, product_id) or {}
    return {
        "ok": True,
        "price": fresh.get("price") or getattr(product, "price", None),
        "price_normal": fresh.get("price_normal") or getattr(product, "price_normal", None),
        "updated_at": (
            fresh.get("updated_at").isoformat()
            if hasattr(fresh.get("updated_at"), "isoformat")
            else fresh.get("updated_at")
        ),
        "saved": saved,
        "real_offer_queue": queue,
    }


def launch_product_refresh(repo_factory, store: str, product_id: str) -> dict[str, Any]:
    """Encola en un hilo; el caller no espera el scrape."""
    if not claim_refresh(store, product_id):
        return {"ok": True, "queued": False, "detail": "Ya hay una actualización en curso."}

    def _run() -> None:
        repo = None
        try:
            repo = repo_factory()
            if repo is None:
                return
            refresh_product_price(repo, store, product_id)
        except Exception:
            logger.exception("Refresh en segundo plano falló %s/%s", store, product_id)
        finally:
            release_refresh(store, product_id)
            if repo is not None:
                try:
                    repo.close()
                except Exception:
                    pass

    thread = threading.Thread(target=_run, name=f"price-refresh-{store}-{product_id}", daemon=True)
    thread.start()
    return {"ok": True, "queued": True, "detail": "Actualización encolada."}
