from __future__ import annotations

import os
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retail.batch.alerts import (
    bind_user_chats,
    deduplicate_product_alerts,
    dispatch_alerts,
    dispatch_user_alerts,
)
from retail.batch.group_scope import GroupBatchStopped
from retail.batch.catalog import (
    active_products,
    catalog_origin_store,
    default_catalog_path,
    default_rules_path,
    load_catalog,
)
from retail.batch.rules import Alert, detect_offers, load_rules, notification_offers, watch_alerts
from retail.search import search_products


def refresh_product_index() -> dict[str, Any]:
    """Reescribe Redis `retail:pindex:` desde la semilla Mongo (o JSON si Mongo está vacío)."""
    try:
        from retail.index.products import ensure_loaded

        return ensure_loaded(force=True)
    except Exception as exc:
        return {"error": str(exc)}


def refresh_store_categories() -> dict[str, Any]:
    """Upsert de grupos de tiendas en Mongo desde el registry (sin pisar enriquecidos)."""
    try:
        from retail.store_categories import ensure_store_categories

        return ensure_store_categories()
    except Exception as exc:
        return {"error": str(exc)}


def run_batch(
    *,
    catalog_path: Path | None = None,
    rules_path: Path | None = None,
    source: str = "both",
    max_items: int = 6,
    delay: float = 1.0,
    pause: float = 2.0,
    limit: int | None = None,
    ids: list[str] | None = None,
    grupo: str | None = None,
    tienda: str | None = None,
    dry_run: bool = False,
    persist: bool = True,
    time_budget_minutes: float | None = None,
    batch_run_id: str | None = None,
) -> dict[str, Any]:
    if batch_run_id and dry_run:
        raise ValueError("Una corrida reservada no admite dry-run.")
    if batch_run_id and not grupo and not tienda:
        raise ValueError("La reserva requiere un grupo o una tienda.")
    if batch_run_id and grupo and tienda:
        raise ValueError("Usa una tienda o un grupo, no ambos.")
    if tienda and grupo:
        raise ValueError("Usa una tienda o un grupo, no ambos.")

    # Activa la reserva antes de cargar el catálogo: ese paso puede tardar
    # minutos y, si no, el panel muestra «en curso» sin progreso real.
    run_id = None
    repo = None
    early_repo = False
    if batch_run_id and not dry_run:
        from retail.search import connect_repo

        repo = connect_repo()
        early_repo = repo is not None
        if persist and repo is None:
            raise RuntimeError("MongoDB no está disponible; el batch no puede guardar productos.")
        if repo is not None:
            try:
                if tienda:
                    from retail.batch.store_scope import normalize_store

                    store_key = normalize_store(tienda)
                    repo.activate_store_batch_run(
                        batch_run_id,
                        store_key,
                        {
                            "phase": "index",
                            "tienda": store_key,
                            "scope": "tienda",
                            "stores": [store_key],
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                elif grupo:
                    from retail.store_categories import normalize_group

                    group_key = normalize_group(grupo, repo=repo)
                    repo.activate_group_batch_run(
                        batch_run_id,
                        group_key,
                        {
                            "phase": "index",
                            "grupo": group_key,
                            "scope": "grupo",
                            "started_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
            except GroupBatchStopped:
                repo.finish_batch_run(batch_run_id, status="stopped", phase="stopped")
                if early_repo:
                    try:
                        repo.close()
                    except Exception:
                        pass
                return {
                    "started_at": datetime.now(timezone.utc).isoformat(),
                    "batch_run_id": batch_run_id,
                    "stopped": True,
                    "items": 0,
                    "searches": [],
                    "alerts": [],
                    "alert_count": 0,
                }
            run_id = batch_run_id

    catalog = load_catalog(catalog_path or default_catalog_path())
    rules = load_rules(rules_path or default_rules_path())
    products = active_products(catalog)
    if ids:
        allowed = {item.lower() for item in ids}
        products = [item for item in products if str(item.get("id") or "").lower() in allowed]

    stores = catalog.get("default_stores")
    group_key = None
    store_key = None
    group_keys: list[str] = []
    store_title = None
    store_categories_meta: dict[str, Any] | None = None
    if tienda:
        from retail.batch.store_scope import (
            groups_for_store,
            normalize_store,
            products_for_store,
            store_title as title_of,
        )

        store_key = normalize_store(tienda)
        store_title = title_of(store_key)
        store_categories_meta = refresh_store_categories()
        group_keys, products = products_for_store(products, store_key)
        # Solo esta tienda: nunca el resto del grupo.
        stores = [store_key]
        if not group_keys:
            group_keys = groups_for_store(store_key)
        if not products:
            raise ValueError(f"No hay consultas de catálogo para la tienda «{store_title}».")
    elif grupo:
        from retail.store_categories import (
            filter_products_for_group,
            normalize_group,
            stores_for_group,
        )

        store_categories_meta = refresh_store_categories()
        group_key = normalize_group(grupo)
        stores = stores_for_group(group_key)
        products = filter_products_for_group(products, group_key)
        if not stores:
            raise ValueError(f"El grupo «{group_key}» no tiene tiendas registradas.")

    summary: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "catalog": catalog.get("title"),
        "items": len(products),
        "dry_run": dry_run,
        "searches": [],
        "alerts": [],
    }
    if store_key:
        summary["tienda"] = store_key
        summary["tienda_title"] = store_title
        summary["groups"] = list(group_keys)
        summary["stores"] = [store_key]
        summary["scope"] = "tienda"
        if store_categories_meta:
            summary["store_categories"] = store_categories_meta
    elif group_key:
        summary["grupo"] = group_key
        summary["stores"] = list(stores or [])
        summary["scope"] = "grupo"
        if store_categories_meta:
            summary["store_categories"] = store_categories_meta
    if dry_run:
        if limit is not None:
            products = products[:limit]
            summary["items"] = len(products)
        summary["searches"] = [{"id": item.get("id"), "query": item.get("query")} for item in products]
        return summary

    if repo is None:
        from retail.search import connect_repo

        repo = connect_repo()
    if persist and repo is None:
        raise RuntimeError("MongoDB no está disponible; el batch no puede guardar productos.")
    adaptive_meta: dict[str, Any] = {"enabled": False, "reason": "Se usa el orden completo del catálogo."}
    adaptive_requested = os.environ.get("ADAPTIVE_SCRAPING", "1").strip().lower() not in {"0", "false", "no"}
    if repo is not None and group_key and not ids and adaptive_requested:
        try:
            from retail.batch.adaptive import plan_catalog_products
            from retail.predictive_alerts import predictive_validation_status

            validation = predictive_validation_status(repo)
            catalog_ids = [str(item.get("id") or "") for item in products if item.get("id")]
            priorities = list(repo.scrape_priorities.find({"catalog_id": {"$in": catalog_ids}}, {"_id": 0}))
            products, adaptive_meta = plan_catalog_products(products, priorities)
            adaptive_meta["timesfm_enabled"] = bool(validation["enabled"])
            if adaptive_meta.get("enabled") and not validation["enabled"]:
                adaptive_meta["reason"] = (
                    f"{adaptive_meta['reason']} Se usa el historial comprobado; TimesFM todavía no interviene."
                )
        except Exception as exc:
            adaptive_meta = {
                "enabled": False,
                "reason": f"No se pudo leer el plan adaptativo; se usa el catálogo completo ({exc}).",
            }
    if limit is not None:
        products = products[:limit]
    # Los catálogos importados suelen venir en bloques enormes por tienda. Al
    # intercalarlos podemos consultar dos tiendas distintas a la vez sin hacer
    # dos peticiones simultáneas al mismo comercio.
    if group_key and not ids:
        products = _interleave_products_by_origin(products)
    cursor_key = f"batch_cursor:{group_key}" if group_key and not ids and limit is None else None
    if repo is not None and cursor_key and hasattr(repo, "get_app_setting"):
        cursor = repo.get_app_setting(cursor_key) or {}
        products = _rotate_products(products, str(cursor.get("next_id") or ""))
    summary["items"] = len(products)
    summary["adaptive_scraping"] = adaptive_meta
    if repo is not None:
        if store_key and not batch_run_id:
            from retail.batch.store_scope import ensure_store_batch_available

            ensure_store_batch_available(repo, store_key)
        run_doc: dict[str, Any] = {
            "started_at": summary["started_at"],
            "catalog": catalog.get("title"),
            "items": len(products),
            "source": source,
            "persist": persist,
            "phase": "index",
            "adaptive_scraping": adaptive_meta,
        }
        if store_key:
            # Sin `grupo`: la agregación de crons no debe tomar esta corrida.
            run_doc.update(
                {
                    "tienda": store_key,
                    "groups": list(group_keys),
                    "stores": [store_key],
                    "scope": "tienda",
                }
            )
        elif group_key:
            run_doc.update(
                {
                    "grupo": group_key,
                    "stores": list(stores or []),
                    "scope": "grupo",
                }
            )
        try:
            if batch_run_id and run_id:
                # Ya activada al inicio; solo completa ítems y meta del catálogo.
                repo.update_batch_run(run_id, **run_doc)
            elif batch_run_id and store_key:
                repo.activate_store_batch_run(batch_run_id, store_key, run_doc)
                run_id = batch_run_id
            elif batch_run_id and group_key:
                repo.activate_group_batch_run(batch_run_id, group_key, run_doc)
                run_id = batch_run_id
            else:
                run_id = repo.start_batch_run(run_doc)
        except Exception:
            if early_repo and repo is not None:
                try:
                    repo.close()
                except Exception:
                    pass
            raise
        summary["batch_run_id"] = run_id
    # El host renueva el índice una vez al día. Rehacerlo para cada uno de los
    # grupos era trabajo duplicado y retenía el inicio de todos los lotes.
    refresh_index = not group_key or os.environ.get("BATCH_REFRESH_INDEX", "0").strip().lower() in {"1", "true", "yes"}
    index_meta = refresh_product_index() if refresh_index else {"skipped": True, "reason": "renovado por el cron diario"}
    if index_meta:
        summary["product_index"] = index_meta
        if index_meta.get("skipped"):
            print("Índice de productos: se conserva el índice renovado por el cron diario.")
        elif index_meta.get("error"):
            print(f"Índice de productos: no se pudo renovar Redis ({index_meta['error']})")
            if repo is not None and run_id:
                repo.update_batch_run(run_id, last_error=f"índice: {index_meta['error']}")
        else:
            origen = "Mongo" if index_meta.get("source") == "mongo" else "JSON"
            print(
                f"Índice de productos: {index_meta.get('count') or 0} genéricos en "
                f"{index_meta.get('backend') or 'memoria'} desde {origen}."
            )
    if store_key:
        grupos = ", ".join(group_keys) or "sin grupo"
        print(f"Tienda {store_title or store_key} ({grupos}): 1 tienda · {len(products)} consultas")
    elif group_key:
        print(f"Grupo {group_key}: {len(stores or [])} tiendas · {len(products)} productos del catálogo")

    if repo is not None and group_key == "autos" and not ids:
        from retail.batch.auto_inventory import refresh_auto_inventory

        print("Autos: descubriendo inventario nuevo y usado por categorías…")
        if run_id:
            repo.update_batch_run(run_id, phase="auto_inventory")
        summary["auto_inventory"] = refresh_auto_inventory(repo, delay=delay)
        if run_id:
            repo.update_batch_run(run_id, auto_inventory=summary["auto_inventory"])

    channels = list(rules.get("channels") or ["log", "file"])
    notification_users = (
        repo.list_notification_users()
        if repo is not None and hasattr(repo, "list_notification_users")
        else []
    )
    if repo is not None:
        # Evita que el mismo chat reciba el aviso global y, enseguida, su aviso personal.
        bind_user_chats(repo, notification_users)
    # Cada oferta se despacha individualmente, incluyendo sus canales push.
    por_alerta = channels
    budget = time_budget_minutes
    if budget is None and group_key:
        budget = float(os.environ.get("BATCH_TIME_BUDGET_MINUTES", "90") or 90)
    deadline = time.monotonic() + max(1.0, float(budget)) * 60 if budget else None
    error_streaks: dict[str, int] = {}
    suspended_stores: set[str] = set()
    error_threshold = max(1, int(os.environ.get("BATCH_STORE_ERROR_THRESHOLD", "3") or 3))
    next_index = 0
    budget_exhausted = False
    batch_clock = time.monotonic()
    executed_searches = 0
    product_workers = 1
    if group_key:
        product_workers = max(1, min(4, int(os.environ.get("BATCH_PRODUCT_WORKERS", "2") or 2)))
    summary["product_workers"] = product_workers
    prepared_searches: dict[int, dict[str, Any]] = {}
    product_executor: ThreadPoolExecutor | None = None
    try:
        # Los seguidos solo en la corrida completa: con un cron por grupo
        # dispararían N veces el mismo aviso.
        if group_key is None and store_key is None:
            if repo is not None and run_id:
                repo.update_batch_run(run_id, phase="watches")
            summary["watch_alerts"] = _check_watches(
                repo,
                channels,
                run=run_id or summary["started_at"],
                source=source,
                stores=stores,
                max_items=max_items,
                delay=delay,
                pause=pause,
                persist=persist,
            )
        else:
            summary["watch_alerts"] = 0
        if repo is not None and run_id:
            repo.update_batch_run(run_id, phase="products")
        if product_workers > 1:
            product_executor = ThreadPoolExecutor(
                max_workers=product_workers,
                thread_name_prefix="batch-product",
            )
        for index, item in enumerate(products):
            next_index = index
            if deadline is not None and time.monotonic() >= deadline and index not in prepared_searches:
                budget_exhausted = True
                break
            if repo is not None:
                from retail.batch.config import wait_while_paused

                wait_while_paused(repo, run_id)
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            origin_store = catalog_origin_store(item)
            query_stores = [str(value) for value in (stores or []) if str(value) not in suspended_stores]
            # Una consulta importada ya representa un producto de una tienda.
            # Revisarla contra todas las tiendas multiplicaba el trabajo y
            # generaba coincidencias débiles. Las comparaciones se construyen
            # con los productos de origen que cada tienda actualiza por separado.
            if group_key and origin_store and origin_store in query_stores:
                query_stores = [origin_store]
            if not query_stores:
                row = {
                    "id": item.get("id"),
                    "query": query,
                    "skipped": True,
                    "warnings": ["Tienda suspendida temporalmente por errores repetidos."],
                }
                summary["searches"].append(row)
                if repo is not None and run_id:
                    repo.append_batch_search(run_id, row)
                next_index = index + 1
                continue
            print(f"[{index + 1}/{len(products)}] {item.get('id')}: {query}")
            if repo is not None and run_id:
                repo.update_batch_run(
                    run_id,
                    phase="products",
                    current_query=query,
                    current_id=item.get("id"),
                    current_index=index,
                )
                if group_key and hasattr(repo, "set_group_batch_cursor"):
                    repo.set_group_batch_cursor(group_key, item.get("id"))
            if index not in prepared_searches:
                jobs: list[tuple[int, dict[str, Any], str, list[str], str | None]] = [
                    (index, item, query, query_stores, origin_store)
                ]
                occupied_stores = set(query_stores)
                # La lista ya está intercalada por origen. Solo se amplía la
                # ola mientras las tiendas no se superpongan; una búsqueda
                # genérica que consulta varias tiendas queda sola.
                if product_executor is not None:
                    for next_job_index in range(index + 1, min(len(products), index + product_workers)):
                        next_item = products[next_job_index]
                        next_query = str(next_item.get("query") or "").strip()
                        if not next_query:
                            break
                        next_origin = catalog_origin_store(next_item)
                        next_stores = [
                            str(value)
                            for value in (stores or [])
                            if str(value) not in suspended_stores
                        ]
                        if group_key and next_origin and next_origin in next_stores:
                            next_stores = [next_origin]
                        if not next_stores or occupied_stores.intersection(next_stores):
                            break
                        occupied_stores.update(next_stores)
                        jobs.append((next_job_index, next_item, next_query, next_stores, next_origin))

                futures = []
                for job_index, job_item, job_query, job_stores, job_origin in jobs:
                    kwargs = _catalog_search_kwargs(
                        job_item,
                        stores=job_stores,
                        origin_store=job_origin,
                        source=source,
                        max_items=max_items,
                        delay=delay,
                        group_key=group_key,
                        store_key=store_key,
                        run_id=run_id,
                        started_at=summary["started_at"],
                    )
                    if product_executor is None:
                        prepared_searches[job_index] = _timed_catalog_search(job_query, kwargs)
                    else:
                        futures.append(
                            (job_index, product_executor.submit(_timed_catalog_search, job_query, kwargs))
                        )
                for job_index, future in futures:
                    prepared_searches[job_index] = future.result()
                for position, (job_index, *_rest) in enumerate(jobs):
                    prepared_searches[job_index]["wave_last"] = position == len(jobs) - 1

            prepared = prepared_searches.pop(index)
            try:
                if prepared.get("error") is not None:
                    raise prepared["error"]
                result = prepared["result"]
            except Exception as exc:
                for attempted in query_stores:
                    error_streaks[attempted] = error_streaks.get(attempted, 0) + 1
                    if error_streaks[attempted] >= error_threshold:
                        suspended_stores.add(attempted)
                executed_searches += 1
                row = {
                    "id": item.get("id"),
                    "query": query,
                    "stores": query_stores,
                    "duration_seconds": prepared["duration_seconds"],
                    "error": str(exc),
                }
                summary["searches"].append(row)
                if repo is not None and run_id:
                    repo.append_batch_search(run_id, row)
                continue
            failed_stores = {
                str(error.get("store") or "").strip()
                for error in (result.get("store_errors") or [])
                if error.get("store")
            }
            for attempted in query_stores:
                if attempted in failed_stores:
                    error_streaks[attempted] = error_streaks.get(attempted, 0) + 1
                    if error_streaks[attempted] >= error_threshold:
                        suspended_stores.add(attempted)
                else:
                    error_streaks[attempted] = 0
            executed_searches += 1
            persist_meta = {
                "catalog_id": item.get("id"),
                "catalog_query": query,
                "catalog_category": item.get("category"),
                "batch_grupo": group_key,
                "batch_tienda": store_key,
                "last_batch_run": run_id or summary["started_at"],
                "last_batch_at": summary["started_at"],
            }
            saved = result.get("saved")
            if persist and repo is not None and not saved:
                saved = repo.persist_search(
                    query,
                    result.get("groups") or [],
                    source=source,
                    store_errors=result.get("store_errors") or [],
                    extra=persist_meta,
                )
            personal_alerts = deduplicate_product_alerts(notification_offers(result, item)) if notification_users else []
            if group_key:
                for personal_alert in personal_alerts:
                    personal_alert.extra["notification_category"] = group_key
            alerts = deduplicate_product_alerts(detect_offers(result, item, rules))
            if repo is not None:
                alerts = [alert for alert in alerts if not repo.alert_exists(alert)]
                if alerts:
                    repo.save_alerts(alerts, run=run_id or summary["started_at"])
            if alerts:
                dispatch_alerts(alerts, por_alerta, repo=repo)
            if personal_alerts:
                dispatch_user_alerts(
                    personal_alerts, notification_users, repo=repo, system_channels=channels,
                )
            saved = result.get("saved") or {}
            row = {
                "id": item.get("id"),
                "query": query,
                "offers": result.get("offer_count"),
                "comparable": result.get("comparable_count"),
                "saved": saved,
                "alerts": len(alerts),
                "warnings": result.get("warnings") or [],
                "stores": query_stores,
                "duration_seconds": prepared["duration_seconds"],
            }
            print(
                f"    {row['offers'] or 0} ofertas · "
                f"Mongo +{saved.get('upserted') or 0} ~{saved.get('modified') or 0} · "
                f"{row['alerts']} alertas"
            )
            summary["searches"].append(row)
            summary["alerts"].extend(_alert_rows(alerts))
            if repo is not None and run_id:
                repo.append_batch_search(run_id, row)
            next_index = index + 1
            if pause and prepared.get("wave_last", True) and index + 1 < len(products):
                time.sleep(pause)
        if product_executor is not None:
            product_executor.shutdown(wait=True)
            product_executor = None
        if cursor_key and repo is not None and hasattr(repo, "save_app_setting") and products:
            resume_at = next_index % len(products)
            repo.save_app_setting(
                cursor_key,
                {
                    "next_id": products[resume_at].get("id"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "budget_exhausted": budget_exhausted,
                },
            )
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        summary["alert_count"] = len(summary["alerts"])
        summary["budget_minutes"] = budget
        summary["budget_exhausted"] = budget_exhausted
        summary["suspended_stores"] = sorted(suspended_stores)
        summary["executed_searches"] = executed_searches
        summary["duration_seconds"] = round(time.monotonic() - batch_clock, 2)
        summary["queries_per_minute"] = round(
            executed_searches * 60 / max(0.001, summary["duration_seconds"]), 2
        )
        # Las ofertas ya se envían al detectarse arriba. El segundo barrido de
        # "ofertas reales" repetía los mismos productos al terminar cada grupo.
        if repo is not None and run_id:
            repo.finish_batch_run(
                run_id,
                alert_count=summary["alert_count"],
                finished_at=summary["finished_at"],
                status="done",
                phase="budget_done" if budget_exhausted else "done",
                budget_exhausted=budget_exhausted,
                suspended_stores=sorted(suspended_stores),
                executed_searches=executed_searches,
                duration_seconds=summary["duration_seconds"],
                queries_per_minute=summary["queries_per_minute"],
                product_workers=product_workers,
            )
        return summary
    except GroupBatchStopped:
        if product_executor is not None:
            product_executor.shutdown(wait=False, cancel_futures=True)
        summary["stopped"] = True
        summary["finished_at"] = datetime.now(timezone.utc).isoformat()
        if repo is not None and run_id:
            repo.finish_batch_run(
                run_id,
                status="stopped",
                phase="stopped",
                finished_at=summary["finished_at"],
            )
        return summary
    except Exception as exc:
        if product_executor is not None:
            product_executor.shutdown(wait=False, cancel_futures=True)
        if repo is not None and run_id:
            repo.finish_batch_run(
                run_id,
                status="failed",
                phase="failed",
                last_error=str(exc),
            )
        raise
    finally:
        if repo is not None:
            repo.close()


def _catalog_search_kwargs(
    item: dict[str, Any],
    *,
    stores: list[str],
    origin_store: str | None,
    source: str,
    max_items: int,
    delay: float,
    group_key: str | None,
    store_key: str | None,
    run_id: str | None,
    started_at: str,
) -> dict[str, Any]:
    """Argumentos comunes de una búsqueda de catálogo, aptos para un worker."""
    return {
        "source": source,
        "stores": stores,
        "max_items": min(max_items, 3) if origin_store else max_items,
        "delay": delay,
        # El hilo solo obtiene datos. Persistencia, alertas y contadores se
        # mantienen en el hilo principal y en el orden del catálogo.
        "persist": False,
        "fresh": True,
        "background_side_effects": False,
        "wait_for_all": True,
        "persist_meta": {
            "catalog_id": item.get("id"),
            "catalog_query": item.get("query"),
            "catalog_category": item.get("category"),
            "batch_grupo": group_key,
            "batch_tienda": store_key,
            "last_batch_run": run_id or started_at,
            "last_batch_at": started_at,
            "batch_origin_store": origin_store,
        },
    }


def _timed_catalog_search(query: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        return {
            "result": search_products(query, **kwargs),
            "error": None,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "result": None,
            "error": exc,
            "duration_seconds": round(time.monotonic() - started, 3),
        }


def _interleave_products_by_origin(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Alterna tiendas conservando el orden interno de cada una.

    Los productos genéricos comparten un bloque especial porque consultan
    varias tiendas y, por seguridad, se ejecutan sin otra búsqueda paralela.
    """
    buckets: OrderedDict[str, deque[dict[str, Any]]] = OrderedDict()
    for item in products:
        key = catalog_origin_store(item) or "__shared__"
        buckets.setdefault(key, deque()).append(item)
    interleaved: list[dict[str, Any]] = []
    while buckets:
        empty: list[str] = []
        for key, rows in buckets.items():
            interleaved.append(rows.popleft())
            if not rows:
                empty.append(key)
        for key in empty:
            buckets.pop(key, None)
    return interleaved


def _rotate_products(products: list[dict[str, Any]], next_id: str) -> list[dict[str, Any]]:
    """Reanuda un catálogo desde el último cursor sin perder ni duplicar filas."""
    if not next_id:
        return list(products)
    for index, item in enumerate(products):
        if str(item.get("id") or "") == next_id:
            return [*products[index:], *products[:index]]
    return list(products)


def _check_watches(
    repo,
    channels: list[str],
    *,
    run: str,
    source: str,
    stores: list[str] | None,
    max_items: int,
    delay: float,
    pause: float,
    persist: bool,
) -> int:
    """Revisa primero los productos seguidos: son los que le importan al usuario."""
    if repo is None:
        return 0
    watches = [item for item in repo.list_watches(active_only=True) if item.get("query")]
    if not watches:
        return 0
    by_query: dict[str, list[dict[str, Any]]] = {}
    for watch in watches:
        by_query.setdefault(watch["query"], []).append(watch)
    sent = 0
    for index, (query, group) in enumerate(by_query.items()):
        from retail.batch.config import wait_while_paused

        wait_while_paused(repo, run)
        print(f"[seguidos {index + 1}/{len(by_query)}] {query}")
        try:
            result = search_products(
                query,
                source=source,
                stores=stores,
                max_items=max_items,
                delay=delay,
                persist=persist,
                persist_meta={"watch_query": query, "last_batch_run": run},
            )
        except Exception as exc:
            print(f"    error: {exc}")
            continue
        for watch in group:
            detected = watch_alerts(result, watch)
            alerts = [
                alert for alert in detected
                if alert.rule == "watch_change" or not repo.alert_exists(alert)
            ]
            if not alerts:
                best_prices = [
                    int(row["price"])
                    for product_group in result.get("groups") or []
                    if not watch.get("compare_code") or product_group.get("compare_code") == watch.get("compare_code")
                    for row in product_group.get("offers") or []
                    if row.get("price")
                ]
                if best_prices and hasattr(repo, "mark_watch_checked"):
                    repo.mark_watch_checked(watch.get("_id") or watch.get("id"), min(best_prices))
                continue
            repo.save_alerts(alerts, run=run)
            dispatch_alerts(alerts, [channel for channel in channels if channel not in {"email", "telegram"}], repo=repo)
            owner = repo.find_user_by_id(str(watch.get("user_id") or "")) if hasattr(repo, "find_user_by_id") else None
            if owner:
                dispatch_user_alerts(alerts, [owner], repo=repo, system_channels=channels)
            repo.mark_watch_notified(watch.get("_id") or watch.get("id"), alerts[0].price)
            sent += len(alerts)
        if pause and index + 1 < len(by_query):
            time.sleep(pause)
    return sent


def _alert_rows(alerts: list[Alert]) -> list[dict[str, Any]]:
    return [
        {
            "catalog_id": alert.catalog_id,
            "query": alert.query,
            "rule": alert.rule,
            "store": alert.store,
            "price": alert.price,
            "message": alert.message,
        }
        for alert in alerts
    ]
