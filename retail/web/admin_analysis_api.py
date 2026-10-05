from __future__ import annotations

from functools import partial
import uuid

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from retail.product_analysis import (
    FICHA_QUERY_MAX,
    TEXT_QUERY_MAX,
    analysis_search_text,
    build_product_analysis,
    parse_ficha_ref,
)
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


def _resolve_analysis_query(repo, raw_query: str) -> tuple[str, dict | None]:
    """URI de ficha → nombre del producto semilla; texto libre se deja igual."""
    query = " ".join(str(raw_query or "").split()).strip()
    if len(query) < 2:
        raise HTTPException(status_code=400, detail="Escribe un producto o pega la URI de su ficha.")
    ficha = parse_ficha_ref(query)
    if ficha is None:
        if len(query) > TEXT_QUERY_MAX:
            raise HTTPException(status_code=400, detail="La búsqueda es demasiado larga.")
        return query, None
    if len(query) > FICHA_QUERY_MAX:
        raise HTTPException(status_code=400, detail="La URI de ficha es demasiado larga.")
    store, product_id = ficha
    document = repo.product_detail(store, product_id)
    if document is None:
        raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")
    search_text = analysis_search_text(document)
    if len(search_text) < 2:
        raise HTTPException(
            status_code=400,
            detail="Ese producto no tiene nombre para buscar comparables.",
        )
    return search_text, {"store": store, "product_id": product_id, "name": document.get("name")}


async def _product_analysis(request: Request, *, admin_only: bool = False) -> dict:
    body = await request.json()
    live = body.get("live") is True
    repo = repo_or_503()
    try:
        user = current_user(request, repo, required=True, admin=admin_only) or {}
        if live and user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Solo el administrador puede consultar las tiendas ahora.")
        query, seed = _resolve_analysis_query(repo, body.get("query") or "")
    finally:
        repo.close()

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
    if seed:
        payload["seed"] = seed
        payload["resolved_query"] = query
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
        user = current_user(request, repo, required=True, admin=True) or {}
        body = await request.json()
        action = str(body.get("action") or "").strip().lower()
        products = _entity_products(body)
        if action == "merge":
            if len(products) < 2:
                raise HTTPException(status_code=400, detail="Selecciona al menos dos productos para unir.")
            override = f"manual:{uuid.uuid4().hex}"
            overrides = [override] * len(products)
        elif action in {"split", "incorrect"}:
            # «incorrect» = el par automático ≥80% está mal: forzar separación.
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
        if action == "incorrect":
            from retail.identity_audit import record_identity_audit

            record_identity_audit(
                repo,
                action="incorrect",
                products=products,
                pair_id=str(body.get("pair_id") or ""),
                confidence=(
                    float(body["confidence"])
                    if body.get("confidence") is not None
                    else None
                ),
                note=str(body.get("note") or "Par marcado como identidad incorrecta"),
                actor=str(user.get("email") or user.get("id") or "admin"),
            )
        return {"ok": True, "action": action, "entity_override": override, **saved}
    finally:
        repo.close()


@router.get("/api/admin/identity-audit/sample")
async def identity_audit_sample(request: Request) -> dict:
    """Muestra pares de identidad con confianza ≥80% para revisión admin."""
    from retail.identity_audit import load_identity_audit_sample
    from retail.reales import MIN_ENTITY_CONFIDENCE

    repo = repo_or_503()
    try:
        current_user(request, repo, required=True, admin=True)
        try:
            limit = int(request.query_params.get("limit") or 20)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        try:
            min_confidence = float(
                request.query_params.get("min_confidence") or MIN_ENTITY_CONFIDENCE
            )
        except (TypeError, ValueError):
            min_confidence = MIN_ENTITY_CONFIDENCE
        seed_raw = request.query_params.get("seed")
        seed = int(seed_raw) if seed_raw not in (None, "") else None
        return await run_in_threadpool(
            load_identity_audit_sample,
            repo,
            min_confidence=min_confidence,
            limit=limit,
            seed=seed,
        )
    finally:
        repo.close()


@router.post("/api/admin/identity-audit/override")
async def identity_audit_override(request: Request) -> dict:
    """Atajo: marcar par incorrecto o forzar unión/separación desde el muestreo."""
    from retail.identity_audit import record_identity_audit

    repo = repo_or_503()
    try:
        user = current_user(request, repo, required=True, admin=True) or {}
        body = await request.json()
        action = str(body.get("action") or "incorrect").strip().lower()
        products = _entity_products(body)
        if action == "incorrect":
            if len(products) < 2:
                raise HTTPException(status_code=400, detail="Indica el par a marcar como incorrecto.")
            overrides = [f"manual:{uuid.uuid4().hex}" for _item in products]
            saved = repo.set_entity_overrides(products, overrides)
            audit = record_identity_audit(
                repo,
                action="incorrect",
                products=products,
                pair_id=str(body.get("pair_id") or ""),
                confidence=(
                    float(body["confidence"])
                    if body.get("confidence") is not None
                    else None
                ),
                note=str(body.get("note") or ""),
                actor=str(user.get("email") or user.get("id") or "admin"),
            )
            return {"ok": True, "action": "incorrect", **saved, "audit": audit}
        if action == "confirm":
            audit = record_identity_audit(
                repo,
                action="confirm",
                products=products,
                pair_id=str(body.get("pair_id") or ""),
                confidence=(
                    float(body["confidence"])
                    if body.get("confidence") is not None
                    else None
                ),
                note=str(body.get("note") or "Par confirmado en muestreo"),
                actor=str(user.get("email") or user.get("id") or "admin"),
            )
            return {"ok": True, "action": "confirm", "audit": audit}
        raise HTTPException(status_code=400, detail="Acción inválida (incorrect|confirm).")
    finally:
        repo.close()
