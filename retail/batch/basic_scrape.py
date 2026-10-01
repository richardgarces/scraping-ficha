"""Scraping básico: recorre productos ya guardados en Mongo, no la semilla genérica.

Por cada documento resuelve la categoría (grupo de tiendas) y busca esa consulta
solo en las tiendas del grupo. Los resultados pasan por `persist_search` /
`upsert_offers` (store + product_id): inserta los nuevos y actualiza el precio
de los que ya existen. No usa la clave `grupo` ni `tienda` de los crons.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from retail.batch.store_scope import STALE_AFTER, _parse_when
from retail.registry import GROUP_TITLES, STORE_GROUP, list_stores
from retail.search import SEARCH_TIMEOUT, search_products

logger = logging.getLogger(__name__)

JOB_KEY = "scraping_basico"
SCOPE = "basico"

_GROUP_FIELDS = ("batch_grupo", "catalog_group", "group", "grupo")
_QUERY_FIELDS = ("last_search_query", "catalog_query", "query", "name")
_TITLE_TO_GROUP = {title.casefold(): key for key, title in GROUP_TITLES.items()}


class BasicScrapeBusy(Exception):
    def __init__(self) -> None:
        super().__init__("Ya hay un scraping básico en curso.")


class BasicScrapeNothingToResume(ValueError):
    def __init__(self) -> None:
        super().__init__("No hay progreso guardado para continuar el scraping básico. Usa reiniciar.")


def resolve_basic_resume_after(repo: Any, run: dict[str, Any] | None) -> Any:
    """Punto de reanudación: cursor guardado, resume_after_id de la corrida, o offset."""
    if hasattr(repo, "basic_scrape_cursor"):
        saved = repo.basic_scrape_cursor()
        if saved:
            return saved
    if run:
        after = run.get("resume_after_id")
        if after:
            return after
        processed = int(run.get("processed") or 0)
        if processed > 0 and hasattr(repo, "product_id_at_offset"):
            found = repo.product_id_at_offset(processed - 1)
            if found is not None:
                return found
    raise BasicScrapeNothingToResume()


def product_query(doc: dict[str, Any]) -> str:
    """Términos de búsqueda del documento, o el nombre si no hay consulta guardada."""
    for key in _QUERY_FIELDS:
        text = str(doc.get(key) or "").strip()
        if text:
            return text
    return ""


def _known_group(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    key = text.lower()
    if key == "otros":
        return None
    if key in GROUP_TITLES:
        return key
    found = _TITLE_TO_GROUP.get(text.casefold())
    if found == "otros":
        return None
    return found


def _explicit_groups(doc: dict[str, Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        key = _known_group(value)
        if key and key not in seen:
            seen.add(key)
            found.append(key)

    for field in _GROUP_FIELDS:
        add(doc.get(field))
    raw_groups = doc.get("groups")
    if isinstance(raw_groups, str):
        add(raw_groups)
    elif isinstance(raw_groups, (list, tuple)):
        for item in raw_groups:
            add(item)
    for field in ("catalog_category", "category"):
        add(doc.get(field))
    return found


def groups_for_product(doc: dict[str, Any], *, resolve_fn: Any | None = None) -> list[str]:
    """Grupo(s) de tiendas del producto. Vacío si no se puede resolver.

    Orden: campos del documento, `product_index.resolve` del nombre/consulta,
    y si no hay match el grupo del registry de la tienda donde ya está guardado.
    No usa el fallback de «sin genérico» (eso abriría retail+tecnología).
    """
    explicit = _explicit_groups(doc)
    if explicit:
        return explicit

    resolver = resolve_fn
    if resolver is None:
        from retail.index.products import resolve as resolver

    seen: list[str] = []
    tried: set[str] = set()
    for raw in (product_query(doc), str(doc.get("name") or "").strip()):
        text = raw.strip()
        folded = text.casefold()
        if not text or folded in tried:
            continue
        tried.add(folded)
        try:
            found = resolver(text)
        except Exception:
            logger.debug("No se pudo resolver la categoría de %s", text, exc_info=True)
            continue
        groups = getattr(found, "groups", None) if found is not None else None
        for item in groups or ():
            key = _known_group(item)
            if key and key not in seen:
                seen.append(key)
        if seen:
            return seen

    store = str(doc.get("store") or "").strip().lower()
    store_group = _known_group(STORE_GROUP.get(store))
    if store_group:
        return [store_group]
    return []


def stores_for_groups(groups: list[str], *, repo: Any | None = None) -> list[str]:
    """Tiendas de esos grupos, en el orden del registry. Nunca el catálogo completo."""
    from retail.store_categories import stores_for_group

    wanted: list[str] = []
    seen: set[str] = set()
    for group in groups:
        try:
            ids = stores_for_group(group, repo=repo)
        except Exception:
            logger.info("Scraping básico: grupo desconocido %s", group, exc_info=True)
            continue
        for store_id in ids:
            if store_id and store_id not in seen:
                seen.add(store_id)
                wanted.append(store_id)
    available = [spec.id for spec in list_stores()]
    if not wanted or (available and set(wanted) >= set(available) and len(available) > 1):
        return []
    return wanted


def basic_scrape_is_busy(repo: Any | None) -> bool:
    """True si hay una corrida `scraping_basico` reciente. Las viejas se marcan fallidas."""
    if repo is None or not hasattr(repo, "find_running_basic_scrape"):
        return False
    doc = repo.find_running_basic_scrape()
    if not doc:
        return False
    started = _parse_when(doc.get("started_at"))
    if started is not None and datetime.now(timezone.utc) - started > STALE_AFTER:
        run_id = str(doc.get("_id") or doc.get("id") or "")
        if run_id and hasattr(repo, "finish_batch_run"):
            repo.finish_batch_run(
                run_id,
                status="failed",
                phase="failed",
                last_error="Corrida interrumpida; se marcó como fallida para poder reanudar.",
            )
        return False
    return True


def run_basic_scrape(
    *,
    products: list[dict[str, Any]] | None = None,
    repo: Any | None = None,
    source: str = "scrape",
    max_items: int = 6,
    delay: float = 1.0,
    pause: float = 2.0,
    limit: int | None = None,
    persist: bool = True,
    resolve_fn: Any | None = None,
    after_id: Any | None = None,
    resume_mode: str | None = None,
    prior_progress: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recorre productos guardados y scrapea el grupo de cada uno. No bloquea el request."""
    close = False
    if repo is None:
        from retail.search import connect_repo

        repo = connect_repo()
        close = repo is not None
    if repo is None:
        raise RuntimeError("MongoDB no está disponible; el scraping básico no puede guardar productos.")
    if source not in {"scrape", "both"}:
        source = "scrape"

    owns_list = products is not None
    stream = list(products or [])
    prior = dict(prior_progress or {})
    prior_processed = int(prior.get("processed") or 0)
    if not owns_list:
        total = int(repo.count() or 0)
        if limit is not None:
            total = min(total, int(limit))
    else:
        if limit is not None:
            stream = stream[: int(limit)]
        total = len(stream)

    if basic_scrape_is_busy(repo):
        raise BasicScrapeBusy()

    started_at = datetime.now(timezone.utc).isoformat()
    run_doc = {
        "started_at": started_at,
        "catalog": "Scraping básico",
        "items": total,
        "source": source,
        "persist": persist,
        "phase": "products",
        "job": JOB_KEY,
        "scope": SCOPE,
        "skipped": 0,
        "resume_mode": resume_mode or "schedule",
        "resume_after_id": str(after_id) if after_id is not None else None,
    }
    run_id = repo.start_batch_run(run_doc)
    if prior_processed or prior.get("saved_upserted") or prior.get("saved_modified") or prior.get("skipped"):
        repo.update_batch_run(
            run_id,
            processed=prior_processed,
            saved_upserted=int(prior.get("saved_upserted") or 0),
            saved_modified=int(prior.get("saved_modified") or 0),
            skipped=int(prior.get("skipped") or 0),
            failed=int(prior.get("failed") or 0),
            resume_after_id=str(after_id) if after_id is not None else None,
        )
    summary: dict[str, Any] = {
        "started_at": started_at,
        "batch_run_id": run_id,
        "job": JOB_KEY,
        "scope": SCOPE,
        "items": total,
        "processed": prior_processed,
        "skipped": int(prior.get("skipped") or 0),
        "failed": int(prior.get("failed") or 0),
        "saved_upserted": int(prior.get("saved_upserted") or 0),
        "saved_modified": int(prior.get("saved_modified") or 0),
        "resume_after_id": str(after_id) if after_id is not None else None,
    }
    seen: set[tuple[str, tuple[str, ...]]] = set()
    walked = 0
    try:
        iterator: Any
        if owns_list:
            iterator = stream
        else:
            iterator = repo.iter_stored_products(after_id=after_id)
        for doc in iterator:
            from retail.batch.config import wait_while_paused

            wait_while_paused(repo, run_id)
            if limit is not None and walked >= int(limit):
                break
            walked += 1
            mongo_id = doc.get("_id")
            label = _label(doc)
            query = product_query(doc)
            groups = groups_for_product(doc, resolve_fn=resolve_fn) if query else []
            if mongo_id is not None and hasattr(repo, "set_basic_scrape_cursor"):
                repo.set_basic_scrape_cursor(mongo_id)
            if not query or not groups:
                logger.info("Scraping básico: sin categoría, se omite %s", label)
                summary["skipped"] += 1
                summary["processed"] += 1
                repo.advance_batch_run(run_id, processed=1, skipped=1)
                if mongo_id is not None:
                    repo.update_batch_run(run_id, resume_after_id=str(mongo_id))
                continue
            stores = stores_for_groups(groups, repo=repo)
            if not stores:
                logger.info(
                    "Scraping básico: sin tiendas para %s (%s), se omite",
                    label,
                    ", ".join(groups),
                )
                summary["skipped"] += 1
                summary["processed"] += 1
                repo.advance_batch_run(run_id, processed=1, skipped=1)
                if mongo_id is not None:
                    repo.update_batch_run(run_id, resume_after_id=str(mongo_id))
                continue
            key = (query.casefold(), tuple(groups))
            if key in seen:
                summary["processed"] += 1
                repo.advance_batch_run(run_id, processed=1)
                if mongo_id is not None:
                    repo.update_batch_run(run_id, resume_after_id=str(mongo_id))
                continue
            seen.add(key)
            repo.update_batch_run(
                run_id,
                phase="products",
                current_query=query,
                current_id=str(doc.get("product_id") or ""),
                current_index=walked - 1,
                stores_total=len(stores),
                resume_after_id=str(mongo_id) if mongo_id is not None else None,
            )
            print(f"[básico {walked}/{total or '?'}] {query} · {', '.join(groups)} · {len(stores)} tiendas")
            try:
                result = search_products(
                    query,
                    source=source,
                    stores=stores,
                    max_items=max_items,
                    delay=delay,
                    timeout=SEARCH_TIMEOUT,
                    persist=persist,
                    fresh=True,
                    persist_meta={
                        "catalog_query": query,
                        "catalog_category": groups[0],
                        "basic_scrape": True,
                        "last_batch_run": run_id,
                        "last_batch_at": started_at,
                    },
                )
            except Exception as exc:
                logger.warning("Scraping básico: falló %s: %s", label, exc)
                summary["failed"] += 1
                summary["processed"] += 1
                repo.advance_batch_run(run_id, processed=1, failed=1, error=str(exc))
                continue
            saved = result.get("saved") or {}
            if persist and not saved:
                saved = repo.persist_search(
                    query,
                    result.get("groups") or [],
                    source=source,
                    store_errors=result.get("store_errors") or [],
                    extra={
                        "catalog_query": query,
                        "catalog_category": groups[0],
                        "basic_scrape": True,
                        "last_batch_run": run_id,
                        "last_batch_at": started_at,
                    },
                )
            upserted = int(saved.get("upserted") or 0)
            modified = int(saved.get("modified") or 0)
            summary["saved_upserted"] += upserted
            summary["saved_modified"] += modified
            summary["processed"] += 1
            repo.advance_batch_run(run_id, processed=1, upserted=upserted, modified=modified)
            if pause and walked < total:
                time.sleep(pause)
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        if hasattr(repo, "clear_basic_scrape_cursor"):
            repo.clear_basic_scrape_cursor()
        repo.finish_batch_run(
            run_id,
            status="done",
            phase="done",
            finished_at=summary["finished_at"],
            skipped=summary["skipped"],
            failed=summary["failed"],
        )
        return summary
    except Exception as exc:
        repo.finish_batch_run(
            run_id,
            status="failed",
            phase="failed",
            last_error=str(exc),
        )
        raise
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass


def _label(doc: dict[str, Any]) -> str:
    store = str(doc.get("store") or "sin tienda")
    ident = str(doc.get("product_id") or doc.get("sku_id") or doc.get("name") or "")
    return f"{store}/{ident}" if ident else store
