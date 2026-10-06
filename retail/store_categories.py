"""Categorías de tiendas (grupos) persistidas en Mongo.

Colección `store_categories`: id, title, store_ids, sort_order, updated_at.
Bootstrap desde `GROUP_TITLES` / `STORE_GROUP` del registry; no pisa datos
enriquecidos. El batch por grupo y los crons leen de aquí (fallback registry).
"""

from __future__ import annotations

import logging
from typing import Any

from retail.registry import GROUP_ORDER, GROUP_TITLES, STORE_GROUP, list_stores

logger = logging.getLogger(__name__)


def registry_payloads() -> list[dict[str, Any]]:
    """Documentos de arranque: un grupo del registry con sus tiendas conocidas."""
    by_group: dict[str, list[str]] = {key: [] for key in GROUP_ORDER}
    for store_id, group in STORE_GROUP.items():
        key = (group or "otros").lower()
        if key not in by_group:
            key = "otros"
        by_group.setdefault(key, []).append(store_id)
    rows = []
    for index, group_id in enumerate(GROUP_ORDER):
        stores = sorted(set(by_group.get(group_id) or []))
        rows.append(
            {
                "id": group_id,
                "title": GROUP_TITLES[group_id],
                "store_ids": stores,
                "sort_order": index,
            }
        )
    return rows


def normalize_group(group_id: str | None, *, repo: Any | None = None) -> str:
    key = (group_id or "").strip().lower()
    if not key:
        raise ValueError("Indica un grupo de tiendas, por ejemplo tecnologia.")
    if key in GROUP_TITLES:
        return key
    from retail.cyber_day import CYBER_GROUP_ID, is_cyber_group

    if is_cyber_group(key):
        return CYBER_GROUP_ID
    close = False
    local = repo
    if local is None:
        local = _connect()
        close = local is not None
    try:
        if local is not None:
            ensure_store_categories(repo=local)
            if local.get_store_category(key):
                return key
    except Exception:
        logger.debug("No se pudo validar grupo %s en Mongo", key, exc_info=True)
    finally:
        if close and local is not None:
            try:
                local.close()
            except Exception:
                pass
    available = ", ".join((*GROUP_ORDER, CYBER_GROUP_ID))
    raise ValueError(f"Grupo desconocido: {group_id}. Disponibles: {available}")


def list_store_categories(*, repo: Any | None = None) -> list[dict[str, Any]]:
    """Mongo primero; registry si Mongo está vacío o caído."""
    close = False
    if repo is None:
        repo = _connect()
        close = repo is not None
    try:
        if repo is not None:
            ensure_store_categories(repo=repo)
            rows = repo.load_store_categories()
            if rows:
                return [_public_row(item) for item in rows]
    except Exception:
        logger.debug("store_categories Mongo no disponible; se usa el registry", exc_info=True)
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
    return [_public_row(item) for item in registry_payloads()]


def ensure_store_categories(*, repo: Any | None = None) -> dict[str, Any]:
    """Sincroniza ids nuevos del registry sin pisar títulos ni store_ids extras."""
    close = False
    if repo is None:
        repo = _connect()
        close = repo is not None
    try:
        if repo is None:
            return {"source": "registry", "count": len(GROUP_ORDER), "upserted": 0}
        upserted = repo.sync_store_categories(registry_payloads())
        try:
            from retail.cyber_day import ensure_cyber_category

            ensure_cyber_category(repo)
        except Exception:
            logger.debug("No se pudo registrar cyber_junio2026", exc_info=True)
        rows = repo.load_store_categories()
        return {"source": "mongo", "count": len(rows), "upserted": upserted}
    except Exception as exc:
        logger.debug("No se pudo sincronizar store_categories: %s", exc, exc_info=True)
        return {"source": "registry", "count": len(GROUP_ORDER), "upserted": 0, "error": str(exc)}
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass


def stores_for_group(group_id: str, *, repo: Any | None = None) -> list[str]:
    """Tiendas registradas del grupo, en el orden de `list_stores()`."""
    key = normalize_group(group_id)
    available = [spec.id for spec in list_stores()]
    wanted = set(_store_ids_for(key, repo=repo))
    return [store_id for store_id in available if store_id in wanted]


def group_titles() -> dict[str, str]:
    return {item["id"]: item["title"] for item in list_store_categories()}


def enabled_group_ids(schedule: dict[str, Any] | None = None) -> list[str]:
    """Grupos a programar en cron: lista de programacion.json o todos los de Mongo/registry."""
    all_ids = [item["id"] for item in list_store_categories()]
    block = (schedule or {}).get("groups") or {}
    selected = block.get("enabled")
    if selected is None:
        return all_ids
    wanted = {str(item).strip().lower() for item in selected if str(item).strip()}
    return [item for item in all_ids if item in wanted]


def filter_products_for_group(
    products: list[dict[str, Any]],
    group_id: str,
    *,
    repo: Any | None = None,
) -> list[dict[str, Any]]:
    """Deja ítems del catálogo cuya consulta resuelve a un genérico con ese grupo.

    Usa `product_index_seed.groups` (vía resolve / ids en Mongo). Sin match,
    mismo fallback que el índice (retail+tecnología; +farmacias si parece médico).
    """
    from retail.index.products import resolve, unmatched_fallback_groups

    key = normalize_group(group_id)
    seed_ids: set[str] | None = None
    close = False
    local_repo = repo
    if local_repo is None:
        local_repo = _connect()
        close = local_repo is not None
    try:
        if local_repo is not None:
            seed_ids = local_repo.product_seed_ids_for_group(key)
        group_stores = set(_store_ids_for(key, repo=local_repo))
    except Exception:
        seed_ids = None
        group_stores = set(_store_ids_for(key))
    finally:
        if close and local_repo is not None:
            try:
                local_repo.close()
            except Exception:
                pass

    from retail.batch.catalog import catalog_origin_store

    kept: list[dict[str, Any]] = []
    for item in products:
        query = str(item.get("query") or "").strip()
        if not query:
            continue
        origin = catalog_origin_store(item)
        if origin:
            # Las consultas importadas desde una tienda pertenecen al grupo de
            # esa tienda. Resolverlas por palabras las multiplicaba en grupos
            # ajenos y convertía 53 mil productos en cientos de miles de tareas.
            if origin in group_stores:
                kept.append(item)
            continue
        found = resolve(query)
        if found is not None:
            if key in found.groups or (seed_ids and found.id in seed_ids):
                kept.append(item)
            continue
        if key in unmatched_fallback_groups(query):
            kept.append(item)
    return kept


def _store_ids_for(group_id: str, *, repo: Any | None = None) -> list[str]:
    close = False
    if repo is None:
        repo = _connect()
        close = repo is not None
    try:
        if repo is not None:
            ensure_store_categories(repo=repo)
            row = repo.get_store_category(group_id)
            if row and row.get("store_ids"):
                return [str(item) for item in row["store_ids"]]
    except Exception:
        logger.debug("No se pudo leer store_category %s", group_id, exc_info=True)
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
    return [
        store_id
        for store_id, group in STORE_GROUP.items()
        if (group or "otros").lower() == group_id
    ]


def _public_row(item: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": str(item.get("id") or "").strip().lower(),
        "title": str(item.get("title") or item.get("id") or "").strip(),
        "store_ids": [str(store) for store in (item.get("store_ids") or []) if store],
        "sort_order": int(item.get("sort_order") if item.get("sort_order") is not None else 999),
    }
    if item.get("query_list") or item.get("kind") == "query_list":
        row["query_list"] = True
        row["kind"] = "query_list"
        row["list_id"] = str(item.get("list_id") or row["id"])
    return row


def _connect():
    try:
        from retail.search import connect_repo

        return connect_repo()
    except Exception:
        return None
