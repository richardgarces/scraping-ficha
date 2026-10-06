from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from retail.auth import safe_next
from retail.registry import group_of, list_stores
from retail.qdrant_index import connect_qdrant
from retail.search import (
    SEARCH_TIMEOUT,
    SOURCES,
    connect_repo,
    drop_search_cancel,
    iter_search_events,
    new_search_cancel,
    request_search_cancel,
    search_products,
)
from retail.click_stats import click_origin, parse_click_kind, record_click
from retail.request_stats import client_country, client_ip, record_request
from retail.search_stats import record_app_search
from retail.web.auth_api import router as auth_router
from retail.web.deps import current_user, request_is_admin, require_admin_html, require_login_html
from retail.web.insights_api import router as insights_router
from retail.web.settings_api import router as settings_router
from retail.web.forecasts_api import router as forecasts_router
from retail.web.admin_analysis_api import router as admin_analysis_router
from retail.web.push_api import router as push_router
from retail.web.reviews_api import router as reviews_router
from retail.web.quotes_api import router as quotes_router
from retail.offer_screenshot import offer_shot_media_type, offer_shot_path
from retail.web.anti_scraping import (
    VISITOR_COOKIE,
    VISITOR_MAX_AGE,
    inspect_request,
    should_issue_visitor_cookie,
    sign_visitor,
)

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Comparador retail Chile", version="2.0.0")
app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(insights_router)
app.include_router(forecasts_router)
app.include_router(admin_analysis_router)
app.include_router(push_router)
app.include_router(reviews_router)
app.include_router(quotes_router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(STATIC / "brand" / "favicon.ico", media_type="image/x-icon")


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon() -> FileResponse:
    return FileResponse(STATIC / "brand" / "apple-touch-icon.png", media_type="image/png")


@app.get("/sw.js", include_in_schema=False)
def push_service_worker() -> FileResponse:
    return FileResponse(
        STATIC / "push-sw.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/push-sw-v1.js", include_in_schema=False)
@app.get("/push-sw-v2.js", include_in_schema=False)
def versioned_push_service_worker() -> FileResponse:
    """v2 evita el JS cacheado. v1 sigue sirviendo el mismo script para no dejar suscripciones viejas sin la foto."""
    return push_service_worker()


@app.get("/offer-shots/{name}", include_in_schema=False)
def offer_shot(name: str) -> FileResponse:
    """Sirve una captura ya guardada. No lista el directorio ni acepta otras rutas."""
    path = offer_shot_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Captura no disponible.")
    return FileResponse(
        path,
        media_type=offer_shot_media_type(path),
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/robots.txt", include_in_schema=False)
def robots() -> PlainTextResponse:
    return PlainTextResponse("User-agent: *\nDisallow: /\n", headers={"Cache-Control": "public, max-age=3600"})


def _quotes_api_path(path: str) -> str:
    if path == "/api/cotizaciones" or path.startswith("/api/cotizaciones/"):
        return "/api/quotes" + path[len("/api/cotizaciones") :]
    return path


@app.middleware("http")
async def count_app_requests(request: Request, call_next):
    quoted_path = _quotes_api_path(request.url.path)
    if quoted_path != request.url.path:
        request.scope["path"] = quoted_path
    if quoted_path.startswith("/api/quotes") and request.method in {"POST", "PUT"}:
        if len(await request.body()) > 600_000:
            return JSONResponse({"detail": "La cotización supera el tamaño permitido."}, status_code=413)
    decision = None
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        decision = inspect_request(
            request.url.path,
            request.method,
            request.headers,
            request.cookies,
            request.client.host if request.client else None,
        )
    if decision is not None:
        headers = {
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow, noarchive, nosnippet",
        }
        if decision.retry_after is not None:
            headers["Retry-After"] = str(decision.retry_after)
        return JSONResponse({"detail": decision.detail}, status_code=decision.status_code, headers=headers)
    try:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if should_issue_visitor_cookie(request.url.path, content_type):
            response.set_cookie(
                VISITOR_COOKIE,
                sign_visitor(),
                max_age=VISITOR_MAX_AGE,
                httponly=True,
                samesite="strict",
                secure=os.environ.get("RETAIL_COOKIE_SECURE", "0").strip().lower() in {"1", "true", "yes"},
                path="/",
            )
        if "text/html" in content_type.lower() or request.url.path.startswith("/api/"):
            response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive, nosnippet"
        return response
    finally:
        try:
            host = request.client.host if request.client else None
            record_request(
                request.url.path,
                client_ip(request.headers, host),
                client_country(request.headers),
                method=request.method,
            )
        except Exception:
            pass


@app.on_event("startup")
def _bootstrap_admin() -> None:
    repo = connect_repo()
    if repo is None:
        return
    try:
        repo.ensure_bootstrap_admin()
    finally:
        repo.close()


@app.on_event("startup")
def _bootstrap_product_index() -> None:
    try:
        from retail.index.products import ensure_loaded

        ensure_loaded(sync_json=True)
    except Exception:
        return


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/ofertas")
def ofertas(request: Request):
    gate = require_admin_html(request, next_path="/ofertas")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "ofertas.html")


@app.get("/cron")
def cron_lotes(request: Request):
    gate = require_admin_html(request, next_path="/cron")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "cron.html")


@app.get("/estadisticas")
def estadisticas(request: Request):
    gate = require_admin_html(request, next_path="/estadisticas")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "estadisticas.html")


@app.get("/analisis-producto")
def analisis_producto(request: Request):
    gate = require_login_html(request, next_path="/analisis-producto")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "analisis-producto.html")


@app.get("/hoy")
def hoy() -> FileResponse:
    return FileResponse(STATIC / "hoy.html")


@app.get("/reales")
def reales(request: Request):
    gate = require_login_html(request, next_path="/reales")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "reales.html")


@app.get("/super")
def super_ofertas_page() -> RedirectResponse:
    return RedirectResponse("/reales?super=1", status_code=302)


@app.get("/catalogo")
def catalogo() -> FileResponse:
    return FileResponse(STATIC / "catalogo.html")


@app.get("/tiendas")
def tiendas(request: Request):
    gate = require_admin_html(request, next_path="/tiendas")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "tiendas.html")


@app.get("/producto")
def producto() -> FileResponse:
    return FileResponse(STATIC / "producto.html")


@app.get("/o/{code}", include_in_schema=False)
def short_product_redirect(code: str):
    """Resuelve un enlace de notificación sin aceptar destinos externos."""
    if not code.isdigit() or not (6 <= len(code) <= 18):
        raise HTTPException(status_code=404, detail="Enlace no encontrado.")
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Servicio temporalmente no disponible.")
    try:
        found = repo.resolve_product_short_link(code)
    finally:
        repo.close()
    if not found or not found.get("store") or not found.get("product_id"):
        raise HTTPException(status_code=404, detail="Enlace no encontrado.")
    try:
        from retail.funnel_stats import record_funnel_event

        record_funnel_event("link_click", source="lnk")
    except Exception:
        pass
    from retail.short_links import public_product_url

    return RedirectResponse(
        public_product_url(found["store"], found["product_id"]),
        status_code=302,
    )


@app.get("/comparar")
def comparar(request: Request):
    next_path = request.url.path
    if request.url.query:
        next_path += f"?{request.url.query}"
    gate = require_login_html(request, next_path=next_path)
    if gate is not None:
        return gate
    return FileResponse(STATIC / "comparar.html")


@app.get("/siguiendo")
def siguiendo() -> FileResponse:
    return FileResponse(STATIC / "siguiendo.html")


def _member_page(path: str) -> bool:
    """Páginas que cualquier cuenta aprobada puede abrir, no solo el admin."""
    base = path.split("?", 1)[0].rstrip("/") or "/"
    return base in {"/reales", "/super", "/comparar", "/analisis-producto"}


@app.get("/entrar")
def entrar(request: Request):
    if request.query_params.get("modo") in {"recuperar", "restablecer"}:
        return FileResponse(STATIC / "entrar.html")
    nxt = safe_next(request.query_params.get("next"), "/ofertas")
    repo = connect_repo()
    if repo is not None:
        try:
            user = current_user(request, repo)
            admin_next = user and user.get("role") == "admin" and (
                nxt.startswith("/ofertas")
                or nxt.startswith("/cron")
                or nxt.startswith("/estadisticas")
                or nxt.startswith("/usuarios")
                or nxt.startswith("/analisis-producto")
                or nxt.startswith("/cotizaciones")
            )
            member_next = user and _member_page(nxt)
            if admin_next or member_next:
                return RedirectResponse(nxt, status_code=303)
        finally:
            repo.close()
    return FileResponse(STATIC / "entrar.html")


@app.get("/usuarios")
def usuarios(request: Request):
    gate = require_admin_html(request, next_path="/usuarios")
    if gate is not None:
        return gate
    return FileResponse(STATIC / "usuarios.html")


@app.post("/api/clicks")
async def track_click(request: Request) -> dict:
    """Clics del menú, de la fecha y de enlaces externos. No es una visita."""
    raw = await request.body()
    if len(raw) > 512:
        raise HTTPException(status_code=400, detail="Clic no reconocido.")
    host = request.client.host if request.client else None
    saved = record_click(
        parse_click_kind(raw),
        client_ip(request.headers, host),
        client_country(request.headers),
        origin=click_origin(request.headers),
    )
    if saved is None:
        raise HTTPException(status_code=400, detail="Clic no reconocido.")
    return {"ok": True}


@app.get("/api/health")
def health() -> dict:
    repo = connect_repo()
    mongo = False
    products = 0
    real_offer_worker = {"healthy": False}
    if repo is not None:
        mongo = True
        try:
            products = repo.count()
            real_offer_worker = repo.real_offer_worker_status()
        except Exception:
            products = 0
        repo.close()
    qdrant = connect_qdrant()
    redis_ok = False
    try:
        from retail.search_cache import connect_redis

        redis_ok = connect_redis() is not None
    except Exception:
        redis_ok = False
    return {
        "ok": True,
        "mongo": mongo,
        "qdrant": qdrant is not None,
        "redis": redis_ok,
        "real_offer_worker": real_offer_worker,
        "stores": len(list_stores()),
        "products": products,
    }


_LOGO_FILES = {
    "falabella": "falabella.png",
    "sodimac": "sodimac.png",
    "tottus": "tottus.png",
    "paris": "paris.svg",
    "easy": "easy.svg",
    "construplaza": "construplaza.svg",
    "prat": "prat.svg",
    "weitzler": "weitzler.svg",
    "audiomusica": "audiomusica.svg",
    "casaroyal": "casaroyal.svg",
    "promusic": "promusic.svg",
    "dbs": "dbs.svg",
    "sallybeauty": "sallybeauty.svg",
    "bodyshop": "bodyshop.svg",
    "preunic": "preunic.svg",
    "ripley": "ripley.svg",
    "lider": "lider.svg",
    "unimarc": "unimarc.svg",
    "alvi": "alvi.svg",
    "cugat": "cugat.svg",
    "pcfactory": "pcfactory.png",
    "ikea": "ikea.svg",
    "mercadolibre": "mercadolibre.svg",
    "drsimi": "drsimi.webp",
    "doite": "doite.png",
    "antartica": "antartica.png",
    "intime": "intime.png",
    "sparta": "sparta.png",
    "nike": "nike.png",
    "weplay": "weplay.png",
    "rosen": "rosen.jpg",
    "amphora": "amphora.jpg",
    "fashionspark": "fashionspark.png",
    "lippi": "lippi.png",
    "colloky": "colloky.png",
    "tiendaflores": "tiendaflores.png",
    "cannon": "cannon.png",
    "ahumada": "ahumada.svg",
    "cruzverde": "cruzverde.png",
    "eliteperfumes": "eliteperfumes.svg",
    "loccitane": "loccitane.svg",
    "lush": "lush.svg",
    "pichara": "pichara.svg",
    "silkperfumes": "silkperfumes.svg",
    "azaleia": "azaleia.svg",
    "cardinale": "cardinale.svg",
    "converse": "converse.svg",
    "crocs": "crocs.svg",
    "hushpuppies": "hushpuppies.svg",
    "vans": "vans.svg",
    "allnutrition": "allnutrition.svg",
    "andesgear": "andesgear.svg",
    "asics": "asics.svg",
    "bikehouse": "bikehouse.svg",
    "hakahonu": "hakahonu.svg",
    "head": "head.svg",
    "mammut": "mammut.svg",
    "merrell": "merrell.svg",
    "newbalance": "newbalance.svg",
    "nutrapharm": "nutrapharm.svg",
    "oxford": "oxford.svg",
    "patagonia": "patagonia.svg",
    "puma": "puma.svg",
    "reebok": "reebok.svg",
    "salomon": "salomon.svg",
    "sportika": "sportika.svg",
    "supletech": "supletech.svg",
    "thenorthface": "thenorthface.svg",
    "underarmour": "underarmour.svg",
    "dellanatura": "dellanatura.svg",
    "atika": "atika.svg",
    "budnik": "budnik.svg",
    "mk": "mk.svg",
    "stretto": "stretto.svg",
    "adagio": "adagio.svg",
    "cafehaiti": "cafehaiti.svg",
    "lavinoteca": "lavinoteca.svg",
    "marleycoffee": "marleycoffee.svg",
    "mundovino": "mundovino.svg",
    "wineclub": "wineclub.svg",
    "varsovienne": "varsovienne.svg",
    "byp": "byp.svg",
    "flex": "flex.svg",
    "interdesign": "interdesign.svg",
    "kitchencenter": "kitchencenter.svg",
    "mashini": "mashini.svg",
    "medular": "medular.svg",
    "oster": "oster.svg",
    "simplepuro": "simplepuro.svg",
    "thomas": "thomas.svg",
    "tramontina": "tramontina.svg",
    "bebesit": "bebesit.svg",
    "ficcus": "ficcus.svg",
    "limonada": "limonada.svg",
    "opaline": "opaline.svg",
    "artenostro": "artenostro.svg",
    "contrapunto": "contrapunto.svg",
    "ferialibro": "ferialibro.svg",
    "torre": "torre.svg",
    "bananarepublic": "bananarepublic.svg",
    "calvinklein": "calvinklein.svg",
    "dockers": "dockers.svg",
    "ellus": "ellus.svg",
    "kipling": "kipling.svg",
    "levis": "levis.svg",
    "lounge": "lounge.svg",
    "trial": "trial.svg",
    "econopticas": "econopticas.svg",
    "gmo": "gmo.svg",
    "opv": "opv.svg",
    "schilling": "schilling.svg",
    "mosso": "mosso.svg",
    "swarovski": "swarovski.svg",
    "belkin": "belkin.svg",
    "centrale": "centrale.svg",
    "migo": "migo.svg",
    "motorola": "motorola.svg",
    "movistar": "movistar.svg",
    "entel": "entel.svg",
    "dcshoes": "dcshoes.svg",
    "totaltools": "totaltools.svg",
    "descorcha": "descorcha.svg",
    "piwen": "piwen.svg",
    "tika": "tika.svg",
    "betterlife": "betterlife.svg",
    "janome": "janome.svg",
    "mundotransfer": "mundotransfer.svg",
    "maui": "maui.svg",
    "ripcurl": "ripcurl.svg",
    "volcom": "volcom.svg",
    "speedo": "speedo.svg",
    "liquimoly": "liquimoly.svg",
    "needle": "needle.svg",
    "ansaldo": "ansaldo.svg",
    "toyng": "toyng.svg",
    "piedrabruja": "piedrabruja.svg",
    "catalonia": "catalonia.svg",
    "nacional": "nacional.svg",
    "etienne": "etienne.svg",
    "petrizzio": "petrizzio.svg",
    "gap": "gap.svg",
    "ferouch": "ferouch.svg",
    "perryellis": "perryellis.svg",
    "tommy": "tommy.svg",
    "hugoboss": "hugoboss.svg",
    "guess": "guess.svg",
    "fdv": "fdv.svg",
    "amesti": "amesti.svg",
    "dartel": "dartel.svg",
    "salcobrand": "salcobrand.svg",
}


@app.get("/api/stores")
def stores() -> list[dict[str, str | int]]:
    rows = []
    for spec in list_stores():
        group, group_title, group_order = group_of(spec.id, spec.group)
        rows.append(
            {
                "id": spec.id,
                "title": spec.title,
                "site": spec.site,
                "logo": f"/static/logos/{_LOGO_FILES.get(spec.id, '_store.svg')}",
                "group": group,
                "group_title": group_title,
                "group_order": group_order,
            }
        )
    rows.sort(key=lambda row: (int(row["group_order"]), str(row["title"]).casefold(), str(row["id"])))
    return rows


@app.get("/api/history")
def history(request: Request, limit: int = Query(default=12, ge=1, le=50)) -> list[dict]:
    repo = connect_repo()
    if repo is None:
        return []
    try:
        user = current_user(request, repo)
        if not user or user.get("role") != "admin":
            return []
        return repo.recent_searches(limit)
    finally:
        repo.close()


@app.get("/api/search")
def search(
    request: Request,
    q: str = Query(..., min_length=1),
    source: str = Query(default="both"),
    stores: str | None = Query(default=None),
    max_items: int = Query(default=5, ge=1, le=30, alias="max"),
    delay: float = Query(default=1.0, ge=0.0, le=10.0),
    price_band: bool = Query(default=True),
    fresh: bool = Query(default=False),
    quick: bool = Query(default=False),
) -> dict:
    _log_web_search(request, q)
    favorites, excluded = _request_store_preferences(request)
    try:
        result = search_products(
            **_with_store_preferences(_search_args_for_role(
                request_is_admin(request), q, source, stores, max_items, delay, price_band, fresh, quick
            ), favorites, excluded)
        )
        return _personalize_search_result(result, favorites, excluded)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _log_web_search(request: Request, query: str) -> None:
    try:
        host = request.client.host if request.client else None
        record_app_search(query, client_ip(request.headers, host), client_country(request.headers))
    except Exception:
        return
    try:
        from retail.funnel_stats import record_funnel_event

        record_funnel_event("search", source="web")
    except Exception:
        return


def _request_store_preferences(request: Request) -> tuple[list[str], list[str]]:
    repo = connect_repo()
    if repo is None:
        return [], []
    try:
        user = current_user(request, repo)
        if not user:
            return [], []
        document = repo.find_user_by_id(str(user.get("id") or "")) or {}
        valid = {spec.id for spec in list_stores()}
        favorites = list(dict.fromkeys(
            str(item).strip().lower() for item in document.get("favorite_stores") or []
            if str(item).strip().lower() in valid
        ))
        excluded = list(dict.fromkeys(
            str(item).strip().lower() for item in document.get("excluded_stores") or []
            if str(item).strip().lower() in valid
        ))
        return [item for item in favorites if item not in set(excluded)], excluded
    finally:
        repo.close()


def _with_store_preferences(args: dict, favorites: list[str], excluded: list[str]) -> dict:
    if not favorites and not excluded:
        return args
    args = dict(args)
    args["preferred_stores"] = list(favorites)
    args["excluded_stores"] = list(excluded)
    return args


def _personalize_search_result(result: dict, favorites: list[str], excluded: list[str]) -> dict:
    """Oculta tiendas excluidas y sitúa las preferidas antes que las demás."""
    if not favorites and not excluded:
        return result
    payload = dict(result)
    ranks = {store_id: index for index, store_id in enumerate(favorites)}
    excluded_set = set(excluded)

    def key(item: dict, fallback: int = 0):
        store_id = str(item.get("store") or item.get("id") or "")
        return (0, ranks[store_id]) if store_id in ranks else (1, fallback)

    groups = []
    for group_index, original in enumerate(payload.get("groups") or []):
        group = dict(original)
        offers = [dict(item) for item in original.get("offers") or [] if item.get("store") not in excluded_set]
        if not offers:
            continue
        offers = [item for _, item in sorted(enumerate(offers), key=lambda pair: key(pair[1], pair[0]))]
        for item in offers:
            item["favorite_store"] = item.get("store") in ranks
        prices = [item.get("price") for item in offers if isinstance(item.get("price"), (int, float))]
        if prices:
            lowest = min(prices)
            lowest_offers = [item for item in offers if item.get("price") == lowest]
            group["lowest_price"] = lowest
            group["lowest_stores"] = [item.get("store") for item in lowest_offers]
            group["lowest_store_titles"] = [item.get("store_title") or item.get("store") for item in lowest_offers]
        group["offers"] = offers
        group["favorite_store"] = any(item.get("favorite_store") for item in offers)
        if len({item.get("store") for item in offers}) < 2:
            group["comparable"] = False
        groups.append((group_index, group))
    groups.sort(key=lambda pair: (0 if pair[1].get("favorite_store") else 1, pair[0]))
    payload["groups"] = [item for _, item in groups]

    rows = [dict(item) for item in payload.get("rows") or [] if item.get("store") not in excluded_set]
    rows = [item for _, item in sorted(enumerate(rows), key=lambda pair: key(pair[1], pair[0]))]
    for item in rows:
        item["favorite_store"] = item.get("store") in ranks
    payload["rows"] = rows
    payload["offer_count"] = len(rows)
    payload["group_count"] = len(payload["groups"])
    payload["comparable_count"] = sum(1 for group in payload["groups"] if group.get("comparable"))
    for field in ("stores",):
        values = [item for item in payload.get(field) or [] if item not in excluded_set]
        payload[field] = sorted(values, key=lambda item: key({"store": item}, values.index(item)))
    progress = [dict(item) for item in payload.get("progress") or [] if item.get("id") not in excluded_set]
    payload["progress"] = [item for _, item in sorted(enumerate(progress), key=lambda pair: key(pair[1], pair[0]))]
    payload["store_preferences"] = {"favorites": favorites, "excluded": excluded}
    return payload


def _personalize_search_event(event: dict, favorites: list[str], excluded: list[str]) -> dict:
    if not favorites and not excluded:
        return event
    output = dict(event)
    if isinstance(output.get("result"), dict):
        output["result"] = _personalize_search_result(output["result"], favorites, excluded)
    if isinstance(output.get("progress"), list):
        progress = {"progress": output["progress"]}
        output["progress"] = _personalize_search_result(progress, favorites, excluded)["progress"]
    return output


def _search_args(
    q: str,
    source: str,
    stores: str | None,
    max_items: int,
    delay: float,
    price_band: bool = True,
    fresh: bool = False,
) -> dict:
    if source not in SOURCES:
        raise HTTPException(status_code=400, detail="source debe ser scrape, db o both")
    chosen = [item.strip() for item in stores.split(",") if item.strip()] if stores else None
    return {
        "query": q,
        "source": source,
        "stores": chosen,
        "max_items": max_items,
        "delay": delay,
        "price_band": price_band,
        "fresh": fresh,
        "timeout": SEARCH_TIMEOUT,
    }


def _search_args_for_role(
    admin: bool,
    q: str,
    source: str,
    stores: str | None,
    max_items: int,
    delay: float,
    price_band: bool,
    fresh: bool,
    quick: bool = False,
) -> dict:
    """Los parámetros avanzados son exclusivos del administrador."""
    if quick:
        args = _search_args(
            q,
            "db",
            stores if admin else None,
            max_items if admin else 20,
            delay,
            price_band if admin else False,
            False,
        )
        # La búsqueda rápida es estrictamente MongoDB/Qdrant. Si no hay
        # resultados, la interfaz pide confirmación antes de consultar tiendas.
        args["recover_underfilled_db"] = False
        return args
    if not admin:
        # Consulta base y tiendas, reutilizando las búsquedas del día en Chile.
        return _search_args(q, "both", None, 20, delay, False, False)
    return _search_args(q, source, stores, max_items, delay, price_band, fresh)


@app.post("/api/search/cancel")
def search_cancel(search_id: str = Query(..., alias="id", min_length=8, max_length=80)) -> dict:
    return {"ok": request_search_cancel(search_id), "id": search_id}


@app.get("/api/search/stream")
def search_stream(
    request: Request,
    q: str = Query(..., min_length=1),
    source: str = Query(default="both"),
    stores: str | None = Query(default=None),
    max_items: int = Query(default=5, ge=1, le=30, alias="max"),
    delay: float = Query(default=1.0, ge=0.0, le=10.0),
    price_band: bool = Query(default=True),
    fresh: bool = Query(default=False),
    quick: bool = Query(default=False),
    search_id: str | None = Query(default=None, max_length=80),
) -> StreamingResponse:
    _log_web_search(request, q)
    favorites, excluded = _request_store_preferences(request)
    kwargs = _with_store_preferences(_search_args_for_role(
        request_is_admin(request), q, source, stores, max_items, delay, price_band, fresh, quick
    ), favorites, excluded)
    ident, cancel = new_search_cancel(search_id)

    def events():
        try:
            for raw_event in iter_search_events(**kwargs, cancel=cancel, search_id=ident):
                event = _personalize_search_event(raw_event, favorites, excluded)
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except ValueError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except GeneratorExit:
            cancel.set()
            raise
        except Exception as exc:
            # Evita cortar el SSE sin evento: el navegador interpreta el cierre
            # como «Se cortó la consulta» cuando aún no hay filas.
            yield f"data: {json.dumps({'type': 'error', 'detail': f'No se pudo completar la búsqueda: {exc}'})}\n\n"
        finally:
            drop_search_cancel(ident)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
