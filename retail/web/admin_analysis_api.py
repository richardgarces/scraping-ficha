from __future__ import annotations

from functools import partial
import uuid

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from retail.product_analysis import build_product_analysis
from retail.registry import list_stores
from retail.search import SEARCH_TIMEOUT, search_products
from retail.stock_validation import validate_result_stock
from retail.web.deps import current_user, repo_or_503

router = APIRouter()

_ADMIN_OFFER_FIELDS = {
    "shipping_cost", "shipping_free_threshold", "pickup_available",
    "quantity", "quantity_kind", "quantity_label", "availability",
    "low_stock", "variants", "stock_verified", "stock_checked_at",
    "entity_confidence", "entity_match_method", "entity_override", "checked_live",
}


def _entity_products(body: dict) -> list[tuple[str, str]]:
    raw = body.get("products") or []
    if not isinstance(raw, list) or not (1 <= len(raw) <= 20):
        raise HTTPException(status_code=400, detail="Selecciona entre 1 y 20 productos.")
    products: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Selección de productos inválida.")
        store = str(item.get("store") or "").strip().lower()[:80]
        product_id = str(item.get("product_id") or "").strip()[:180]
        if not store or not product_id:
            raise HTTPException(status_code=400, detail="Falta tienda o identificador del producto.")
        key = (store, product_id)
        if key not in products:
            products.append(key)
    return products


async def _product_analysis(request: Request, *, admin_only: bool = False) -> dict:
    repo = repo_or_503()
    try:
        user = current_user(request, repo, required=True, admin=admin_only) or {}
    finally:
        repo.close()

    body = await request.json()
    query = " ".join(str(body.get("query") or "").split())
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Escribe un producto para analizar.")
    if len(query) > 160:
        raise HTTPException(status_code=400, detail="La búsqueda es demasiado larga.")
    live = body.get("live") is True
    if live and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Solo el administrador puede consultar las tiendas ahora.")
    try:
        result = await run_in_threadpool(
            partial(
                search_products,
                query,
                source="both" if live else "db",
                max_items=8,
                delay=0.5,
                timeout=SEARCH_TIMEOUT,
                persist=live,
                price_band=False,
                fresh=live,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"No se pudo completar el análisis: {exc}") from exc
    if live:
        await run_in_threadpool(validate_result_stock, result)
    titles = {spec.id: spec.title for spec in list_stores()}
    payload = build_product_analysis(result, titles)
    if user.get("role") != "admin":
        payload.pop("exact_quantity_count", None)
        for group in payload.get("groups") or []:
            group.pop("entity_confidence", None)
            group.pop("entity_match_method", None)
            for offer in group.get("offers") or []:
                for field in _ADMIN_OFFER_FIELDS:
                    offer.pop(field, None)
    return payload


@router.post("/api/product-analysis")
async def product_analysis(request: Request) -> dict:
    """Análisis guardado para cuentas aprobadas; consulta en vivo solo para admin."""
    return await _product_analysis(request)


@router.post("/api/admin/product-analysis")
async def admin_product_analysis(request: Request) -> dict:
    """Ruta conservada para compatibilidad con clientes administrativos anteriores."""
    return await _product_analysis(request, admin_only=True)


@router.post("/api/admin/entity-overrides")
async def entity_overrides(request: Request) -> dict:
    """Une, separa o devuelve al emparejamiento automático productos guardados."""
    repo = repo_or_503()
    try:
        current_user(request, repo, required=True, admin=True)
        body = await request.json()
        action = str(body.get("action") or "").strip().lower()
        products = _entity_products(body)
        if action == "merge":
            if len(products) < 2:
                raise HTTPException(status_code=400, detail="Selecciona al menos dos productos para unir.")
            override = f"manual:{uuid.uuid4().hex}"
            overrides = [override] * len(products)
        elif action == "split":
            override = None
            overrides = [f"manual:{uuid.uuid4().hex}" for _item in products]
        elif action == "reset":
            override = None
            overrides = [None] * len(products)
        else:
            raise HTTPException(status_code=400, detail="Acción inválida.")
        saved = repo.set_entity_overrides(products, overrides)
        if saved["matched"] != len(products):
            raise HTTPException(status_code=404, detail="Uno o más productos ya no existen.")
        return {"ok": True, "action": action, "entity_override": override, **saved}
    finally:
        repo.close()
