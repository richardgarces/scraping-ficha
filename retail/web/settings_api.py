from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from retail.web.deps import current_user
from retail.batch.catalog import load_catalog
from retail.batch.config import (
    load_channels,
    load_schedule,
    mask_channels,
    merge_secrets,
    save_catalog,
    save_rules,
    write_json,
)
from retail.batch.config import CHANNELS_PATH
from retail.batch.rules import load_rules
from retail.batch.schedule import apply_schedule, schedule_status
from retail.qdrant_index import connect_qdrant
from retail.registry import list_stores
from retail.search import connect_repo
from retail.batch.basic_scrape import BasicScrapeBusy
from retail.batch.store_scope import normalize_store
from retail.offer_screenshot import offer_screenshot_status, save_offer_screenshots_enabled
from retail.web.jobs import (
    batch_status,
    start_basic_scrape,
    start_batch,
    start_group_batch,
    start_store_batch,
    stop_basic_scrape,
    stop_group_batch,
    stop_store_batch,
)

router = APIRouter()


@router.get("/api/settings")
def get_settings(request: Request) -> dict:
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        current_user(request, repo, admin=True)
        return {
            "rules": load_rules(),
            "channels": mask_channels(load_channels()),
            "schedule": schedule_status(repo),
            "catalog": load_catalog(),
            "offer_screenshots": offer_screenshot_status(repo),
        }
    finally:
        repo.close()


@router.put("/api/settings/rules")
async def put_rules(request: Request) -> dict:
    current_user(request, admin=True)
    return save_rules(await request.json())


@router.put("/api/settings/channels")
async def put_channels(request: Request) -> dict:
    current_user(request, admin=True)
    merged = merge_secrets(await request.json())
    write_json(CHANNELS_PATH, merged)
    return mask_channels(merged)


@router.put("/api/settings/schedule")
async def put_schedule(request: Request) -> dict:
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        current_user(request, repo, admin=True)
        return apply_schedule(await request.json(), repo)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Revisa los valores de la programación.") from exc
    finally:
        repo.close()


@router.get("/api/settings/schedule")
def get_schedule(request: Request) -> dict:
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        current_user(request, repo, admin=True)
        return schedule_status(repo)
    finally:
        repo.close()


@router.put("/api/settings/offer-screenshots")
async def put_offer_screenshots(request: Request) -> dict:
    """Activa o apaga las capturas de oferta. El valor queda en Mongo `app_settings`."""
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        current_user(request, repo, admin=True)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
            raise HTTPException(status_code=400, detail="Indica si las capturas quedan activadas.")
        return save_offer_screenshots_enabled(body["enabled"], repo)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="No se pudo guardar el ajuste de capturas.") from exc
    finally:
        repo.close()


@router.put("/api/settings/catalog")
async def put_catalog(request: Request) -> dict:
    current_user(request, admin=True)
    try:
        return save_catalog(await request.json())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/alerts")
def get_alerts(request: Request) -> list[dict]:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        return []
    try:
        from retail.store_display import display_store

        rows = repo.recent_alerts(40)
        for item in rows:
            item["display_store"], item["store_title"] = display_store(item)
        return rows
    finally:
        repo.close()


@router.post("/api/batch/run")
async def post_batch(request: Request) -> dict:
    current_user(request, admin=True)
    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    schedule = load_schedule()
    return start_batch(
        source=body.get("source") or schedule.get("source") or "both",
        pause=float(body.get("pause") or schedule.get("pause") or 2),
        limit=body.get("limit"),
        dry_run=bool(body.get("dry_run")),
        persist=not bool(body.get("dry_run")),
    )


@router.get("/api/batch/status")
def get_batch_status(request: Request) -> dict:
    current_user(request, admin=True)
    return batch_status()


@router.post("/api/admin/store-scrape")
async def post_store_scrape(request: Request) -> dict:
    """Arranca el scrape de todas las categorías/consultas de una sola tienda."""
    current_user(request, admin=True)
    from retail.batch.store_scope import StoreBatchBusy, StoreBatchNothingToResume

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(body, dict):
        body = {}
    raw = str(body.get("tienda") or body.get("store") or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Elige una tienda.")
    try:
        store_id = normalize_store(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule = load_schedule()
    pause = body.get("pause")
    mode = body.get("mode")
    try:
        return start_store_batch(
            store_id,
            mode=mode,
            source=body.get("source") or schedule.get("source") or "both",
            pause=float(pause if pause is not None else schedule.get("pause") or 2),
            delay=float(body.get("delay") or 1),
            max_items=int(body.get("max") or body.get("max_items") or 6),
            limit=body.get("limit"),
            persist=not bool(body.get("dry_run")),
            dry_run=bool(body.get("dry_run")),
        )
    except StoreBatchBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StoreBatchNothingToResume as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/admin/store-scrape/{store_id}/stop", status_code=202)
def stop_store_scrape(store_id: str, request: Request) -> dict:
    """Pide detener el scraping de una tienda. El worker lo nota entre consultas."""
    current_user(request, admin=True)
    from pymongo.errors import PyMongoError
    from retail.batch.store_scope import StoreBatchIdle

    try:
        return stop_store_batch(store_id)
    except StoreBatchIdle as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, PyMongoError) as exc:
        raise HTTPException(status_code=503, detail="No se pudo detener el scraping. Inténtalo de nuevo.") from exc


@router.post("/api/admin/basic-scrape")
async def post_basic_scrape(request: Request) -> dict:
    """Recorre productos ya guardados y scrapea cada categoría en sus tiendas."""
    current_user(request, admin=True)
    from retail.batch.basic_scrape import BasicScrapeBusy, BasicScrapeNothingToResume

    body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
    if not isinstance(body, dict):
        body = {}
    schedule = load_schedule()
    source = str(body.get("source") or "scrape").strip().lower()
    if source not in {"scrape", "both"}:
        source = "scrape"
    pause = body.get("pause")
    limit = body.get("limit")
    mode = body.get("mode")
    try:
        return start_basic_scrape(
            source=source,
            pause=float(pause if pause is not None else schedule.get("pause") or 2),
            delay=float(body.get("delay") or 1),
            max_items=int(body.get("max") or body.get("max_items") or 6),
            limit=int(limit) if limit not in (None, "") else None,
            persist=not bool(body.get("dry_run")),
            mode=mode,
        )
    except BasicScrapeBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BasicScrapeNothingToResume as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/admin/basic-scrape/stop", status_code=202)
def stop_basic_scrape_api(request: Request) -> dict:
    """Pide detener el scraping básico. El worker lo nota entre productos."""
    current_user(request, admin=True)
    from pymongo.errors import PyMongoError
    from retail.batch.basic_scrape import BasicScrapeIdle

    try:
        return stop_basic_scrape()
    except BasicScrapeIdle as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (RuntimeError, PyMongoError) as exc:
        raise HTTPException(status_code=503, detail="No se pudo detener el scraping básico. Inténtalo de nuevo.") from exc


@router.get("/api/admin/users")
def admin_users(request: Request) -> dict:
    """Cuentas de la colección users. Sin hash, tokens ni ids de Telegram."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        users = repo.list_admin_users()
    finally:
        repo.close()
    return {"users": users, "total": len(users)}


@router.get("/api/admin/stats")
def admin_stats(request: Request) -> dict:
    """Peticiones de la app por día, hora y origen. No cuenta archivos estáticos ni esta misma ruta."""
    current_user(request, admin=True)
    from retail.click_stats import load_click_stats
    from retail.request_stats import load_stats
    from retail.scrape_stats import load_scrape_stats
    from retail.search_cache import load_search_cache
    from retail.search_stats import load_search_stats

    payload = load_stats()
    payload["searches"] = load_search_stats()
    payload["search_cache"] = load_search_cache()
    payload["clicks"] = load_click_stats()
    payload["scrapes"] = load_scrape_stats()
    return payload


@router.get("/api/admin/cron-batches")
def cron_batches(request: Request) -> dict:
    """Estado por grupo de los crons/lotes (Mongo `batch_runs`, visible desde Docker)."""
    current_user(request, admin=True)
    from retail.batch.cron_status import build_cron_batch_status

    return build_cron_batch_status()


@router.post("/api/admin/cron-control")
async def cron_control(request: Request) -> dict:
    """Pausa o reanuda cooperativamente las corridas activas y las futuras."""
    current_user(request, admin=True)
    body = await request.json()
    action = str(body.get("action") or "").strip().lower()
    if action not in {"pause", "resume"}:
        raise HTTPException(status_code=400, detail="Acción inválida.")
    from retail.batch.config import load_schedule, save_schedule

    schedule = load_schedule()
    schedule["paused"] = action == "pause"
    saved = save_schedule(schedule)
    return {
        "ok": True,
        "paused": bool(saved.get("paused")),
        "message": "Corridas pausadas." if saved.get("paused") else "Corridas reanudadas.",
    }


@router.post("/api/admin/cron-batches/{group_id}/start", status_code=202)
async def start_cron_group(group_id: str, request: Request) -> dict:
    current_user(request, admin=True)
    from pymongo.errors import PyMongoError
    from retail.batch.group_scope import GroupBatchBusy, GroupBatchNothingToResume, GroupBatchPaused

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    mode = body.get("mode")
    try:
        return start_group_batch(group_id, mode=mode)
    except (GroupBatchBusy, GroupBatchPaused) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (GroupBatchNothingToResume, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, PyMongoError) as exc:
        raise HTTPException(status_code=503, detail="No se pudo iniciar la corrida. Inténtalo de nuevo.") from exc


@router.post("/api/admin/cron-batches/{group_id}/stop", status_code=202)
def stop_cron_group(group_id: str, request: Request) -> dict:
    current_user(request, admin=True)
    from pymongo.errors import PyMongoError
    from retail.batch.group_scope import GroupBatchIdle

    try:
        return stop_group_batch(group_id)
    except GroupBatchIdle as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, PyMongoError) as exc:
        raise HTTPException(status_code=503, detail="No se pudo detener la corrida. Inténtalo de nuevo.") from exc


@router.get("/api/admin/cron-batches/{run_id}/alerts")
def cron_batch_alerts(run_id: str, request: Request) -> dict:
    """Ofertas que cuenta `alert_count` de esa corrida (`alerts.run`, no envíos)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        found = repo.alerts_for_batch_run(run_id)
    finally:
        repo.close()
    if found is None:
        raise HTTPException(status_code=404, detail="No existe esa corrida.")
    titles = {spec.id: spec.title for spec in list_stores()}
    for item in found["items"]:
        store = item.get("store") or ""
        from retail.store_display import display_store

        item["display_store"], item["store_title"] = display_store(item, titles)
        rival = item.get("second_store") or ""
        if rival:
            item["second_store_title"] = titles.get(rival, rival)
    return found


def _notice_response(result: dict) -> dict:
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "No se pudo enviar.")
    return {"ok": True, "message": result.get("message") or "Enviado."}


def _admin_user_document(user: dict) -> dict:
    repo = connect_repo()
    if repo is None or not user.get("id"):
        return {}
    try:
        return repo.find_user_by_id(str(user["id"])) or {}
    finally:
        repo.close()


@router.post("/api/admin/test-telegram")
def admin_test_telegram(request: Request) -> dict:
    """Un mensaje de prueba al chat guardado (canales o cuenta). Sin token en la respuesta."""
    user = current_user(request, admin=True) or {}
    from retail.batch.alerts import send_telegram_test

    return _notice_response(send_telegram_test(_admin_user_document(user)))


@router.post("/api/admin/test-email")
async def admin_test_email(request: Request) -> dict:
    """Correo de prueba. El formulario puede indicar otro destinatario; si no, la cuenta o el default."""
    user = current_user(request, admin=True) or {}
    from retail.batch.alerts import DEFAULT_NOTICE_TEST_EMAIL, send_email_test

    typed = ""
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            typed = str(body.get("to") or body.get("email") or "").strip()
    recipient = typed or str(user.get("email") or "").strip() or DEFAULT_NOTICE_TEST_EMAIL
    return _notice_response(send_email_test(recipient))


@router.post("/api/admin/test-push")
def admin_test_push(request: Request) -> dict:
    """Push de prueba a los dispositivos de la cuenta admin (suscritos en Siguiendo)."""
    user = current_user(request, admin=True) or {}
    from retail.batch.alerts import send_push_test

    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        document = repo.find_user_by_id(str(user.get("id") or "")) or {}
        return _notice_response(send_push_test(document, repo=repo))
    finally:
        repo.close()


@router.get("/api/admin/overview")
def admin_overview(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    mongo = repo is not None
    stats = {
        "products": 0,
        "searches": 0,
        "alerts": 0,
        "watches": 0,
        "categories": 0,
        "last_run": None,
    }
    if repo is not None:
        try:
            stats.update(repo.stats_overview())
        finally:
            repo.close()
    catalog = load_catalog()
    products = catalog.get("products") or []
    redis_ok = False
    try:
        from retail.search_cache import connect_redis

        redis_ok = connect_redis() is not None
    except Exception:
        redis_ok = False
    live = batch_status()
    return {
        "mongo": mongo,
        "qdrant": connect_qdrant() is not None,
        "redis": redis_ok,
        "stores": len(list_stores()),
        "catalog": {
            "title": catalog.get("title") or "",
            "items": len(products),
            "enabled": sum(1 for item in products if item.get("enabled", True)),
        },
        "schedule": schedule_status(),
        "job": live,
        **stats,
    }
