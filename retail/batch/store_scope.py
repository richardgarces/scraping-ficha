"""Consultas de catálogo acotadas a una sola tienda.

El cron por grupo recorre muchas tiendas. Este módulo elige las mismas
consultas que aplicarían al grupo (o grupos) de una tienda, más las hojas del
árbol `categories` si esa tienda ya tiene uno, y deja el scrape en ese store_id.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.registry import GROUP_ORDER, group_of, list_stores
from retail.store_categories import filter_products_for_group, list_store_categories

logger = logging.getLogger(__name__)

# Una corrida en "running" sin avance no debe bloquear el botón para siempre.
STALE_AFTER = timedelta(hours=36)


class StoreBatchBusy(Exception):
    def __init__(self, store_id: str, title: str | None = None) -> None:
        self.store_id = store_id
        self.title = title or store_id
        super().__init__(f"Ya hay un scraping de {self.title} en curso.")


class StoreBatchIdle(RuntimeError):
    def __init__(self, store_id: str, title: str | None = None) -> None:
        self.store_id = store_id
        self.title = title or store_id
        super().__init__(f"No hay un scraping de {self.title} en curso.")


class StoreBatchNothingToResume(ValueError):
    def __init__(self, store_id: str, title: str | None = None) -> None:
        self.store_id = store_id
        self.title = title or store_id
        super().__init__(f"No hay progreso guardado para continuar {self.title}. Usa reiniciar.")


def store_cursor_key(store_id: str) -> str:
    return f"batch_cursor:tienda:{normalize_store(store_id)}"


def normalize_store(store_id: str | None) -> str:
    key = (store_id or "").strip().lower()
    if not key:
        raise ValueError("Indica una tienda.")
    known = {spec.id for spec in list_stores()}
    if key not in known:
        raise ValueError(f"Tienda desconocida: {store_id}.")
    return key


def store_title(store_id: str) -> str:
    key = store_id.strip().lower()
    for spec in list_stores():
        if spec.id == key:
            return spec.title
    return key


def groups_for_store(store_id: str, *, repo: Any | None = None) -> list[str]:
    """Grupos de `store_categories` que incluyen esta tienda (si no, el del registry)."""
    key = normalize_store(store_id)
    wanted: set[str] = set()
    for row in list_store_categories(repo=repo):
        ids = {str(item).strip().lower() for item in (row.get("store_ids") or []) if item}
        gid = str(row.get("id") or "").strip().lower()
        if gid and key in ids:
            wanted.add(gid)
    ordered = [gid for gid in GROUP_ORDER if gid in wanted]
    extras = sorted(wanted - set(ordered))
    found = ordered + extras
    if found:
        return found
    return [group_of(key)[0]]


def category_catalog_items(store_id: str, *, repo: Any | None = None) -> list[dict[str, Any]]:
    """Hojas del árbol `categories` de esa tienda, si el proyecto ya lo cargó."""
    key = store_id.strip().lower()
    close = False
    local = repo
    if local is None:
        local = _connect()
        close = local is not None
    try:
        finder = getattr(local, "category_search_items", None) if local is not None else None
        if finder is None:
            return []
        rows = finder(key) or []
        return [item for item in rows if str(item.get("query") or "").strip()]
    except Exception:
        logger.debug("No se pudo leer el árbol de categorías de %s", key, exc_info=True)
        return []
    finally:
        if close and local is not None:
            try:
                local.close()
            except Exception:
                pass


def products_for_store(
    products: list[dict[str, Any]],
    store_id: str,
    *,
    repo: Any | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Consultas del índice/catálogo de los grupos de la tienda, más su árbol si existe."""
    key = normalize_store(store_id)
    groups = groups_for_store(key, repo=repo)
    kept: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_queries: set[str] = set()
    for group in groups:
        for item in filter_products_for_group(products, group, repo=repo):
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            ident = str(item.get("id") or "").strip().lower()
            folded = query.casefold()
            if ident and ident in seen_ids:
                continue
            if folded in seen_queries:
                continue
            if ident:
                seen_ids.add(ident)
            seen_queries.add(folded)
            kept.append(item)
    for item in category_catalog_items(key, repo=repo):
        query = str(item.get("query") or "").strip()
        folded = query.casefold()
        if not folded or folded in seen_queries:
            continue
        seen_queries.add(folded)
        kept.append(item)
    return groups, kept


def store_batch_is_busy(repo: Any | None, store_id: str) -> bool:
    """True si hay una corrida running reciente de esa tienda. Las viejas se marcan fallidas."""
    if repo is None or not hasattr(repo, "find_running_store_batch"):
        return False
    doc = repo.find_running_store_batch(store_id)
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


def ensure_store_batch_available(repo: Any | None, store_id: str) -> None:
    if store_batch_is_busy(repo, store_id):
        raise StoreBatchBusy(store_id, store_title(store_id))


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
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _connect():
    try:
        from retail.search import connect_repo

        return connect_repo()
    except Exception:
        return None
