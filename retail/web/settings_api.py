from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

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
    from retail.search_freq import load_search_freq
    from retail.search_stats import load_search_stats

    payload = load_stats()
    payload["searches"] = load_search_stats()
    payload["search_cache"] = load_search_cache()
    payload["search_freq"] = load_search_freq()
    payload["clicks"] = load_click_stats()
    payload["scrapes"] = load_scrape_stats()
    try:
        from retail.funnel_stats import load_funnel_stats

        payload["funnel"] = load_funnel_stats()
    except Exception:
        payload["funnel"] = {"steps": []}
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


def _cyber_list_param(request: Request, body: dict | None = None) -> str | None:
    if body:
        for key in ("list_id", "list", "slug"):
            value = body.get(key)
            if value:
                return str(value).strip()
    for key in ("list", "list_id", "slug"):
        value = request.query_params.get(key)
        if value:
            return str(value).strip()
    return None


@router.get("/api/admin/cyber-day")
def cyber_day_status(request: Request) -> dict:
    """Estado, progreso y lista Cyber Day (JSON-safe; no bloquea la UI)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import set_active_list, status_payload

        list_id = _cyber_list_param(request)
        if list_id:
            set_active_list(repo, list_id)
        # enrich_missing=False: el worker completa precios; la UI no debe colgarse.
        return status_payload(repo, list_id=list_id, enrich_missing=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cyber Day status falló: {exc}") from exc
    finally:
        repo.close()


@router.get("/api/admin/cyber-day/lists")
def cyber_day_lists(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import list_all_lists, resolve_list_id

        return {"ok": True, "lists": list_all_lists(repo), "active": resolve_list_id(repo)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Cyber Day lists falló: {exc}") from exc
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/lists")
async def cyber_day_create_list(request: Request) -> dict:
    """Crea una lista nueva (nombre/slug) con seed, copia u opcionalmente vacía."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, create_list

        body = {}
        content_type = request.headers.get("content-type") or ""
        if "application/json" in content_type:
            raw = await request.json()
            body = raw if isinstance(raw, dict) else {}
        else:
            form = await request.form()
            body = {k: form.get(k) for k in form.keys()}
        name = str(body.get("name") or body.get("title") or "").strip()
        slug = str(body.get("slug") or body.get("list_id") or "").strip() or None
        copy_from = str(body.get("copy_from") or "").strip() or None
        use_seed = str(body.get("use_seed") or body.get("seed") or "").lower() in {
            "1", "true", "yes", "on", "si", "sí",
        }
        if not name and not slug:
            raise HTTPException(status_code=400, detail="Indicá un nombre o slug para la lista.")
        try:
            return create_list(
                repo,
                name=name or slug or "lista",
                slug=slug,
                copy_from=copy_from,
                use_seed=use_seed,
            )
        except CyberDayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/start")
def cyber_day_start(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, start_run

        return start_run(repo, list_id=_cyber_list_param(request))
    except CyberDayError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/stop")
def cyber_day_stop(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, stop_run

        return stop_run(repo, list_id=_cyber_list_param(request))
    except CyberDayError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/continue")
def cyber_day_continue(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, continue_run

        return continue_run(repo, list_id=_cyber_list_param(request))
    except CyberDayError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/import")
async def cyber_day_import(request: Request) -> dict:
    """Importa lista Sonic (CSV o JSON). Reemplaza solo la lista indicada."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    filename = ""
    text = ""
    list_id = _cyber_list_param(request)
    content_type = request.headers.get("content-type") or ""
    try:
        if "multipart/form-data" in content_type:
            form = await request.form()
            list_id = str(form.get("list_id") or form.get("list") or list_id or "").strip() or list_id
            upload = form.get("file") or form.get("lista")
            if upload is not None and hasattr(upload, "read"):
                filename = str(getattr(upload, "filename", "") or "")
                raw = await upload.read()
                text = raw.decode("utf-8-sig", errors="replace")
            else:
                text = str(form.get("text") or form.get("content") or "")
        elif "application/json" in content_type:
            body = await request.json()
            if isinstance(body, dict):
                list_id = _cyber_list_param(request, body) or list_id
            if isinstance(body, list):
                from retail.cyber_day import CyberDayError, import_products, normalize_import_row

                items = [
                    row
                    for index, raw in enumerate(body)
                    if (row := normalize_import_row(raw if isinstance(raw, dict) else {}, index))
                ]
                try:
                    return import_products(repo, items, source="api-json", list_id=list_id)
                except CyberDayError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="JSON inválido.")
            if "text" in body or "content" in body:
                text = str(body.get("text") or body.get("content") or "")
                filename = str(body.get("filename") or "")
            else:
                from retail.cyber_day import CyberDayError, import_products, parse_products_payload
                import json as _json

                text = _json.dumps(body, ensure_ascii=False)
                filename = "import.json"
        else:
            text = (await request.body()).decode("utf-8-sig", errors="replace")
        from retail.cyber_day import CyberDayError, import_products, parse_products_payload

        try:
            items = parse_products_payload(text, filename=filename)
            return import_products(repo, items, source=filename or "upload", list_id=list_id)
        except CyberDayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"No se pudo leer la lista: {exc}") from exc
    finally:
        repo.close()


@router.get("/api/admin/cyber-day/export.csv")
def cyber_day_export_csv(request: Request) -> Response:
    """Descarga la lista Cyber (n, query, category + matches/precio)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import export_csv, resolve_list_id

        list_id = resolve_list_id(repo, _cyber_list_param(request))
        body = export_csv(repo, list_id)
        return Response(
            content=body,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{list_id}.csv"',
            },
        )
    finally:
        repo.close()


@router.get("/api/admin/cyber-day/export.json")
def cyber_day_export_json(request: Request) -> JSONResponse:
    """Descarga la lista Cyber en JSON (mismo shape que el seed)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import export_json, resolve_list_id

        list_id = resolve_list_id(repo, _cyber_list_param(request))
        payload = export_json(repo, list_id)
        return JSONResponse(
            content=payload,
            headers={
                "Content-Disposition": f'attachment; filename="{list_id}.json"',
            },
        )
    finally:
        repo.close()


@router.post("/api/admin/cyber-day/restart")
def cyber_day_restart(request: Request) -> dict:
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, restart_run

        return restart_run(repo, list_id=_cyber_list_param(request))
    except CyberDayError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        repo.close()


@router.patch("/api/admin/cyber-day/items/{n}")
@router.put("/api/admin/cyber-day/items/{n}")
async def cyber_day_update_item(n: int, request: Request) -> dict:
    """Edita query/categoría de una fila (también con el loop en curso)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    try:
        from retail.cyber_day import CyberDayError, update_item

        body: dict = {}
        content_type = request.headers.get("content-type") or ""
        if "application/json" in content_type:
            raw = await request.json()
            body = raw if isinstance(raw, dict) else {}
        else:
            form = await request.form()
            body = {k: form.get(k) for k in form.keys()}
        query = body.get("query")
        category = body.get("category")
        if query is None and category is None:
            raise HTTPException(status_code=400, detail="Indicá query o category.")
        if query is not None:
            query = str(query)
        if category is not None:
            category = str(category)
        try:
            return update_item(
                repo,
                n,
                query=query,
                category=category,
                list_id=_cyber_list_param(request, body),
            )
        except CyberDayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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
