"""Estado de crons/lotes por grupo de tiendas (Mongo `batch_runs`).

El batch corre en el host (cron) y el web en Docker: el progreso se lee de Mongo
compartido, no de logs locales ni del estado in-process de `/api/batch/status`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retail.batch.config import load_schedule
from retail.batch.schedule import group_slots, schedule_status
from retail.registry import group_of, list_stores
from retail.store_categories import list_store_categories
from retail.store_display import public_store_key, public_store_label

TZ_CL = ZoneInfo("America/Santiago")

PHASE_LABELS = {
    "starting": "Arrancando",
    "index": "Índice de productos",
    "watches": "Seguidos",
    "products": "Catálogo",
    "paused": "Pausado por el administrador",
    "stopping": "Deteniendo",
    "stopped": "Detenida",
    "digest": "Resumen",
    "done": "Listo",
    "budget_done": "Turno completado",
    "failed": "Falló",
}


def chile_today() -> str:
    return datetime.now(TZ_CL).strftime("%Y-%m-%d")


def _parse_when(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def started_on_chile_day(run: dict[str, Any] | None, day: str | None = None) -> bool:
    if not run:
        return False
    when = _parse_when(run.get("started_at"))
    if when is None:
        return False
    return when.astimezone(TZ_CL).strftime("%Y-%m-%d") == (day or chile_today())


def normalize_run_status(raw: str | None) -> str:
    status = (raw or "").strip().lower()
    if status == "error":
        return "failed"
    return status or "unknown"


def derive_group_status(run: dict[str, Any] | None, *, today: str | None = None) -> str:
    """idle | running | failed | done — done/failed solo cuentan si la corrida es de hoy (CL)."""
    if not run:
        return "idle"
    status = normalize_run_status(run.get("status"))
    if status == "running":
        if run.get("phase") == "paused":
            return "paused"
        return "running"
    if not started_on_chile_day(run, today):
        return "idle"
    if status == "failed":
        return "failed"
    if status == "stopped":
        return "stopped"
    if status == "done":
        return "done"
    return "idle"


def progress_payload(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run or normalize_run_status(run.get("status")) != "running":
        return None
    items = int(run.get("items") or 0)
    processed = int(run.get("processed") or 0)
    percent = round(100.0 * processed / items, 1) if items > 0 else None
    phase = run.get("phase") or "products"
    return {
        "phase": phase,
        "phase_label": PHASE_LABELS.get(str(phase), str(phase)),
        "processed": processed,
        "items": items,
        "percent": percent,
        "current_query": run.get("current_query"),
        "current_id": run.get("current_id"),
        "current_index": run.get("current_index"),
        "stores_total": int(run.get("stores_total") or len(run.get("stores") or [])),
        "saved_upserted": int(run.get("saved_upserted") or 0),
        "saved_modified": int(run.get("saved_modified") or 0),
        "new": int(run.get("saved_upserted") or 0),
        "updated": int(run.get("saved_modified") or 0),
        "skipped": int(run.get("skipped") or 0),
        "last_error": run.get("last_error"),
    }


def public_run_summary(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not run:
        return None
    return {
        "id": run.get("id"),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "status": normalize_run_status(run.get("status")),
        "phase": run.get("phase"),
        "processed": int(run.get("processed") or 0),
        "items": run.get("items"),
        "alert_count": int(run.get("alert_count") or 0),
        "failed": int(run.get("failed") or 0),
        "executed_searches": int(run.get("executed_searches") or 0),
        "duration_seconds": float(run.get("duration_seconds") or 0),
        "queries_per_minute": float(run.get("queries_per_minute") or 0),
        "budget_exhausted": bool(run.get("budget_exhausted")),
        "suspended_stores": list(run.get("suspended_stores") or []),
        "last_error": run.get("last_error"),
        "saved_upserted": int(run.get("saved_upserted") or 0),
        "saved_modified": int(run.get("saved_modified") or 0),
        "new": int(run.get("saved_upserted") or 0),
        "updated": int(run.get("saved_modified") or 0),
        "skipped": int(run.get("skipped") or 0),
    }


def build_cron_batch_status(*, repo: Any | None = None, today: str | None = None) -> dict[str, Any]:
    """Lista cada grupo con horario, estado del día y progreso si está corriendo."""
    schedule = load_schedule()
    sched_public = schedule_status()
    slots = {grupo: {"hour": hour, "minute": minute} for grupo, hour, minute in group_slots(schedule)}
    day = today or chile_today()

    close = False
    local = repo
    if local is None:
        from retail.search import connect_repo

        local = connect_repo()
        close = local is not None

    runs_by_grupo: dict[str, dict[str, Any]] = {}
    runs_by_tienda: dict[str, dict[str, Any]] = {}
    basic_run: dict[str, Any] | None = None
    categories: list[dict[str, Any]] = []
    try:
        if local is not None:
            cleanup = getattr(local, "fail_stale_batch_runs", None)
            if cleanup is not None:
                cleanup(hours=3)
            runs_by_grupo = local.latest_batch_runs_by_grupo()
            by_store = getattr(local, "latest_batch_runs_by_tienda", None)
            if by_store is not None:
                runs_by_tienda = by_store()
            by_job = getattr(local, "latest_batch_run_by_job", None)
            if by_job is not None:
                basic_run = by_job("scraping_basico")
        categories = list_store_categories(repo=local)
    finally:
        if close and local is not None:
            local.close()

    groups: list[dict[str, Any]] = []
    any_running = False
    for cat in categories:
        gid = str(cat.get("id") or "").strip().lower()
        if not gid:
            continue
        run = runs_by_grupo.get(gid)
        status = derive_group_status(run, today=day)
        if status in {"running", "paused"}:
            any_running = True
        slot = slots.get(gid) or {
            "hour": int(6 if schedule.get("hour") is None else schedule["hour"]),
            "minute": int(0 if schedule.get("minute") is None else schedule["minute"]),
        }
        groups.append(
            {
                "id": gid,
                "title": cat.get("title") or gid,
                "store_count": len(cat.get("store_ids") or []),
                "schedule": {
                    "hour": slot["hour"],
                    "minute": slot["minute"],
                    "label": f"{slot['hour']:02d}:{slot['minute']:02d}",
                },
                "status": status,
                "progress": progress_payload(run) if status in {"running", "paused"} else None,
                "last_run": public_run_summary(run),
            }
        )

    titles = {spec.id: spec.title for spec in list_stores()}
    store_jobs: list[dict[str, Any]] = []
    for store_id, run in runs_by_tienda.items():
        status = derive_group_status(run, today=day)
        if status in {"running", "paused"}:
            any_running = True
        store_jobs.append(
            {
                "id": store_id,
                "public_id": public_store_key(store_id),
                "title": public_store_label(store_id, titles),
                "groups": list(run.get("groups") or []),
                "status": status,
                "progress": progress_payload(run) if status in {"running", "paused"} else None,
                "last_run": public_run_summary(run),
            }
        )
    store_jobs.sort(key=lambda item: (item["status"] not in {"running", "paused"}, item["title"].lower()))

    basic_status = derive_group_status(basic_run, today=day)
    if basic_status in {"running", "paused"}:
        any_running = True
    basic_scrape = {
        "id": "scraping_basico",
        "title": "Scraping básico",
        "status": basic_status,
        "progress": progress_payload(basic_run) if basic_status in {"running", "paused"} else None,
        "last_run": public_run_summary(basic_run),
    }

    registered: list[dict[str, Any]] = []
    for spec in list_stores():
        gid, gtitle, _order = group_of(spec.id)
        registered.append(
            {
                "id": spec.id,
                "public_id": public_store_key(spec.id),
                "title": public_store_label(spec.id, titles),
                "group": gid,
                "group_title": gtitle,
            }
        )
    registered.sort(key=lambda item: item["title"].lower())

    return {
        "today": day,
        "timezone": "America/Santiago",
        "any_running": any_running,
        "schedule": {
            "enabled": bool(sched_public.get("enabled")),
            "paused": bool(sched_public.get("paused")),
            "source": sched_public.get("source"),
            "pause": sched_public.get("pause"),
            "batch_budget_minutes": int(sched_public.get("batch_budget_minutes") or 90),
            "backend": sched_public.get("backend"),
            "stagger_minutes": int((sched_public.get("groups") or {}).get("stagger_minutes") or 45),
            "hint": sched_public.get("hint"),
        },
        "groups": groups,
        "stores": registered,
        "store_jobs": store_jobs,
        "basic_scrape": basic_scrape,
    }
