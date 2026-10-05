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


def refresh_product_price(repo: Any, store: str, product_id: str) -> dict[str, Any]:
    """Scrape de la ficha en tienda + upsert + cola de oferta real."""
    document = repo.product_detail(store, product_id)
    if document is None:
        return {"ok": False, "detail": "Producto no encontrado."}
    try:
        from retail.registry import get_client

        client = get_client(store, delay=0, timeout=12, retries=1)
    except Exception as exc:
        return {"ok": False, "detail": f"Tienda no disponible: {exc}"}
    try:
        products = client.scrape(
            Target(kind="product", product_id=product_id, raw_url=document.get("url")),
            max_pages=1,
            max_items=1,
        )
    except Exception as exc:
        logger.info("Refresh precio falló %s/%s: %s", store, product_id, exc)
        return {"ok": False, "detail": "No se pudo consultar el precio ahora."}
    finally:
        try:
            client.close()
        except Exception:
            pass
    product = next(
        (
            item for item in products or []
            if str(getattr(item, "product_id", "") or "") == str(product_id)
            or str(getattr(item, "sku_id", "") or "") == str(product_id)
        ),
        None,
    )
    if product is None and products:
        product = products[0]
    if product is None:
        return {"ok": False, "detail": "La tienda no devolvió el producto."}
    saved = repo.upsert_many([product], extra={"source": "ficha_refresh"})
    offer = product.to_dict(flatten_specs=False) if hasattr(product, "to_dict") else {}
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
