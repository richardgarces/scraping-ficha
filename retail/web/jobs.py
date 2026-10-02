from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"running": False, "last": None, "error": None}


def start_batch(**kwargs) -> dict[str, Any]:
    with _LOCK:
        if _STATE["running"]:
            return {"running": True, "message": "Ya hay un batch en curso."}
        _STATE["running"] = True
        _STATE["error"] = None
    thread = threading.Thread(target=_run, kwargs=kwargs, daemon=True)
    thread.start()
    return {"running": True, "message": "Batch iniciado."}


def batch_status() -> dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def start_group_batch(grupo: str, *, mode: str | None = None) -> dict[str, Any]:
    """Registra el arranque en Mongo antes de responder y ejecuta solo ese grupo.

    mode:
      - None: usa el cursor guardado (turno diario / continuar implícito)
      - continue: coloca el cursor en el último producto de una corrida fallida o detenida
      - restart: borra el cursor y parte desde el comienzo del catálogo
    """
    from retail.batch.config import load_schedule
    from retail.batch.group_scope import GroupBatchNothingToResume, GroupBatchPaused, resume_product_id
    from retail.search import connect_repo
    from retail.store_categories import list_store_categories, normalize_group, stores_for_group

    action = (mode or "").strip().lower() or None
    if action not in {None, "continue", "restart"}:
        raise ValueError("Modo inválido. Usa continuar o reiniciar.")

    repo = connect_repo()
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; no se pudo iniciar la corrida.")
    try:
        group = normalize_group(grupo, repo=repo)
        stores = stores_for_group(group, repo=repo)
        if not stores:
            raise ValueError(f"El grupo «{group}» no tiene tiendas registradas.")
        schedule = load_schedule(repo)
        if schedule.get("paused"):
            raise GroupBatchPaused()
        title = next(
            (item.get("title") or group for item in list_store_categories(repo=repo) if item["id"] == group),
            group,
        )
        if action == "restart" and hasattr(repo, "clear_group_batch_cursor"):
            repo.clear_group_batch_cursor(group)
        elif action == "continue":
            previous = repo.latest_group_batch_run(group) if hasattr(repo, "latest_group_batch_run") else None
            product = resume_product_id(previous)
            if not product:
                raise GroupBatchNothingToResume(group)
            repo.set_group_batch_cursor(group, product)
        kwargs = {
            "source": schedule["source"],
            "pause": schedule["pause"],
            "time_budget_minutes": schedule["batch_budget_minutes"],
            "persist": True,
        }
        run_id = repo.start_batch_run({
            "grupo": group, "scope": "grupo", "stores": stores,
            "source": kwargs["source"], "persist": True, "phase": "starting",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "resume_mode": action or "schedule",
        })
        try:
            thread = threading.Thread(
                target=_run_group, args=(group, run_id), kwargs=kwargs,
                daemon=True, name=f"group-batch-{group}",
            )
            thread.start()
        except Exception:
            repo.finish_batch_run(run_id, status="failed", last_error="No se pudo iniciar el worker del grupo.")
            raise RuntimeError("No se pudo iniciar la corrida. Inténtalo de nuevo.") from None
    finally:
        repo.close()
    if action == "continue":
        message = f"Continuando {title} desde donde quedó."
    elif action == "restart":
        message = f"Reiniciando {title} desde el comienzo."
    else:
        message = f"Corrida iniciada para {title}."
    return {
        "ok": True, "running": True, "grupo": group, "run_id": run_id,
        "mode": action or "schedule",
        "message": message,
    }


def stop_group_batch(grupo: str) -> dict[str, Any]:
    """Pide detener un grupo. La corrida lo nota entre productos; las otras siguen."""
    from retail.batch.group_scope import GroupBatchIdle
    from retail.search import connect_repo
    from retail.store_categories import list_store_categories, normalize_group

    repo = connect_repo()
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; no se pudo detener la corrida.")
    try:
        group = normalize_group(grupo, repo=repo)
        if not repo.request_group_stop(group):
            raise GroupBatchIdle(group)
        title = next(
            (item.get("title") or group for item in list_store_categories(repo=repo) if item["id"] == group),
            group,
        )
    finally:
        repo.close()
    return {
        "ok": True,
        "grupo": group,
        "message": f"Deteniendo {title}. Las demás corridas siguen.",
    }


def _run_group(group: str, run_id: str, **kwargs) -> None:
    try:
        from retail.batch.runner import run_batch

        run_batch(grupo=group, batch_run_id=run_id, **kwargs)
    except Exception as exc:
        logger.exception("La corrida de %s falló", group)
        from retail.search import connect_repo

        repo = connect_repo()
        if repo is not None:
            try:
                repo.finish_batch_run(run_id, status="failed", last_error=str(exc))
            finally:
                repo.close()


_STORE_LOCK = threading.Lock()
_STORE_RUNNING: set[str] = set()


def start_store_batch(tienda: str, *, mode: str | None = None, **kwargs) -> dict[str, Any]:
    """Registra la corrida en Mongo antes de responder y scrapea solo esa tienda.

    mode:
      - None: usa el cursor guardado si existe
      - continue: coloca el cursor en la última consulta de una corrida fallida o detenida
      - restart: borra el cursor y parte desde el comienzo del catálogo
    """
    from datetime import datetime, timezone

    from retail.batch.group_scope import resume_product_id
    from retail.batch.store_scope import (
        StoreBatchBusy,
        StoreBatchNothingToResume,
        groups_for_store,
        normalize_store,
        store_batch_is_busy,
        store_cursor_key,
        store_title,
    )
    from retail.search import connect_repo

    action = (mode or "").strip().lower() or None
    if action not in {None, "continue", "restart"}:
        raise ValueError("Modo inválido. Usa continuar o reiniciar.")

    store_id = normalize_store(tienda)
    title = store_title(store_id)
    with _STORE_LOCK:
        if store_id in _STORE_RUNNING:
            raise StoreBatchBusy(store_id, title)
        repo = connect_repo()
        try:
            if repo is None:
                raise RuntimeError("MongoDB no está disponible; no se pudo iniciar el scraping.")
            if store_batch_is_busy(repo, store_id):
                raise StoreBatchBusy(store_id, title)
            if action == "restart" and hasattr(repo, "clear_store_batch_cursor"):
                repo.clear_store_batch_cursor(store_id)
            elif action == "continue":
                previous = repo.latest_store_batch_run(store_id) if hasattr(repo, "latest_store_batch_run") else None
                product = resume_product_id(previous)
                if not product and hasattr(repo, "get_app_setting"):
                    cursor = repo.get_app_setting(store_cursor_key(store_id)) or {}
                    product = str(cursor.get("next_id") or "").strip() or None
                if not product:
                    raise StoreBatchNothingToResume(store_id, title)
                repo.set_store_batch_cursor(store_id, product)
            groups = groups_for_store(store_id, repo=repo)
            run_id = repo.start_batch_run({
                "tienda": store_id,
                "scope": "tienda",
                "stores": [store_id],
                "groups": list(groups),
                "phase": "starting",
                "catalog": title,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "source": kwargs.get("source") or "scrape",
                "persist": bool(kwargs.get("persist", True)),
                "resume_mode": action or "schedule",
            })
        finally:
            if repo is not None:
                repo.close()
        _STORE_RUNNING.add(store_id)
    thread = threading.Thread(
        target=_run_store,
        args=(store_id, run_id),
        kwargs=kwargs,
        daemon=True,
        name=f"store-batch-{store_id}",
    )
    try:
        thread.start()
    except Exception:
        with _STORE_LOCK:
            _STORE_RUNNING.discard(store_id)
        raise
    if action == "continue":
        message = f"Continuando scraping de {title} desde donde quedó."
    elif action == "restart":
        message = f"Reiniciando scraping de {title} desde el comienzo."
    else:
        message = f"Scraping iniciado para {title}."
    return {
        "ok": True,
        "running": True,
        "tienda": store_id,
        "title": title,
        "run_id": run_id,
        "mode": action or "schedule",
        "message": message,
    }


def stop_store_batch(tienda: str) -> dict[str, Any]:
    """Pide detener el scraping de una tienda. La corrida lo nota entre consultas."""
    from retail.batch.store_scope import StoreBatchIdle, normalize_store, store_title
    from retail.search import connect_repo

    store_id = normalize_store(tienda)
    title = store_title(store_id)
    repo = connect_repo()
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; no se pudo detener el scraping.")
    try:
        if not hasattr(repo, "request_store_stop") or not repo.request_store_stop(store_id):
            raise StoreBatchIdle(store_id, title)
    finally:
        repo.close()
    return {
        "ok": True,
        "tienda": store_id,
        "message": f"Deteniendo scraping de {title}.",
    }


_BASIC_LOCK = threading.Lock()
_BASIC_RUNNING = False


def start_basic_scrape(**kwargs) -> dict[str, Any]:
    """Arranca el barrido de productos ya guardados. No bloquea el request.

    kwargs puede incluir mode=continue|restart para retomar o partir de cero.
    """
    from retail.batch.basic_scrape import (
        BasicScrapeBusy,
        BasicScrapeNothingToResume,
        basic_scrape_is_busy,
        resolve_basic_resume_after,
    )
    from retail.search import connect_repo

    global _BASIC_RUNNING
    mode = str(kwargs.pop("mode", None) or "").strip().lower() or None
    if mode not in {None, "continue", "restart"}:
        raise ValueError("Modo inválido. Usa continuar o reiniciar.")

    with _BASIC_LOCK:
        if _BASIC_RUNNING:
            raise BasicScrapeBusy()
        repo = connect_repo()
        try:
            if repo is None:
                raise RuntimeError("MongoDB no está disponible; el scraping básico no puede guardar productos.")
            if basic_scrape_is_busy(repo):
                raise BasicScrapeBusy()
            after_id = None
            prior = {}
            if mode == "restart" and hasattr(repo, "clear_basic_scrape_cursor"):
                repo.clear_basic_scrape_cursor()
            elif mode == "continue":
                previous = repo.latest_basic_scrape_run() if hasattr(repo, "latest_basic_scrape_run") else None
                after_id = resolve_basic_resume_after(repo, previous)
                if previous:
                    prior = {
                        "processed": int(previous.get("processed") or 0),
                        "saved_upserted": int(previous.get("saved_upserted") or 0),
                        "saved_modified": int(previous.get("saved_modified") or 0),
                        "skipped": int(previous.get("skipped") or 0),
                        "failed": int(previous.get("failed") or 0),
                    }
                if hasattr(repo, "set_basic_scrape_cursor"):
                    repo.set_basic_scrape_cursor(after_id)
            kwargs["after_id"] = after_id
            kwargs["resume_mode"] = mode or "schedule"
            kwargs["prior_progress"] = prior
        finally:
            if repo is not None:
                repo.close()
        _BASIC_RUNNING = True
    thread = threading.Thread(
        target=_run_basic,
        kwargs=kwargs,
        daemon=True,
        name="basic-scrape",
    )
    try:
        thread.start()
    except Exception:
        with _BASIC_LOCK:
            _BASIC_RUNNING = False
        raise
    if mode == "continue":
        message = "Continuando scraping básico desde donde quedó."
    elif mode == "restart":
        message = "Reiniciando scraping básico desde el comienzo."
    else:
        message = "Scraping básico iniciado."
    return {
        "ok": True,
        "running": True,
        "job": "scraping_basico",
        "mode": mode or "schedule",
        "message": message,
    }


def stop_basic_scrape() -> dict[str, Any]:
    """Pide detener el scraping básico. La corrida lo nota entre productos."""
    from retail.batch.basic_scrape import BasicScrapeIdle
    from retail.search import connect_repo

    repo = connect_repo()
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; no se pudo detener el scraping básico.")
    try:
        if not hasattr(repo, "request_basic_stop") or not repo.request_basic_stop():
            raise BasicScrapeIdle()
    finally:
        repo.close()
    return {
        "ok": True,
        "job": "scraping_basico",
        "message": "Deteniendo scraping básico.",
    }


def _run_basic(**kwargs) -> None:
    global _BASIC_RUNNING
    try:
        from retail.batch.basic_scrape import BasicScrapeBusy, run_basic_scrape

        try:
            run_basic_scrape(**kwargs)
        except BasicScrapeBusy:
            logger.warning("Scraping básico ya estaba en curso.")
    except Exception:
        logger.exception("El scraping básico falló")
    finally:
        with _BASIC_LOCK:
            _BASIC_RUNNING = False


def _run_store(store_id: str, run_id: str, **kwargs) -> None:
    try:
        from retail.batch.runner import run_batch

        run_batch(tienda=store_id, batch_run_id=run_id, **kwargs)
    except Exception as exc:
        logger.exception("El scraping de %s falló", store_id)
        from retail.search import connect_repo

        repo = connect_repo()
        if repo is not None:
            try:
                repo.finish_batch_run(run_id, status="failed", last_error=str(exc))
            finally:
                repo.close()
    finally:
        with _STORE_LOCK:
            _STORE_RUNNING.discard(store_id)


def _run(**kwargs) -> None:
    try:
        from retail.batch.runner import run_batch

        summary = run_batch(**kwargs)
        with _LOCK:
            _STATE["last"] = summary
            _STATE["running"] = False
    except Exception as exc:
        with _LOCK:
            _STATE["error"] = str(exc)
            _STATE["running"] = False
