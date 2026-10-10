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
    from retail.cyber_day import (
        CYBER_GROUP_ID,
        CYBER_GROUP_TITLE,
        CyberDayError,
        continue_run,
        ensure_cyber_category,
        is_cyber_group,
        restart_run,
        start_run,
    )
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
        schedule = load_schedule(repo)
        if schedule.get("paused"):
            raise GroupBatchPaused()

        # Grupo lista fija Cyber: el worker `precios-cyber-worker` hace el loop.
        if is_cyber_group(group):
            ensure_cyber_category(repo)
            try:
                if action == "continue":
                    result = continue_run(repo)
                    message = f"Continuando {CYBER_GROUP_TITLE} desde la query actual."
                else:
                    # Iniciar / Reiniciar: vuelta desde #1 en loop continuo.
                    result = restart_run(repo) if action == "restart" else start_run(repo)
                    message = (
                        f"Reiniciando {CYBER_GROUP_TITLE} desde la query 1."
                        if action == "restart"
                        else f"Corrida iniciada para {CYBER_GROUP_TITLE} (loop continuo)."
                    )
            except CyberDayError as exc:
                raise ValueError(str(exc)) from exc
            return {
                "ok": True,
                "running": True,
                "grupo": CYBER_GROUP_ID,
                "run_id": CYBER_GROUP_ID,
                "mode": action or "schedule",
                "query_list": True,
                "message": message,
                "cyber": (result.get("run") if isinstance(result, dict) else None),
            }

        stores = stores_for_group(group, repo=repo)
        if not stores:
            raise ValueError(f"El grupo «{group}» no tiene tiendas registradas.")
        title = next(
            (item.get("title") or group for item in list_store_categories(repo=repo) if item["id"] == group),
            group,
        )
        if action == "restart" and hasattr(repo, "clear_group_batch_cursor"):
            repo.clear_group_batch_cursor(group)
        elif action == "continue":
            from retail.batch.group_scope import batch_cursor_key

            previous = repo.latest_group_batch_run(group) if hasattr(repo, "latest_group_batch_run") else None
            # Preferir cursor del turno (next_id tras presupuesto) a rehacer la última búsqueda.
            product = None
            if hasattr(repo, "get_app_setting"):
                cursor = repo.get_app_setting(batch_cursor_key(group)) or {}
                product = str(cursor.get("next_id") or "").strip() or None
            if not product:
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
    from retail.cyber_day import CYBER_GROUP_ID, CYBER_GROUP_TITLE, CyberDayError, is_cyber_group, stop_run
    from retail.search import connect_repo
    from retail.store_categories import list_store_categories, normalize_group

    repo = connect_repo()
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; no se pudo detener la corrida.")
    try:
        group = normalize_group(grupo, repo=repo)
        if is_cyber_group(group):
            try:
                stop_run(repo)
            except CyberDayError as exc:
                raise GroupBatchIdle(CYBER_GROUP_ID) from exc
            return {
                "ok": True,
                "grupo": CYBER_GROUP_ID,
                "message": f"Deteniendo {CYBER_GROUP_TITLE}. Las demás corridas siguen.",
            }
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


def _run_group(group: str, run_id: str, *, _interrupt_attempt: int = 0, **kwargs) -> None:
    try:
        from retail.batch.group_scope import interrupt_auto_retries, interrupt_retry_delay_seconds
        from retail.batch.runner import run_batch

        summary = run_batch(grupo=group, batch_run_id=run_id, **kwargs) or {}
        if not summary.get("interrupted"):
            return
        # Shutdown del pool suele ir con muerte del proceso (deploy); el arranque
        # del web o el cron de soyo reanudarán. Reintento in-process solo si el
        # proceso sigue vivo y quedan cupos.
        if summary.get("shutdown_interrupt"):
            logger.warning(
                "Corrida de %s interrumpida por shutdown del executor; "
                "reanudación vía arranque web / cron soyo (intento %s)",
                group,
                _interrupt_attempt,
            )
            return
        max_retries = interrupt_auto_retries()
        if _interrupt_attempt >= max_retries:
            logger.warning(
                "Corrida de %s interrumpida; sin más reintentos automáticos (%s/%s)",
                group,
                _interrupt_attempt,
                max_retries,
            )
            return
        delay = interrupt_retry_delay_seconds(_interrupt_attempt)
        logger.info(
            "Reintento automático %s/%s de %s tras interrupción (espera %.0fs)",
            _interrupt_attempt + 1,
            max_retries,
            group,
            delay,
        )
        import time

        time.sleep(delay)
        # Nueva corrida en su propio thread (mode=continue usa el cursor Mongo).
        start_group_batch(group, mode="continue")
    except Exception as exc:
        logger.exception("La corrida de %s falló", group)
        from retail.search import connect_repo

        repo = connect_repo()
        if repo is not None:
            try:
                repo.finish_batch_run(run_id, status="failed", last_error=str(exc))
            finally:
                repo.close()


def resume_interrupted_group_batches(*, limit: int = 2) -> dict[str, Any]:
    """Tras deploy/reinicio: Continuar grupos con última corrida ``interrupted`` de hoy.

    Tope ``limit`` y ``BATCH_INTERRUPT_RETRIES`` para no abrir un torbellino.
    """
    from retail.batch.cron_status import chile_today, started_on_chile_day
    from retail.batch.group_scope import (
        batch_web_auto_resume_enabled,
        interrupt_auto_retries,
        is_interrupt_status,
    )
    from retail.search import connect_repo

    if not batch_web_auto_resume_enabled():
        return {"ok": True, "skipped": True, "reason": "BATCH_WEB_AUTO_RESUME off", "resumed": []}

    max_retries = interrupt_auto_retries()
    if max_retries <= 0:
        return {"ok": True, "skipped": True, "reason": "BATCH_INTERRUPT_RETRIES=0", "resumed": []}

    repo = connect_repo()
    if repo is None:
        return {"ok": False, "error": "Mongo unavailable", "resumed": []}

    resumed: list[str] = []
    today = chile_today()
    try:
        by_group = repo.latest_batch_runs_by_grupo() if hasattr(repo, "latest_batch_runs_by_grupo") else {}
        candidates: list[tuple[str, dict[str, Any]]] = []
        for group, run in (by_group or {}).items():
            if not is_interrupt_status(run.get("status")):
                continue
            if not started_on_chile_day(run, today):
                continue
            retries = int(run.get("interrupt_retries") or 0)
            if retries >= max_retries:
                continue
            if int(run.get("processed") or 0) <= 0 and not resume_product_available(repo, group, run):
                continue
            candidates.append((str(group), run))
        candidates.sort(key=lambda item: str(item[1].get("finished_at") or ""), reverse=True)
        for group, run in candidates[: max(0, int(limit))]:
            try:
                run_id = str(run.get("id") or "").strip()
                if run_id and hasattr(repo, "update_batch_run"):
                    repo.update_batch_run(
                        run_id,
                        interrupt_retries=int(run.get("interrupt_retries") or 0) + 1,
                    )
                start_group_batch(group, mode="continue")
                resumed.append(group)
                logger.info("Auto-reanudación tras interrupción: grupo=%s", group)
            except Exception as exc:
                logger.warning("No se pudo auto-reanudar %s: %s", group, exc)
    finally:
        repo.close()
    return {"ok": True, "resumed": resumed, "limit": limit}


def resume_product_available(repo: Any, group: str, run: dict[str, Any] | None) -> bool:
    from retail.batch.group_scope import batch_cursor_key, resume_product_id

    product = resume_product_id(run)
    if product:
        return True
    if hasattr(repo, "get_app_setting"):
        cursor = repo.get_app_setting(batch_cursor_key(group)) or {}
        return bool(str(cursor.get("next_id") or "").strip())
    return False


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
