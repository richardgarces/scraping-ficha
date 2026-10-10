"""Scrape async on-miss para cotizaciones (lista de compra).

Cotizar responde con Mongo; las celdas vacías encolan búsqueda por tienda+query.
Un worker (thread en web o `python -m retail.quote_miss_jobs`) ejecuta
``search_products`` y marca el job done para que el rebuild/poll complete la matriz.
"""
from __future__ import annotations

import argparse
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.quotes import QuoteLine
from retail.relevance import fold
from retail.shopping_list import _line_search_query

log = logging.getLogger("retail.quote_miss_jobs")

COLLECTION = "quote_miss_jobs"
MAX_JOBS_PER_COTIZAR = 40
DEDUPE_MINUTES = 30
LEASE_SECONDS = 180
BATCH_SIZE = 2
IDLE_SLEEP = 4.0
SEARCHING_LABEL = "buscando en tienda…"

_worker_started = False
_worker_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll(repo: Any):
    direct = getattr(repo, "quote_miss_jobs", None)
    if direct is not None:
        return direct
    db = getattr(repo, "db", None)
    if db is None:
        return None
    try:
        return db[COLLECTION]
    except TypeError:
        return getattr(db, COLLECTION, None)


def ensure_indexes(repo: Any) -> None:
    coll = _coll(repo)
    if coll is None:
        return
    try:
        coll.create_index(
            [("status", 1), ("next_at", 1), ("created_at", 1)],
            name="quote_miss_claim",
        )
        coll.create_index(
            [("store", 1), ("folded_query", 1), ("status", 1), ("created_at", -1)],
            name="quote_miss_dedupe",
        )
        coll.create_index(
            [("quote_id", 1), ("line_index", 1), ("store", 1)],
            name="quote_miss_quote_line_store",
        )
    except Exception as exc:
        log.debug("quote_miss indexes: %s", exc)


def _pending_duplicate(repo: Any, store: str, folded_query: str, *, now: datetime) -> bool:
    since = now - timedelta(minutes=DEDUPE_MINUTES)
    found = _coll(repo).find_one(
        {
            "store": store,
            "folded_query": folded_query,
            "status": {"$in": ["pending", "running"]},
            "created_at": {"$gte": since},
        },
        {"_id": 1},
    )
    return found is not None


def enqueue_miss_jobs(
    repo: Any,
    quote_id: str,
    quote: dict[str, Any],
    matches: dict[str, dict[str, dict]],
    *,
    max_jobs: int = MAX_JOBS_PER_COTIZAR,
) -> tuple[dict[str, dict[str, dict]], int]:
    """Encola scrapes para celdas vacías y las marca ``searching``.

    Returns:
        (matches_actualizados, jobs_creados)
    """
    coll = _coll(repo)
    if coll is None:
        return matches, 0
    ensure_indexes(repo)
    now = _now()
    items = list(quote.get("items") or [])
    created = 0
    out: dict[str, dict[str, dict]] = {}
    for index_key, per_store in (matches or {}).items():
        if not isinstance(per_store, dict):
            continue
        try:
            line_index = int(index_key)
        except (TypeError, ValueError):
            out[index_key] = per_store
            continue
        if line_index < 0 or line_index >= len(items):
            out[index_key] = per_store
            continue
        try:
            line = QuoteLine.model_validate(items[line_index])
        except Exception:
            out[index_key] = dict(per_store)
            continue
        query = _line_search_query(line) or str(line.name or "").strip()
        folded = fold(query)
        updated: dict[str, dict] = {}
        for store, cell in per_store.items():
            cell = dict(cell or {})
            reason = str(cell.get("empty_reason") or "")
            if reason not in {"no_catalog", "no_match"}:
                updated[store] = cell
                continue
            store_id = str(store or "").strip().lower()
            if not store_id or not query or created >= max_jobs:
                updated[store] = cell
                continue
            if _pending_duplicate(repo, store_id, folded, now=now):
                cell["empty_reason"] = "searching"
                cell["empty_label"] = SEARCHING_LABEL
                updated[store] = cell
                continue
            job = {
                "_id": str(uuid.uuid4()),
                "quote_id": quote_id,
                "line_index": line_index,
                "store": store_id,
                "query": query,
                "folded_query": folded,
                "status": "pending",
                "attempts": 0,
                "created_at": now,
                "next_at": now,
                "updated_at": now,
                "miss_reason": reason,
            }
            try:
                coll.insert_one(job)
                created += 1
                cell["empty_reason"] = "searching"
                cell["empty_label"] = SEARCHING_LABEL
            except Exception as exc:
                log.warning("enqueue miss %s/%s: %s", store_id, query[:40], exc)
            updated[store] = cell
        out[index_key] = updated
    return out, created


def apply_pending_searching(
    repo: Any,
    quote_id: str,
    matches: dict[str, dict[str, dict]],
) -> dict[str, dict[str, dict]]:
    """Si aún hay jobs pending/running, conserva la celda como searching."""
    coll = _coll(repo)
    if coll is None:
        return matches
    active = list(
        coll.find(
            {
                "quote_id": quote_id,
                "status": {"$in": ["pending", "running"]},
            },
            {"line_index": 1, "store": 1},
        )
    )
    if not active:
        return matches
    wanted = {(int(row["line_index"]), str(row["store"])) for row in active}
    out: dict[str, dict[str, dict]] = {}
    for index_key, per_store in (matches or {}).items():
        updated = dict(per_store or {})
        try:
            line_index = int(index_key)
        except (TypeError, ValueError):
            out[index_key] = updated
            continue
        for store, cell in list(updated.items()):
            key = (line_index, str(store).lower())
            if key not in wanted:
                continue
            if cell.get("store") and cell.get("product_id"):
                continue
            cell = dict(cell or {})
            cell["empty_reason"] = "searching"
            cell["empty_label"] = SEARCHING_LABEL
            updated[store] = cell
        out[index_key] = updated
    return out


def claim_jobs(repo: Any, *, limit: int = BATCH_SIZE) -> list[dict[str, Any]]:
    coll = _coll(repo)
    now = _now()
    claimed: list[dict[str, Any]] = []
    for _ in range(max(1, limit)):
        doc = coll.find_one_and_update(
            {
                "status": "pending",
                "next_at": {"$lte": now},
            },
            {
                "$set": {
                    "status": "running",
                    "leased_at": now,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                    "updated_at": now,
                },
                "$inc": {"attempts": 1},
            },
            sort=[("created_at", 1)],
        )
        if not doc:
            break
        claimed.append(doc)
    return claimed


def _fail_job(repo: Any, job: dict[str, Any], error: str) -> None:
    attempts = int(job.get("attempts") or 1)
    coll = _coll(repo)
    now = _now()
    if attempts >= 3:
        coll.update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "error", "error": error[:500], "updated_at": now, "finished_at": now}},
        )
        return
    coll.update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "status": "pending",
                "error": error[:500],
                "next_at": now + timedelta(seconds=30 * attempts),
                "updated_at": now,
            }
        },
    )


def process_job(repo: Any, job: dict[str, Any]) -> None:
    from retail.search import search_products

    query = str(job.get("query") or "").strip()
    store = str(job.get("store") or "").strip().lower()
    if not query or not store:
        _fail_job(repo, job, "job incompleto")
        return
    try:
        search_products(
            query,
            source="scrape",
            stores=[store],
            max_items=8,
            delay=0.8,
            persist=True,
            wait_for_all=True,
            persist_meta={
                "quote_miss_job": str(job.get("_id")),
                "quote_id": job.get("quote_id"),
                "list_query": query,
            },
        )
        _coll(repo).update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "done",
                    "updated_at": _now(),
                    "finished_at": _now(),
                    "error": None,
                }
            },
        )
    except Exception as exc:
        log.warning("miss job %s %s: %s", store, query[:50], exc)
        _fail_job(repo, job, str(exc))


def run_once(repo: Any, *, limit: int = BATCH_SIZE) -> int:
    jobs = claim_jobs(repo, limit=limit)
    for job in jobs:
        process_job(repo, job)
    return len(jobs)


def worker_loop(*, idle_sleep: float = IDLE_SLEEP, stop_event: threading.Event | None = None) -> None:
    from retail.search import connect_repo

    stop = stop_event or threading.Event()
    while not stop.is_set():
        repo = connect_repo()
        if repo is None:
            stop.wait(idle_sleep)
            continue
        try:
            ensure_indexes(repo)
            n = run_once(repo)
        except Exception as exc:
            log.warning("quote miss worker: %s", exc)
            n = 0
        finally:
            try:
                repo.close()
            except Exception:
                pass
        stop.wait(0.5 if n else idle_sleep)


def start_background_worker() -> None:
    """Arranca un thread daemon en el proceso web (una sola vez)."""
    global _worker_started
    if os.environ.get("QUOTE_MISS_WORKER", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
    thread = threading.Thread(target=worker_loop, name="quote-miss-jobs", daemon=True)
    thread.start()
    log.info("quote miss worker thread started")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Worker de scrape on-miss para cotizaciones")
    parser.add_argument("--once", action="store_true", help="Procesa un lote y sale")
    parser.add_argument("--limit", type=int, default=BATCH_SIZE)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from retail.search import connect_repo

    if args.once:
        repo = connect_repo()
        if repo is None:
            print("Sin Mongo", flush=True)
            return 1
        try:
            ensure_indexes(repo)
            n = run_once(repo, limit=max(1, args.limit))
            print(f"processed={n}", flush=True)
        finally:
            repo.close()
        return 0
    worker_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
