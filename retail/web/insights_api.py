from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from retail import thumbs
from retail.compare import is_catalog_mirror, same_product_pack
from retail.commercial import conditions_compatible, landed_price, shipping_comparable
from retail.ficha_extra import (
    description_of,
    enrich_from_store,
    pick_related,
    search_text,
    specifications_of,
)
from retail.ficha_sweep import iter_ficha_sweep
from retail.models import normalize_product_url
from retail.pricing import (
    apply_cheaper_elsewhere_gate,
    buy_or_wait,
    chart_history,
    classified_drop_events,
    parse_moment,
    price_observations,
    price_stats,
    series,
)
from retail.offer_screenshot import (
    annotate_store_bot_checks,
    bot_check_api_rows,
    list_store_bot_checks,
)
from retail.registry import list_stores
from retail.search import connect_repo
from retail.web.deps import current_user

router = APIRouter()

# Un mes es lo mínimo para que el ranking de tiendas hable de la tienda y no
# del puñado de días que alcanzamos a mirar.
REPORT_MIN_DAYS = 30
# Misma ventana que usa el ranking. Si el detalle mirara otro tope, el número
# de la tabla y la lista del clic dejarían de coincidir.
REPORT_MIN_POINTS = 3
REPORT_SCAN_LIMIT = 20000


def _repo_or_404():
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    return repo


def _points(document: dict[str, Any], field: str = "price") -> list[dict[str, Any]]:
    entries = [row for row in document.get("price_history") or [] if isinstance(row, dict)]
    if any(row.get("price_basis") == "all_payment" for row in entries):
        entries = [row for row in entries if row.get("price_basis") == "all_payment"]
    rows = []
    for entry in entries:
        value = entry.get(field)
        if value in (None, 0):
            continue
        moment = parse_moment(entry.get("scraped_at"))
        rows.append({"price": int(value), "scraped_at": moment.isoformat() if moment else None})
    rows.sort(key=lambda row: row.get("scraped_at") or "")
    return rows


def _card(document: dict[str, Any]) -> dict[str, Any]:
    from retail.store_display import display_store

    observations = price_observations(
        document.get("price_history"),
        current_offer=document.get("price"),
        current_normal=document.get("price_normal"),
        current_at=document.get("updated_at"),
    )
    points = [
        {"price": row["offer"], "scraped_at": row["scraped_at"], "day": row["day"]}
        for row in observations
        if row.get("offer") is not None
    ]
    normal_points = [
        {"price": row["normal"], "scraped_at": row["scraped_at"], "day": row["day"]}
        for row in observations
        if row.get("normal") is not None
    ]
    display_id, display_title = display_store(document)
    return {
        "store": document.get("store"),
        "display_store": display_id,
        "store_title": display_title,
        "product_id": document.get("product_id"),
        "sku_id": document.get("sku_id"),
        "name": document.get("name"),
        "brand": document.get("brand"),
        "seller": document.get("seller") or "",
        "url": normalize_product_url(document.get("store"), document.get("url"), document.get("name")),
        "category": document.get("category") or document.get("catalog_category"),
        "description": description_of(document),
        "specifications": specifications_of(document),
        "discount_percent": document.get("discount_percent"),
        "image_url": document.get("image_url"),
        "compare_code": document.get("compare_code"),
        "entity_confidence": document.get("entity_confidence"),
        "entity_match_method": document.get("entity_match_method"),
        "entity_override": document.get("entity_override"),
        "price": document.get("price"),
        "rating": document.get("rating"),
        "stock": document.get("stock"),
        "availability": document.get("availability"),
        "condition": document.get("condition") or "unknown",
        "condition_confidence": document.get("condition_confidence"),
        "price_all_payment": document.get("price_all_payment") or document.get("price_internet"),
        "price_card": document.get("price_card") or document.get("price_cmr"),
        "payment_card_name": document.get("payment_card_name"),
        "installment_count": document.get("installment_count"),
        "installment_total": document.get("installment_total"),
        "financial_cae": document.get("financial_cae"),
        "payment_conditions": document.get("payment_conditions"),
        "shipping_cost": document.get("shipping_cost"),
        "shipping_free_threshold": document.get("shipping_free_threshold"),
        "shipping_region": document.get("shipping_region"),
        "pickup_available": document.get("pickup_available"),
        "low_stock": bool(document.get("low_stock")),
        "only_extreme_sizes": bool(document.get("only_extreme_sizes")),
        "variants": document.get("variants") or [],
        "reviews": document.get("reviews"),
        "price_normal": document.get("price_normal"),
        "price_internet": document.get("price_internet"),
        "price_cmr": document.get("price_cmr"),
        "updated_at": _iso(document.get("updated_at")),
        "has_thumb": bool(
            (document.get("thumbnail") or {}).get("data")
            or document.get("image_url")
            or document.get("image_urls")
        ),
        "history": points,
        "history_offer": points,
        "history_normal": normal_points,
        "price_observations": observations,
        "stats": price_stats(points, document.get("price")),
        "timing": buy_or_wait(points, document.get("price")),
    }


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


@router.get("/api/product")
def product(store: str = Query(...), id: str = Query(...)) -> dict:
    repo = _repo_or_404()
    try:
        document = repo.product_detail(store, id)
        if document is None:
            raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")
        try:
            from retail.funnel_stats import record_funnel_event

            record_funnel_event("product_view", source="web")
        except Exception:
            pass
        card = _card(document)
        # La curva usa un punto por día hasta hoy. El veredicto sigue mirando
        # las mediciones reales, no esta serie rellena.
        card["history"] = chart_history(card["history"])
        from retail.compare import same_product_identity

        others = [
            _card(item)
            for item in repo.by_compare_code(document.get("compare_code") or "")
            if (item.get("product_id") != document.get("product_id") or item.get("store") != store)
            and not is_catalog_mirror(document, item)
            and same_product_pack(document, item)
            and same_product_identity(document, item)
            and conditions_compatible(document.get("condition"), item.get("condition"))
        ]
        priced = [item for item in [card, *others] if item.get("price")]
        use_total = shipping_comparable(priced)
        cheapest = min(
            priced,
            key=lambda item: landed_price(item["price"], item.get("shipping_cost")) if use_total else item["price"],
        ) if priced else None
        cheapest_payload = {
            "store": cheapest["store"],
            "display_store": cheapest.get("display_store"),
            "store_title": cheapest.get("store_title"),
            "price": cheapest["price"],
            "total_price": landed_price(cheapest["price"], cheapest.get("shipping_cost")),
            "url": cheapest.get("url"),
            "product_id": cheapest.get("product_id"),
        } if cheapest else None
        # La ficha muestra «Más barato en X» si otra tienda gana. El veredicto
        # CONVIENE COMPRAR / mínimo histórico debe usar el mismo criterio global.
        if (
            cheapest_payload
            and cheapest_payload.get("store")
            and cheapest_payload["store"] != card.get("store")
        ):
            apply_cheaper_elsewhere_gate(
                stats=card.get("stats"),
                timing=card.get("timing"),
                cheaper=cheapest_payload,
            )
        return {
            "product": card,
            "others": others,
            "cheapest": cheapest_payload,
        }
    finally:
        repo.close()


@router.get("/api/catalog-insights")
def catalog_insights(group_by: str = Query("catalog_category"), limit: int = Query(50)) -> dict:
    repo = _repo_or_404()
    try:
        results = repo.catalog_analysis(group_by=group_by, limit=limit)
        return {"ok": True, "group_by": group_by, "results": results}
    finally:
        repo.close()


def _related_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "store": item.get("store"),
        "product_id": item.get("product_id"),
        "name": item.get("name"),
        "brand": item.get("brand"),
        "url": item.get("url"),
        "price": item.get("price"),
        "price_normal": item.get("price_normal"),
        "price_internet": item.get("price_internet"),
        "price_cmr": item.get("price_cmr"),
        "discount_percent": item.get("discount_percent"),
        "has_thumb": bool(item.get("has_thumb")),
        "comparison_fields": int(item.get("comparison_fields") or 0),
    }


@router.get("/api/product/ficha")
def product_ficha(
    store: str = Query(...),
    id: str = Query(...),
    comparable_only: bool = Query(default=False),
) -> dict:
    """Specs, descripción y relacionados. No pinta el precio: la ficha ya lo hizo."""
    repo = _repo_or_404()
    try:
        document = repo.product_detail(store, id)
        if document is None:
            raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")
        try:
            fields = enrich_from_store(document)
        except Exception:
            fields = {}
        if fields:
            document.update(fields)
            try:
                repo.save_ficha_fields(store, id, fields)
            except Exception:
                pass
        try:
            candidates = repo.related_candidates(
                text=search_text(document),
                catalog_id=document.get("catalog_id"),
                category_id=document.get("category_id"),
                category=document.get("category") or document.get("catalog_category"),
                brand=document.get("brand"),
                only_comparable=comparable_only,
            )
        except Exception:
            candidates = []
        return {
            "description": description_of(document),
            "specifications": specifications_of(document),
            "related": [_related_card(item) for item in pick_related(document, candidates)],
            "image_available": bool(document.get("image_url") or fields.get("image_url")),
        }
    finally:
        repo.close()


def _same_store_offers(repo, document: dict[str, Any], store: str) -> list[dict[str, Any]]:
    from retail.compare import same_product_identity

    return [
        item
        for item in repo.by_compare_code(document.get("compare_code") or "")
        if (item.get("product_id") != document.get("product_id") or item.get("store") != store)
        and not is_catalog_mirror(document, item)
        and same_product_pack(document, item)
        and same_product_identity(document, item)
    ]


@router.get("/api/product/sweep")
def product_sweep(request: Request, store: str = Query(...), id: str = Query(...)) -> StreamingResponse:
    """Busca el mismo producto en otras tiendas sin bloquear la ficha ya pintada."""
    repo = _repo_or_404()
    try:
        document = repo.product_detail(store, id)
        if document is None:
            raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")
        others = _same_store_offers(repo, document, store)
        try:
            user = current_user(request, repo)
        except HTTPException:
            user = None
    except Exception:
        repo.close()
        raise

    def events():
        try:
            for event in iter_ficha_sweep(document, others, repo=repo, user=user):
                if event.get("type") == "offer" and event.get("offer"):
                    event["offer"] = _card(event["offer"])
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        finally:
            repo.close()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/product/refresh")
def product_refresh(store: str = Query(...), id: str = Query(...)) -> dict:
    """Encola un scrape puntual de la ficha (no espera el resultado largo)."""
    repo = _repo_or_404()
    try:
        document = repo.product_detail(store, id)
        if document is None:
            raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")
    finally:
        repo.close()
    from retail.product_refresh import launch_product_refresh

    return launch_product_refresh(connect_repo, store, id)


@router.get("/api/thumb")
def thumb(store: str = Query(...), id: str = Query(...)) -> Response:
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=404, detail="Sin miniatura.")
    try:
        images = repo.product_images(store, id)
        decoded = thumbs.decode(images.get("thumbnail"))
    finally:
        repo.close()
    if decoded is None:
        source = next(
            (url for url in images.get("sources") or [] if str(url).startswith(("https://", "http://"))),
            None,
        )
        if source:
            return RedirectResponse(
                source,
                status_code=307,
                headers={"Cache-Control": "public, max-age=3600"},
            )
        raise HTTPException(status_code=404, detail="Sin miniatura.")
    payload, mime = decoded
    return Response(content=payload, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})


DEAL_SORTS = {"discount", "saving", "price", "price_desc", "name", "gap"}


@router.get("/api/deals")
def deals(
    request: Request,
    day: str | None = Query(default=None),
    category: str | None = Query(default=None),
    store: str | None = Query(default=None),
    q: str | None = Query(default=None),
    rule: str | None = Query(default=None),
    min_saving: int = Query(default=0, ge=0),
    min_discount: float = Query(default=0, ge=0),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    sort: str = Query(default="discount"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=80, ge=1, le=240),
) -> dict:
    repo = _repo_or_404()
    try:
        days = repo.deal_days()
        chosen = day or (days[0] if days else datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        order = sort if sort in DEAL_SORTS else "discount"
        found = repo.deals(
            day=chosen,
            category=category,
            store=store,
            text=q,
            rule=rule,
            min_saving=min_saving,
            min_discount=min_discount,
            min_price=min_price,
            max_price=max_price,
            sort=order,
            page=page,
            size=size,
        )
        user = current_user(request, repo)
        runs = repo.recent_runs(5) if user and user.get("role") == "admin" else []
        from retail.store_display import display_store

        titles = {spec.id: spec.title for spec in list_stores()}
        for item in found["items"]:
            item["display_store"], item["store_title"] = display_store(item, titles)
        store_labels = {
            store_id: display_store({"store": store_id}, titles)[1]
            for store_id in repo.deal_facets(chosen).get("stores") or []
        }
        return {
            "day": chosen,
            "days": days,
            "facets": repo.deal_facets(chosen),
            "store_labels": store_labels,
            "total": found["total"],
            "page": found["page"],
            "size": found["size"],
            "total_saving": found["total_saving"],
            "deals": found["items"],
            "runs": runs,
        }
    finally:
        repo.close()


@router.get("/api/explore-categories")
def explore_categories(
    request: Request,
    limit: int = Query(default=40, ge=1, le=80),
    include_counts: bool = Query(default=False),
) -> dict:
    """Categorías para «Explora rápido»: value/label/icon; counts solo admin."""
    from retail.search_cache import connect_redis
    from retail.web.deps import request_is_admin

    # Path público nunca calcula/expone counts (aunque manden el flag).
    want_counts = bool(include_counts and request_is_admin(request))
    cache_key = f"explore:categories:v2:{int(limit)}:{'c' if want_counts else 'n'}"
    client = connect_redis()
    if client is not None:
        try:
            raw = client.get(cache_key)
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict) and isinstance(payload.get("categories"), list):
                    payload["cache"] = True
                    payload["include_counts"] = want_counts
                    return payload
        except Exception:
            pass

    repo = _repo_or_404()
    try:
        categories = repo.explore_categories(limit=limit, include_counts=want_counts)
        payload = {
            "categories": categories,
            "cache": False,
            "include_counts": want_counts,
        }
        if client is not None:
            try:
                # Rankeo por muestra: 15 min; counts admin también cacheados.
                client.setex(cache_key, 900, json.dumps(payload, ensure_ascii=False))
            except Exception:
                pass
        return payload
    finally:
        repo.close()


@router.get("/api/catalog")
def catalog(
    request: Request,
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    store: str | None = Query(default=None),
    brand: str | None = Query(default=None),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    only_offers: bool = Query(default=False),
    only_comparable: bool = Query(default=False),
    sort: str = Query(default="updated"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=40, ge=1, le=120),
    include_counts: bool = Query(default=False),
) -> dict:
    repo = _repo_or_404()
    try:
        want_counts = False
        if include_counts:
            user = current_user(request, repo)
            want_counts = bool(user and user.get("role") == "admin")

        facets = repo.browse_facets(category=category, store=store, include_counts=want_counts)
        # Si cambió la categoría, un store/brand anterior puede ya no pertenecer
        # a sus facetas; se ignora ese filtro en vez de presentar una página vacía.
        available_stores = {str(item.get("value") or "") for item in facets.get("stores") or []}
        if store and store not in available_stores:
            store = None
            facets = repo.browse_facets(category=category, store=None, include_counts=want_counts)
        available_brands = {
            str(item.get("value") or "").casefold()
            for item in facets.get("brands") or []
        }
        if brand and brand.casefold() not in available_brands:
            brand = None
        if store and brand:
            # Brands dependen del store elegido; una sola reconsulta si hace falta.
            facets = repo.browse_facets(category=category, store=store, include_counts=want_counts)
        from retail.search_cache import rewrite_search_query

        found = repo.browse(
            text=rewrite_search_query(q) if q else q,
            category=category,
            store=store,
            brand=brand,
            min_price=min_price,
            max_price=max_price,
            only_offers=only_offers,
            only_comparable=only_comparable,
            sort=sort,
            page=page,
            size=size,
        )
        from retail.store_display import display_store

        titles = {spec.id: spec.title for spec in list_stores()}
        for item in found["items"]:
            item["display_store"], item["store_title"] = display_store(item, titles)
        for item in facets.get("stores") or []:
            item["label"] = display_store({"store": item.get("value")}, titles)[1]
        return {**found, "facets": facets, "include_counts": want_counts}
    finally:
        repo.close()


@router.get("/api/reales")
def reales(
    request: Request,
    comparacion: bool = Query(default=True),
    historial: bool = Query(default=True),
    iguales: bool = Query(default=False),
    q: str | None = Query(default=None),
    store: str | None = Query(default=None),
    category: str | None = Query(default=None),
    min_gap: float = Query(default=0, ge=0, le=100),
    super_ofertas: bool = Query(default=False, alias="super"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=40, ge=1, le=120),
) -> dict:
    repo = _repo_or_404()
    try:
        current_user(
            request,
            repo,
            required=True,
            detail="Inicia sesión para ver ofertas reales.",
        )
        from retail.reales import MIN_SUPER_PERCENT

        found = repo.real_offers(
            comparacion=comparacion,
            historial=historial,
            iguales=iguales,
            text=q,
            store=store,
            category=category,
            min_gap=min_gap,
            min_super=MIN_SUPER_PERCENT if super_ofertas else None,
            page=page,
            size=size,
        )
        titles = {spec.id: spec.title for spec in list_stores()}
        for item in found["items"]:
            _title_real_offer(item, titles)
        return {**found, "super": super_ofertas, "min_super": MIN_SUPER_PERCENT}
    finally:
        repo.close()


@router.get("/api/super")
def super_ofertas(
    request: Request,
    q: str | None = Query(default=None),
    store: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=40, ge=1, le=120),
) -> dict:
    """Ofertas reales cuyo descuento o brecha entre tiendas supera el 50%."""
    from retail.reales import MIN_SUPER_PERCENT

    repo = _repo_or_404()
    try:
        current_user(
            request,
            repo,
            required=True,
            detail="Inicia sesión para ver super ofertas.",
        )
        found = repo.real_offers(
            comparacion=True,
            historial=True,
            iguales=False,
            text=q,
            store=store,
            category=category,
            min_super=MIN_SUPER_PERCENT,
            page=page,
            size=size,
        )
        titles = {spec.id: spec.title for spec in list_stores()}
        for item in found["items"]:
            _title_real_offer(item, titles)
        return {**found, "min_super": MIN_SUPER_PERCENT}
    finally:
        repo.close()


def _title_real_offer(item: dict[str, Any], titles: dict[str, str]) -> None:
    from retail.store_display import display_store

    item["display_store"], item["store_title"] = display_store(item, titles)
    item["rival_store_title"] = titles.get(item.get("rival_store") or "", item.get("rival_store"))
    for row in item.get("stores") or []:
        row["display_store"], row["store_title"] = display_store(row, titles)


@router.get("/api/categories")
def categories(
    store: str = Query(default="falabella"),
    q: str | None = Query(default=None),
    parent: str | None = Query(default=None),
    depth: int | None = Query(default=None, ge=0),
    roots: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=3000),
) -> dict:
    repo = _repo_or_404()
    try:
        return {
            "store": store,
            "total": repo.count_categories(store),
            "items": repo.list_categories(
                store, text=q, parent_id=parent, depth=depth, roots=roots, limit=limit
            ),
        }
    finally:
        repo.close()


def _history_scan(repo, min_points: int, limit: int):
    """Productos con historial suficiente para entrar al ranking de tiendas."""
    return repo.collection.find(
        {f"price_history.{min_points - 1}": {"$exists": True}},
        {"store": 1, "product_id": 1, "name": 1, "url": 1, "price": 1, "price_history": 1},
    ).limit(limit)


def counted_drop_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Una fila por cada baja que suma la columna «Bajas de precio».

    No son los productos vigilados: si el historial no bajó, no hay fila.
    """
    events = classified_drop_events(series(document.get("price_history")))
    rows = []
    for event in events:
        moment = event["at"]
        rows.append(
            {
                "store": document.get("store"),
                "product_id": document.get("product_id"),
                "name": document.get("name") or "",
                "url": document.get("url") or "",
                "previous_price": event["previous_price"],
                "price": event["price"],
                "dropped_at": moment.isoformat() if moment else None,
                "percent": event["percent"],
                "inflated": event["inflated"],
            }
        )
    return rows


@router.get("/api/stores-report")
def stores_report(
    request: Request,
    min_points: int = Query(default=REPORT_MIN_POINTS, ge=2),
    limit: int = Query(default=REPORT_SCAN_LIMIT, ge=100),
) -> dict:
    """Cuánto se puede confiar en el 'antes' de cada cadena.

    Recorre el historial guardado y cuenta, tienda por tienda, cuántas de sus
    bajas solo deshacen un alza reciente. Es el mismo criterio que usa la
    alerta de descuento falso, pero mirado de a cadena completa.
    """
    repo = _repo_or_404()
    try:
        current_user(
            request,
            repo,
            required=True,
            detail="Inicia sesión para ver las tiendas.",
        )
        por_tienda: dict[str, dict[str, Any]] = {}
        for document in _history_scan(repo, min_points, limit):
            store = document.get("store") or "?"
            row = por_tienda.setdefault(
                store, {"store": store, "products": 0, "drops": 0, "fake_drops": 0, "days_tracked": 0}
            )
            points = _points(document)
            row["products"] += 1
            row["days_tracked"] = max(row["days_tracked"], buy_or_wait(points, document.get("price"))["days_tracked"])
            drops = counted_drop_rows(document)
            row["drops"] += len(drops)
            row["fake_drops"] += sum(1 for drop in drops if drop["inflated"])
        rows = []
        from retail.store_display import display_store

        for row in por_tienda.values():
            row["fake_percent"] = round(row["fake_drops"] * 100 / row["drops"], 1) if row["drops"] else None
            row["display_store"], row["store_title"] = display_store(row)
            rows.append(row)
        rows.sort(key=lambda item: (item["fake_percent"] is None, -(item["fake_percent"] or 0)))
        checks = list_store_bot_checks(repo)
        annotate_store_bot_checks(rows, checks)
        seguidos = max((row["days_tracked"] for row in rows), default=0)
        return {
            "stores": rows,
            "days_tracked": seguidos,
            # Con pocas semanas encima el ranking dice más del azar que de la tienda.
            "ready": seguidos >= REPORT_MIN_DAYS,
            "min_days": REPORT_MIN_DAYS,
            "bot_checks": bot_check_api_rows(checks),
        }
    finally:
        repo.close()


@router.get("/api/stores-drops")
def stores_drops(
    request: Request,
    store: str = Query(...),
    min_points: int = Query(default=REPORT_MIN_POINTS, ge=2),
    limit: int = Query(default=REPORT_SCAN_LIMIT, ge=100),
) -> dict:
    """Productos detrás del número «Bajas de precio» de una tienda.

    Misma sesión que /api/stores-report y la página /tiendas. Recorre el
    mismo historial y el mismo tope: la lista tiene una fila por baja contada,
    no el catálogo vigilado.
    """
    store = store.strip()
    if not store or len(store) > 40:
        raise HTTPException(status_code=400, detail="Tienda inválida.")
    repo = _repo_or_404()
    try:
        current_user(
            request,
            repo,
            required=True,
            detail="Inicia sesión para ver las tiendas.",
        )
        items: list[dict[str, Any]] = []
        for document in _history_scan(repo, min_points, limit):
            if (document.get("store") or "?") != store:
                continue
            items.extend(counted_drop_rows(document))
        items.sort(key=lambda item: item.get("dropped_at") or "", reverse=True)
        return {"store": store, "total": len(items), "items": items}
    finally:
        repo.close()


@router.get("/api/watches")
def list_watches(request: Request) -> list[dict]:
    repo = _repo_or_404()
    try:
        user = current_user(request, repo, required=True)
        return repo.list_watches(user_id=user["id"])
    finally:
        repo.close()


@router.post("/api/watches")
async def create_watch(request: Request) -> dict:
    body = await request.json()
    if not str(body.get("query") or "").strip():
        raise HTTPException(status_code=400, detail="Falta la búsqueda del producto.")
    target = body.get("target_price")
    drop = body.get("drop_percent")
    current_price = body.get("current_price")
    try:
        current_price = int(current_price) if current_price not in (None, "") else None
    except (TypeError, ValueError):
        current_price = None
    repo = _repo_or_404()
    try:
        user = current_user(request, repo, required=True)
        # Seguimiento: por defecto cualquier cambio (sube o baja), sin umbral.
        watch_changes = bool(body.get("watch_changes", True))
        if not target and not drop:
            watch_changes = True
        saved = repo.save_watch(
            {
                "query": body.get("query"),
                "compare_code": body.get("compare_code"),
                "name": body.get("name"),
                "store": body.get("store"),
                "product_id": body.get("product_id"),
                "url": body.get("url"),
                "target_price": int(target) if target else None,
                "drop_percent": float(drop) if drop else None,
                "watch_changes": watch_changes,
                "any_change": watch_changes and not target and not drop,
                "last_seen_price": current_price,
                "user_id": user["id"],
                "email": user.get("email"),
            }
        )
        try:
            from retail.funnel_stats import record_funnel_event

            record_funnel_event("follow", source="watch")
        except Exception:
            pass
        return saved
    finally:
        repo.close()


@router.delete("/api/watches/{watch_id}")
def delete_watch(watch_id: str, request: Request) -> dict:
    repo = _repo_or_404()
    try:
        user = current_user(request, repo, required=True)
        return {"deleted": repo.delete_watch(watch_id, user_id=user["id"])}
    finally:
        repo.close()


def _price_alert_key(store: str, product_id: str) -> tuple[str, str]:
    store_id = str(store or "").strip().lower()
    ident = str(product_id or "").strip()
    if not store_id or not ident or len(store_id) > 40 or len(ident) > 200:
        raise HTTPException(status_code=400, detail="Producto inválido.")
    return store_id, ident


@router.get("/api/price-alert")
def price_alert_status(request: Request, store: str = Query(...), id: str = Query(...)) -> dict:
    repo = _repo_or_404()
    try:
        store_id, product_id = _price_alert_key(store, id)
        user = current_user(request, repo)
        if not user:
            return {"logged_in": False, "active": False}
        found = repo.get_price_alert(user["id"], store_id, product_id)
        return {
            "logged_in": True,
            "active": bool(found),
            "email": user.get("email") or "",
        }
    finally:
        repo.close()


@router.post("/api/price-alert")
async def activate_price_alert(request: Request) -> dict:
    body = await request.json()
    store_id, product_id = _price_alert_key(body.get("store"), body.get("product_id") or body.get("id"))
    repo = _repo_or_404()
    try:
        user = current_user(request, repo)
        if not user:
            raise HTTPException(status_code=401, detail="Entra para activar una alerta de precio.")
        if not str(user.get("email") or "").strip():
            raise HTTPException(status_code=400, detail="Tu cuenta no tiene correo para avisar.")
        document = repo.product_detail(store_id, product_id) or {}
        repo.save_price_alert(
            {
                "user_id": user["id"],
                "email": user.get("email") or "",
                "store": store_id,
                "product_id": product_id,
                "name": document.get("name") or body.get("name") or "",
                "url": document.get("url") or "",
                "any_change": True,
                "watch_changes": True,
            }
        )
        try:
            from retail.funnel_stats import record_funnel_event

            record_funnel_event("follow", source="price_alert")
        except Exception:
            pass
        return {"active": True, "email": user.get("email") or ""}
    finally:
        repo.close()


@router.delete("/api/price-alert")
def deactivate_price_alert(request: Request, store: str = Query(...), id: str = Query(...)) -> dict:
    repo = _repo_or_404()
    try:
        store_id, product_id = _price_alert_key(store, id)
        user = current_user(request, repo)
        if not user:
            raise HTTPException(status_code=401, detail="Entra para activar una alerta de precio.")
        repo.delete_price_alert(user["id"], store_id, product_id)
        return {"active": False, "email": user.get("email") or ""}
    finally:
        repo.close()
