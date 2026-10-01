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


def start_group_batch(grupo: str) -> dict[str, Any]:
    """Registra el arranque en Mongo antes de responder y ejecuta solo ese grupo."""
    from retail.batch.config import load_schedule
    from retail.batch.group_scope import GroupBatchPaused
    from retail.search import connect_repo
    from retail.store_categories import list_store_categories, normalize_group, stores_for_group

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
    return {
        "ok": True, "running": True, "grupo": group, "run_id": run_id,
        "message": f"Corrida iniciada para {title}.",
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


def start_store_batch(tienda: str, **kwargs) -> dict[str, Any]:
    """Arranca el scrape de una tienda en segundo plano. No bloquea el request."""
    from retail.batch.store_scope import StoreBatchBusy, normalize_store, store_batch_is_busy, store_title
    from retail.search import connect_repo

    store_id = normalize_store(tienda)
    title = store_title(store_id)
    with _STORE_LOCK:
        if store_id in _STORE_RUNNING:
            raise StoreBatchBusy(store_id, title)
        repo = connect_repo()
        try:
            if store_batch_is_busy(repo, store_id):
                raise StoreBatchBusy(store_id, title)
        finally:
            if repo is not None:
                repo.close()
        _STORE_RUNNING.add(store_id)
    thread = threading.Thread(
        target=_run_store,
        args=(store_id,),
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
    return {
        "ok": True,
        "running": True,
        "tienda": store_id,
        "title": title,
        "message": f"Scraping iniciado para {title}.",
    }


_BASIC_LOCK = threading.Lock()
_BASIC_RUNNING = False


def start_basic_scrape(**kwargs) -> dict[str, Any]:
    """Arranca el barrido de productos ya guardados. No bloquea el request."""
    from retail.batch.basic_scrape import BasicScrapeBusy, basic_scrape_is_busy
    from retail.search import connect_repo

    global _BASIC_RUNNING
    with _BASIC_LOCK:
        if _BASIC_RUNNING:
            raise BasicScrapeBusy()
        repo = connect_repo()
        try:
            if repo is None:
                raise RuntimeError("MongoDB no está disponible; el scraping básico no puede guardar productos.")
            if basic_scrape_is_busy(repo):
                raise BasicScrapeBusy()
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
    return {
        "ok": True,
        "running": True,
        "job": "scraping_basico",
        "message": "Scraping básico iniciado.",
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


def _run_store(store_id: str, **kwargs) -> None:
    try:
        from retail.batch.runner import run_batch

        run_batch(tienda=store_id, **kwargs)
    except Exception:
        logger.exception("El scraping de %s falló", store_id)
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
