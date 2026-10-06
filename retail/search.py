from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from typing import Any

import os

from retail.compare import collapse_display, compare_products
from retail.index.products import (
    claim_unique_sweep,
    feed_discovered_groups,
    feed_search,
    public_payload,
    release_unique_sweep,
    stores_for,
)
from retail.models import Product
from retail.pricing import cheaper_before, cheaper_elsewhere, mark_false_list_discounts, price_stats
from retail.qdrant_index import connect_qdrant
from retail.registry import GROUP_TITLES, get_client, group_of, list_stores
from retail.relevance import filter_relevant, fold
from retail.search_cache import (
    cache_warnings,
    describe_cache,
    lookup_search_result,
    lookup_store_products,
    resolve_search_query,
    rewrite_search_query,
    store_search_result,
    store_store_products,
)
from retail import thumbs

SOURCES = ("scrape", "db", "both")
STORE_WORKERS = max(1, int(os.environ.get("RETAIL_STORE_WORKERS", "8")))
SEARCH_TIMEOUT = float(os.environ.get("RETAIL_SEARCH_TIMEOUT", "12"))
READY_STORE_RATIO = 0.80
READY_OFFER_RATIO = 0.50
READY_EARLY_SECONDS = 5.0
READY_EARLY_OFFERS = 10
DB_RECOVERY_MIN_RESULTS = max(1, int(os.environ.get("RETAIL_DB_RECOVERY_MIN_RESULTS", "10")))
OPTIONAL_STORES = frozenset({"movistar", "salcobrand"})
OPTIONAL_STORE_TIMEOUT = 5.0
_DONE_STATES = {"ok", "error", "skip"}
_CANCELS: dict[str, threading.Event] = {}
_CANCELS_LOCK = threading.Lock()
_CANCELS_CAP = 200
logger = logging.getLogger(__name__)


def is_optional_store(store_id: str) -> bool:
    return (store_id or "").lower().strip() in OPTIONAL_STORES


def wait_progress(progress: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Tiendas que sí bloquean overlay/`done`. Movistar y Salcobrand quedan fuera."""
    return [item for item in progress or [] if not is_optional_store(str(item.get("id") or ""))]


def wait_set_done(progress: list[dict[str, Any]] | None) -> bool:
    items = wait_progress(progress)
    if not items:
        return True
    return all(item.get("state") in _DONE_STATES for item in items)


def search_is_ready(
    progress: list[dict[str, Any]] | None,
    offer_count: int = 0,
    elapsed: float = 0.0,
) -> bool:
    """Suelta el overlay: 80% del wait-set, 50%+ con oferta, o 5s con 10+ coinciden."""
    items = wait_progress(progress)
    total = len(items)
    if not total:
        return True
    done = sum(1 for item in items if item.get("state") in _DONE_STATES)
    if done >= total:
        return True
    ratio = done / total
    if ratio >= READY_STORE_RATIO:
        return True
    if int(offer_count or 0) >= 1 and ratio >= READY_OFFER_RATIO:
        return True
    return float(elapsed or 0) >= READY_EARLY_SECONDS and int(offer_count or 0) >= READY_EARLY_OFFERS


def _is_timeout_error(error: str | None) -> bool:
    text = (error or "").lower()
    return any(token in text for token in ("timeout", "timed out", "timedout", "time out"))


def _is_timeout_exc(exc: BaseException) -> bool:
    return "timeout" in type(exc).__name__.lower() or _is_timeout_error(str(exc))


def _cancelled(cancel: threading.Event | None) -> bool:
    return cancel is not None and cancel.is_set()


def new_search_cancel(search_id: str | None = None) -> tuple[str, threading.Event]:
    ident = str(search_id or "").strip() or uuid.uuid4().hex
    with _CANCELS_LOCK:
        event = _CANCELS.get(ident)
        if event is None:
            event = threading.Event()
            _CANCELS[ident] = event
    return ident, event


def request_search_cancel(search_id: str) -> bool:
    ident = str(search_id or "").strip()
    if not ident:
        return False
    with _CANCELS_LOCK:
        event = _CANCELS.get(ident)
        if event is None:
            if len(_CANCELS) >= _CANCELS_CAP:
                return False
            event = threading.Event()
            _CANCELS[ident] = event
        event.set()
    return True


def drop_search_cancel(search_id: str) -> None:
    ident = str(search_id or "").strip()
    if not ident:
        return
    with _CANCELS_LOCK:
        _CANCELS.pop(ident, None)


def _shutdown_pool(pool: ThreadPoolExecutor, cancel: threading.Event | None) -> None:
    waiting = not _cancelled(cancel)
    pool.shutdown(wait=waiting, cancel_futures=not waiting)


def connect_repo():
    try:
        from retail.mongo import ProductRepository

        repo = ProductRepository()
        if repo.ping():
            return repo
        repo.close()
    except Exception:
        return None
    return None


def scrape_store(
    store_id: str,
    query: str,
    *,
    max_items: int,
    delay: float,
    timeout: float,
    attempts: int = 2,
) -> tuple[list[Product], str | None]:
    last_error: str | None = None
    store_timeout = float(timeout)
    tries = max(1, int(attempts))
    client_kw: dict[str, Any] = {"delay": delay, "timeout": store_timeout}
    if is_optional_store(store_id):
        store_timeout = min(store_timeout, OPTIONAL_STORE_TIMEOUT)
        tries = 1
        client_kw["timeout"] = store_timeout
        client_kw["retries"] = 1
    for attempt in range(1, tries + 1):
        try:
            with get_client(store_id, **client_kw) as client:
                return client.scrape(query, max_pages=1, max_items=max_items), None
        except Exception as exc:
            last_error = str(exc)
            if _is_timeout_exc(exc):
                last_error = f"timeout ({store_timeout:.0f}s): {last_error}"
                break
            if attempt < tries:
                logger.warning("%s fallo, reintento %s/%s: %s", store_id, attempt + 1, tries, last_error)
                if delay > 0:
                    time.sleep(min(3.0, delay * attempt))
    return [], last_error


def scrape_all(
    query: str,
    stores: list[str],
    *,
    max_items: int = 5,
    delay: float = 1.0,
    timeout: float = 20.0,
    workers: int | None = None,
) -> tuple[list[Product], list[dict[str, str]]]:
    products: list[Product] = []
    errors: list[dict[str, str]] = []
    pool_size = max(1, min(workers or STORE_WORKERS, len(stores) or 1))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        futures = {
            pool.submit(scrape_store, store_id, query, max_items=max_items, delay=delay, timeout=timeout): store_id
            for store_id in stores
        }
        for future in as_completed(futures):
            store_id = futures[future]
            found, error = future.result()
            products.extend(found)
            if error:
                errors.append({"store": store_id, "error": error})
    return products, errors


def scrape_category_probes(
    query: str,
    stores: list[str],
    *,
    max_items: int = 5,
    delay: float = 1.0,
    timeout: float = SEARCH_TIMEOUT,
    price_band: bool = True,
) -> tuple[dict[str, list[Product]], list[dict[str, str]], list[str]]:
    """Explora categorías fuera del índice: una tienda antes de ampliar el grupo.

    Solo se usa para descubrir categorías adicionales. Las categorías del
    producto y las tiendas seleccionadas expresamente se consultan completas.
    Un error no demuestra ausencia: se prueba la siguiente tienda del grupo.
    """
    grouped: dict[str, list[str]] = {}
    for store_id in dict.fromkeys(stores):
        grouped.setdefault(group_of(store_id)[0], []).append(store_id)
    waiting: dict[str, list[str]] = {}
    queue: list[tuple[str, bool]] = []
    for group, members in grouped.items():
        if group in {"retail", "otros"}:
            queue.extend((store_id, False) for store_id in members)
        else:
            queue.append((members[0], True))
            waiting[group] = list(members[1:])
    found_by_store: dict[str, list[Product]] = {}
    errors: list[dict[str, str]] = []
    skipped: list[str] = []
    workers = max(1, min(STORE_WORKERS, len(stores) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: dict[Any, tuple[str, bool]] = {}
        while queue or futures:
            while queue and len(futures) < workers:
                store_id, probe = queue.pop(0)
                future = pool.submit(
                    scrape_store, store_id, query, max_items=max_items,
                    delay=delay, timeout=timeout, attempts=1,
                )
                futures[future] = (store_id, probe)
            finished, _ = wait(set(futures), return_when=FIRST_COMPLETED)
            for future in finished:
                store_id, probe = futures.pop(future)
                try:
                    products, error = future.result()
                except Exception as exc:
                    products, error = [], str(exc)
                if error:
                    errors.append({"store": store_id, "error": error})
                else:
                    found_by_store[store_id] = products
                if not probe:
                    continue
                group = group_of(store_id)[0]
                rest = waiting[group]
                if error:
                    if rest:
                        queue.append((rest.pop(0), True))
                    continue
                matches, _, _ = filter_relevant(query, products, price_band=price_band)
                if matches:
                    queue.extend((other, False) for other in rest)
                else:
                    skipped.extend(rest)
                rest.clear()
    return found_by_store, errors, skipped


def merge_products(scraped: list[Product], stored: list[Product]) -> tuple[list[Product], set[tuple[str, str]]]:
    merged: dict[tuple[str, str], Product] = {}
    scraped_keys: set[tuple[str, str]] = set()
    for product in stored:
        key = (product.store, product.product_id or product.name)
        merged[key] = product
    for product in scraped:
        key = (product.store, product.product_id or product.name)
        scraped_keys.add(key)
        merged[key] = product
    return list(merged.values()), scraped_keys


def _discard_reasons(discarded: list[Any], details) -> list[dict[str, Any]]:
    """Cuántos se descartaron por cada motivo explícito, de mayor a menor."""
    counts: dict[str, int] = {}
    for product in discarded:
        item = details.get((product.store, product.product_id or product.name))
        reason = getattr(item, "reason", None)
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
    ordered = sorted(counts.items(), key=lambda pair: -pair[1])
    return [{"reason": reason, "count": count} for reason, count in ordered[:6]]


def _discarded_items(discarded: list[Any], details, titles: dict[str, str]) -> list[dict[str, Any]]:
    """Filas livianas para mostrar en la UI qué se dejó fuera."""
    rows: list[dict[str, Any]] = []
    from retail.store_display import display_store

    for product in discarded:
        key = (product.store, product.product_id or product.name)
        item = details.get(key)
        row = {
            "name": product.name,
            "store": product.store,
            "seller": product.seller,
            "price": product.price,
            "url": product.url,
            "brand": product.brand,
            "product_id": product.product_id,
            "reason": getattr(item, "reason", None),
            "missing": list(getattr(item, "missing", None) or []),
        }
        row["display_store"], row["store_title"] = display_store(row, titles)
        rows.append(row)
    rows.sort(key=lambda row: (row.get("store_title") or "", row.get("name") or "", row.get("store") or ""))
    return rows


def _attach_relevance(groups: list[dict[str, Any]], details) -> None:
    for group in groups:
        for offer in group.get("offers") or []:
            key = (offer.get("store") or "", offer.get("product_id") or offer.get("name") or "")
            item = details.get(key)
            offer["relevance"] = item.score if item else 0.0
            offer["matched"] = item.matched if item else []


def attach_price_history(repo, groups: list[dict[str, Any]]) -> None:
    if repo is None:
        return
    keys = [
        (offer.get("store") or "", offer.get("product_id") or "")
        for group in groups
        for offer in group.get("offers") or []
    ]
    try:
        found = repo.histories(keys)
    except Exception:
        return
    for group in groups:
        for offer in group.get("offers") or []:
            points = [
                {"price": item.get("price"), "scraped_at": item.get("scraped_at")}
                for item in found.get((offer.get("store") or "", offer.get("product_id") or ""), [])
                if item.get("price") is not None
            ]
            current = offer.get("price")
            stats = price_stats(points, current)
            previous = stats.get("previous")
            spark = list(points)
            if current is not None and (not spark or spark[-1]["price"] != current):
                spark.append({"price": current, "scraped_at": offer.get("scraped_at")})
            offer["price_history"] = spark[-12:]
            offer["price_stats"] = stats
            offer["previous_price"] = previous
            offer["price_delta"] = None if previous is None or current is None else current - previous


def _iter_offers(groups: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for group in groups:
        yield from group.get("offers") or []


def _thumb_key(row: dict[str, Any]) -> tuple[str, str]:
    return (row.get("store") or "", row.get("product_id") or "")


def attach_thumbs(repo, groups: list[dict[str, Any]], rows: list[dict[str, Any]] | None = None) -> None:
    """Marca qué ofertas ya tienen miniatura guardada en Mongo."""
    if repo is None:
        return
    try:
        flags = repo.thumb_flags([_thumb_key(offer) for offer in _iter_offers(groups)])
    except Exception:
        return
    for offer in _iter_offers(groups):
        offer["has_thumb"] = _thumb_key(offer) in flags or bool(offer.get("image_url") or offer.get("image_urls"))
    for row in rows or []:
        row["has_thumb"] = _thumb_key(row) in flags or bool(row.get("image_url") or row.get("image_urls"))


def mark_thumbs(result: dict[str, Any], keys: list[tuple[str, str]] | list[dict[str, Any]]) -> list[dict[str, str]]:
    """Parchea has_thumb en un resultado ya emitido, sin armar otra búsqueda."""
    wanted: set[tuple[str, str]] = set()
    for item in keys:
        if isinstance(item, dict):
            wanted.add((str(item.get("store") or ""), str(item.get("product_id") or "")))
        else:
            store, product_id = item
            wanted.add((str(store or ""), str(product_id or "")))
    wanted.discard(("", ""))
    if not wanted:
        return []
    for offer in _iter_offers(result.get("groups") or []):
        if _thumb_key(offer) in wanted:
            offer["has_thumb"] = True
    for row in result.get("rows") or []:
        if _thumb_key(row) in wanted:
            row["has_thumb"] = True
    return [{"store": store, "product_id": product_id} for store, product_id in wanted]


def thumb_targets(rows: list[dict[str, Any]] | None, *, seen: set[tuple[str, str]], limit: int) -> list[tuple[tuple[str, str], str]]:
    """Coinciden primero (orden de rows); respeta el tope y omite las ya vistas."""
    budget = max(0, int(limit) - len(seen))
    if budget <= 0:
        return []
    targets: list[tuple[tuple[str, str], str]] = []
    for row in rows or []:
        key = _thumb_key(row)
        url = row.get("image_url")
        if not key[0] or not key[1] or not url or key in seen:
            continue
        # has_thumb también incluye imágenes remotas aún no guardadas.
        # missing_thumbnails consulta Mongo para omitir las ya descargadas.
        seen.add(key)
        targets.append((key, url))
        if len(targets) >= budget:
            break
    return targets


def enrich_thumbnails(repo, rows: list[dict[str, Any]], limit: int | None = None) -> list[tuple[str, str]]:
    """Descarga y guarda en Mongo las miniaturas que falten."""
    if repo is None or not thumbs.enabled():
        return []
    targets: list[tuple[tuple[str, str], str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = _thumb_key(row)
        url = row.get("image_url")
        if not key[0] or not key[1] or not url or key in seen:
            continue
        seen.add(key)
        targets.append((key, url))
    pending = repo.missing_thumbnails(targets)[: limit or thumbs.default_limit()]
    built = thumbs.build_many(pending)
    if built:
        repo.save_thumbnails(built)
    return list(built.keys())


def attach_cheaper_hints(groups: list[dict[str, Any]]) -> None:
    """Marca, en cada aviso, si hubo un precio menor en el pasado o en otra tienda."""
    for group in groups:
        offers = group.get("offers") or []
        for offer in offers:
            offer["cheaper_before"] = cheaper_before(offer.get("price_history"), offer.get("price"))
            offer["cheaper_elsewhere"] = cheaper_elsewhere(offer, offers)
    mark_false_list_discounts(groups)


def refresh_cached_comparisons(result: dict[str, Any]) -> dict[str, Any]:
    """Actualiza agrupación y mínimos de una caché creada con reglas anteriores."""
    if int(result.get("comparison_version") or 0) >= 2:
        return result
    rows = [dict(row) for row in result.get("rows") or [] if isinstance(row, dict)]
    if not rows or not result.get("groups"):
        return result
    originals = {
        (str(row.get("store") or ""), str(row.get("product_id") or "")): row
        for row in rows
    }
    groups = compare_products([Product.from_dict(row) for row in rows])
    for group in groups:
        enriched = []
        for computed in group.get("offers") or []:
            key = (str(computed.get("store") or ""), str(computed.get("product_id") or ""))
            offer = dict(originals.get(key) or computed)
            for field in (
                "compare_code", "entity_id", "entity_confidence",
                "entity_match_method", "is_lowest", "comparison_price", "total_price",
            ):
                offer[field] = computed.get(field)
            enriched.append(offer)
        group["offers"] = enriched
    collapse_display(groups)
    attach_cheaper_hints(groups)
    result["groups"] = groups
    result["rows"] = flatten_rows(groups)
    result["offer_count"] = len(result["rows"])
    result["group_count"] = len(groups)
    result["comparable_count"] = sum(1 for group in groups if group.get("comparable"))
    result["comparison_version"] = 2
    return result


def flatten_rows(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in groups:
        for offer in group.get("offers") or []:
            row = dict(offer)
            row["lowest_price"] = group.get("lowest_price")
            row["lowest_stores"] = group.get("lowest_stores") or []
            row["lowest_store_titles"] = group.get("lowest_store_titles") or []
            row["comparable"] = group.get("comparable")
            row["compare_kind"] = group.get("kind")
            rows.append(row)
    rows.sort(
        key=lambda item: (
            not item.get("comparable"),
            item.get("price") is None,
            item.get("price") or 10**12,
            item.get("store") or "",
        )
    )
    return rows


def _annotate(groups: list[dict[str, Any]], scraped_keys: set[tuple[str, str]], titles: dict[str, str]) -> None:
    from retail.store_display import display_store

    for group in groups:
        for offer in group.get("offers") or []:
            key = (offer.get("store") or "", offer.get("product_id") or offer.get("name") or "")
            offer["from_scrape"] = key in scraped_keys
            offer["from_db"] = key not in scraped_keys
            display_id, display_title = display_store(offer, titles)
            offer["display_store"] = display_id
            offer["store_title"] = display_title
        group["lowest_store_titles"] = [
            next(
                (
                    offer.get("store_title")
                    for offer in group.get("offers") or []
                    if offer.get("store") == store and offer.get("store_title")
                ),
                titles.get(store, store),
            )
            for store in group.get("lowest_stores") or []
        ]


def _explicit_store_filter(stores: list[str] | None, available: list[str]) -> bool:
    """True si el caller eligió un subconjunto; 'todas' o None se enrutan por el índice."""
    requested = [item.lower().strip() for item in (stores or []) if item]
    if not requested:
        return False
    return set(requested) != set(available)


def _resolve_scope(
    query: str, source: str, stores: list[str] | None
) -> tuple[str, list[str], dict[str, str], dict[str, Any] | None]:
    text = query.strip()
    if not text:
        raise ValueError("Escribe un producto para buscar.")
    if source not in SOURCES:
        raise ValueError(f"Origen inválido: {source}. Usa scrape, db o both.")
    available = [spec.id for spec in list_stores()]
    requested = [item.lower().strip() for item in (stores or []) if item]
    unknown = [item for item in requested if item not in available]
    if unknown:
        raise ValueError(f"Tiendas desconocidas: {', '.join(unknown)}")
    explicit = _explicit_store_filter(requested, available)
    chosen = requested if explicit else list(available)
    if not chosen:
        chosen = list(available)
        explicit = False
    applied = False
    if not explicit:
        routed = stores_for(text, available)
        if routed:
            chosen = routed
            applied = True
    titles = {spec.id: spec.title for spec in list_stores()}
    return text, chosen, titles, public_payload(text, chosen, applied=applied)


def _category_recovery_plan(
    query: str,
    qdrant: Any | None,
    allowed_stores: list[str],
    current_stores: list[str],
    product_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Infiere categorías semánticas y las convierte en tiendas a consultar."""
    candidates: list[dict[str, Any]] = []
    if qdrant is not None and hasattr(qdrant, "category_candidates"):
        try:
            candidates = list(qdrant.category_candidates(query, limit=40) or [])
        except Exception:
            logger.debug("No se pudieron inferir categorías en Qdrant", exc_info=True)
    if candidates:
        best = float(candidates[0].get("score") or 0.0)
        candidates = [
            item for item in candidates[:8]
            if float(item.get("score") or 0.0) >= max(0.20, best * 0.78)
        ]

    groups: list[str] = []
    categories: list[str] = []

    def add_group(value: str | None) -> None:
        key = str(value or "").strip().lower()
        if key in GROUP_TITLES and key not in groups:
            groups.append(key)

    folded_groups = {
        fold(group_id): group_id for group_id in GROUP_TITLES
    } | {
        fold(title): group_id for group_id, title in GROUP_TITLES.items()
    }
    for item in candidates:
        category = str(item.get("category") or "").strip()
        if category and category not in categories:
            categories.append(category)
        add_group(folded_groups.get(fold(category)))
        for store_id in item.get("stores") or []:
            add_group(group_of(str(store_id))[0])
    # El índice estático es respaldo. Cuando Qdrant sí encontró categorías,
    # mezclar ambos grupos volvería a abrir tiendas genéricas y perdería el
    # beneficio del scraping dirigido.
    if not groups:
        for group_id in (product_index or {}).get("groups") or []:
            add_group(str(group_id))
    if not groups:
        for store_id in current_stores:
            add_group(group_of(store_id)[0])

    allowed = list(dict.fromkeys(allowed_stores or current_stores))
    stores = [store_id for store_id in allowed if group_of(store_id)[0] in set(groups)]
    if not stores:
        stores = list(dict.fromkeys(current_stores or allowed))
    return {
        "triggered": True,
        "threshold": DB_RECOVERY_MIN_RESULTS,
        "categories": categories,
        "groups": groups,
        "stores": stores,
        "engine": "qdrant" if candidates else "product_index",
    }


def remaining_store_ids(chosen: list[str], available: list[str] | None = None) -> list[str]:
    ids = available if available is not None else [spec.id for spec in list_stores()]
    taken = {item.lower().strip() for item in chosen if item}
    return [store_id for store_id in ids if store_id not in taken]


def _claim_other_stores_job(
    query: str,
    product_index: dict[str, Any] | None,
    chosen: list[str],
    *,
    source: str,
    max_items: int,
    delay: float,
    timeout: float,
    price_band: bool,
    persist: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Reserva el barrido de tiendas fuera del índice. No lanza el scrape."""
    payload = dict(product_index) if product_index else None
    if source not in {"scrape", "both"} or not payload or not payload.get("applied"):
        return None, payload
    product_id = str(payload.get("id") or "").strip()
    if not product_id:
        return None, payload
    try:
        others = remaining_store_ids(chosen)
        if not others:
            return None, payload
        if not claim_unique_sweep(product_id):
            return None, payload
    except Exception:
        logger.debug("No se pudo reservar el barrido extra", exc_info=True)
        return None, payload
    payload["background"] = True
    return (
        {
            "query": query,
            "product_id": product_id,
            "others": others,
            "max_items": max_items,
            "delay": delay,
            "timeout": timeout,
            "price_band": price_band,
            "persist": persist,
        },
        payload,
    )


def run_other_stores_sweep(
    query: str,
    product_id: str,
    others: list[str],
    *,
    max_items: int = 5,
    delay: float = 1.0,
    timeout: float = 20.0,
    price_band: bool = True,
    persist: bool = True,
    repo: Any | None = None,
) -> list[str]:
    """Scrape de tiendas fuera del índice. Retroalimenta grupos si hay coincidencias."""
    stores = [item for item in others if item]
    if not stores or not product_id:
        return []
    by_store, errors, skipped = scrape_category_probes(
        query,
        stores,
        max_items=max_items,
        delay=delay,
        timeout=timeout,
        price_band=price_band,
    )
    products = [product for items in by_store.values() for product in items]
    logger.info(
        "Índice por categoría de %s: %s tiendas consultadas; %s omitidas tras una prueba sin coincidencias.",
        product_id, len(by_store) + len(errors), len(skipped),
    )
    if errors:
        logger.warning(
            "Barrido extra de %s: %s errores",
            product_id,
            len(errors),
        )
    try:
        store_store_products(query, by_store, max_items=max_items)
    except Exception:
        logger.debug("No se pudo cachear el barrido extra de %s", product_id, exc_info=True)
    kept, _discarded, _details = filter_relevant(query, products, price_band=price_band)
    if not kept:
        logger.info(
            "Barrido extra de %s: sin coincidencias en %s tiendas",
            product_id,
            len(stores),
        )
        return []
    hit_stores = list(dict.fromkeys(item.store for item in kept if item.store))
    extra = feed_discovered_groups(product_id, hit_stores, query=query, repo=repo)
    if extra:
        logger.info(
            "Índice %s: grupos nuevos %s (tiendas %s)",
            product_id,
            ", ".join(extra),
            ", ".join(hit_stores),
        )
    if persist:
        close = False
        store = repo
        if store is None:
            store = connect_repo()
            close = store is not None
        if store is not None:
            try:
                groups = compare_products(kept)
                store.persist_search(
                    query,
                    groups,
                    source="scrape",
                    store_errors=errors,
                    extra={"background": True, "product_id": product_id},
                )
            except Exception:
                logger.debug("No se pudo guardar el barrido extra de %s", product_id, exc_info=True)
            finally:
                if close:
                    try:
                        store.close()
                    except Exception:
                        pass
    return extra


def launch_other_store_sweep(job: dict[str, Any] | None, *, background: bool = True) -> None:
    if not job:
        return

    def run() -> None:
        try:
            run_other_stores_sweep(**job)
        except Exception:
            logger.exception("Barrido extra de %s falló", job.get("product_id"))

    if not background:
        run()
        return
    try:
        threading.Thread(
            target=run,
            daemon=True,
            name=f"pindex-sweep-{job.get('product_id') or 'x'}",
        ).start()
    except Exception:
        logger.debug("No se pudo disparar el barrido extra", exc_info=True)


def _client_progress(progress: list[dict[str, Any]] | None, *, reveal: bool = False) -> list[dict[str, Any]]:
    if reveal:
        return [dict(item) for item in progress or []]
    return [{key: value for key, value in item.items() if key != "error"} for item in progress or []]


def build_result(
    text: str,
    source: str,
    chosen: list[str],
    titles: dict[str, str],
    scraped: list[Product],
    stored: list[Product],
    errors: list[dict[str, str]],
    warnings: list[str],
    *,
    repo=None,
    qdrant=None,
    extra_scores: dict[tuple[str, str], float] | None = None,
    saved: dict[str, Any] | None = None,
    progress: list[dict[str, Any]] | None = None,
    price_band: bool = True,
    reveal: bool = False,
    product_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    products, scraped_keys = merge_products(scraped, stored)
    kept, discarded, details = filter_relevant(text, products, extra_scores or {}, price_band=price_band)
    groups = compare_products(kept)
    _annotate(groups, scraped_keys, titles)
    _attach_relevance(groups, details)
    attach_price_history(repo, groups)
    attach_thumbs(repo, groups)
    # Se colapsa una copia: en Mongo siguen las dos publicaciones.
    display = [{**group, "offers": [dict(offer) for offer in group.get("offers") or []]} for group in groups]
    collapse_display(display)
    attach_cheaper_hints(display)
    rows = flatten_rows(display)
    return {
        "query": text,
        "source": source,
        "price_band": price_band,
        "stores": chosen,
        "mongo": repo is not None,
        "qdrant": qdrant is not None,
        "offer_count": len(rows),
        "group_count": len(display),
        "comparable_count": sum(1 for group in display if group.get("comparable")),
        "scraped_count": len(scraped),
        "db_count": len(stored),
        "discarded_count": len(discarded),
        "discarded_reasons": _discard_reasons(discarded, details),
        "discarded": _discarded_items(discarded, details, titles),
        "warnings": list(warnings) if reveal else [],
        "store_errors": list(errors) if reveal else [],
        "saved": saved,
        "progress": _client_progress(progress, reveal=reveal),
        "product_index": product_index,
        "comparison_version": 2,
        "groups": display,
        "rows": rows,
    }


def _apply_cancel_state(
    result: dict[str, Any],
    progress: list[dict[str, Any]],
    chosen: list[str],
    *,
    cancelled: bool,
) -> None:
    if cancelled:
        for item in progress:
            if item.get("state") in {"pending", "running"}:
                item["state"] = "skip"
    done = sum(1 for item in progress if item.get("state") in _DONE_STATES)
    total = len(progress) or len(chosen)
    result["cancelled"] = cancelled
    result["stores_done"] = done
    result["stores_total"] = total
    if cancelled:
        result["stopped_label"] = f"Búsqueda detenida · {done} de {total} tiendas"


def iter_search_events(
    query: str,
    *,
    source: str = "both",
    stores: list[str] | None = None,
    max_items: int = 5,
    delay: float = 1.0,
    timeout: float = SEARCH_TIMEOUT,
    persist: bool = True,
    persist_meta: dict[str, Any] | None = None,
    price_band: bool = True,
    fresh: bool = False,
    reveal: bool = False,
    cancel: threading.Event | None = None,
    search_id: str | None = None,
    background_side_effects: bool = True,
    wait_for_all: bool = False,
    preferred_stores: list[str] | None = None,
    excluded_stores: list[str] | None = None,
    recover_underfilled_db: bool = True,
) -> Iterator[dict[str, Any]]:
    requested_query = " ".join(str(query or "").split())
    query = rewrite_search_query(requested_query)
    if query and not fresh:
        query = resolve_search_query(query)
    text, chosen, titles, product_index = _resolve_scope(query, source, stores)
    available = [spec.id for spec in list_stores()]
    excluded = {item for item in (excluded_stores or []) if item in available}
    preferred = list(dict.fromkeys(item for item in (preferred_stores or []) if item in available and item not in excluded))
    explicit = _explicit_store_filter(stores, available)
    chosen = [item for item in chosen if item not in excluded]
    if not explicit:
        chosen = [item for item in preferred if item not in chosen] + chosen
    preferred_set = set(preferred)
    chosen = [item for item in preferred if item in chosen] + [item for item in chosen if item not in preferred_set]
    recovery_stores = list(chosen) if explicit else [item for item in available if item not in excluded]
    recovery_stores = (
        [item for item in preferred if item in recovery_stores]
        + [item for item in recovery_stores if item not in preferred_set]
    )
    if product_index is not None:
        product_index = dict(product_index)
        product_index["stores"] = list(chosen)
    feed_search(
        text,
        product_index,
        store_count=len(chosen),
        applied=bool((product_index or {}).get("applied")),
    )
    sweep_job, product_index = _claim_other_stores_job(
        text,
        product_index,
        chosen,
        source=source,
        max_items=max_items,
        delay=delay,
        timeout=timeout,
        price_band=price_band,
        persist=persist,
    )
    served_daily_cache = False
    try:
        for event in _run_search_events(
            text,
            source=source,
            chosen=chosen,
            titles=titles,
            product_index=product_index,
            max_items=max_items,
            delay=delay,
            timeout=timeout,
            persist=persist,
            persist_meta=persist_meta,
            price_band=price_band,
            fresh=fresh,
            reveal=reveal,
            cancel=cancel,
            background_side_effects=background_side_effects,
            wait_for_all=wait_for_all,
            recovery_stores=recovery_stores,
            recover_underfilled_db=recover_underfilled_db,
        ):
            if search_id and event.get("type") == "start":
                event["search_id"] = search_id
            if event.get("type") == "done" and ((event.get("result") or {}).get("cache") or {}).get("hit") == "result":
                served_daily_cache = True
            if requested_query != text:
                event["requested_query"] = requested_query
                if isinstance(event.get("result"), dict):
                    event["result"]["requested_query"] = requested_query
            yield event
    except GeneratorExit:
        if cancel is not None:
            cancel.set()
        raise
    finally:
        if _cancelled(cancel) or served_daily_cache:
            if sweep_job:
                release_unique_sweep(sweep_job["product_id"])
        else:
            launch_other_store_sweep(sweep_job)


def _run_search_events(
    text: str,
    *,
    source: str,
    chosen: list[str],
    titles: dict[str, str],
    product_index: dict[str, Any] | None,
    max_items: int,
    delay: float,
    timeout: float,
    persist: bool,
    persist_meta: dict[str, Any] | None,
    price_band: bool,
    fresh: bool,
    reveal: bool,
    cancel: threading.Event | None = None,
    background_side_effects: bool = True,
    wait_for_all: bool = False,
    recovery_stores: list[str] | None = None,
    recover_underfilled_db: bool = True,
) -> Iterator[dict[str, Any]]:
    if not fresh:
        cached_result = lookup_search_result(
            text,
            source=source,
            stores=chosen,
            max_items=max_items,
            price_band=price_band,
        )
        cache_is_underfilled_db = (
            recover_underfilled_db
            and source == "db"
            and cached_result is not None
            and int(cached_result.get("offer_count") or 0) < DB_RECOVERY_MIN_RESULTS
            and not bool(cached_result.get("recovery"))
        )
        if cached_result is not None and not cache_is_underfilled_db:
            cached_result = dict(cached_result)
            refresh_cached_comparisons(cached_result)
            cached_result["product_index"] = product_index
            cached_result["stores"] = chosen
            cached_result["cancelled"] = False
            progress = cached_result.get("progress") or []
            for item in progress:
                item["cached"] = True
                if item.get("state") in {None, "pending"}:
                    item["state"] = "skip"
            yield {"type": "start", "query": text, "progress": progress, "product_index": product_index}
            logger.info("Redis: resultado de «%s» del día en Chile.", text)
            yield {"type": "done", "result": cached_result}
            # El EventSource del navegador dispara onerror al cerrar el stream;
            # sin `end` y con 0 filas la UI mostraba «Se cortó la consulta».
            yield {"type": "end", "result": cached_result}
            return

    repo = connect_repo()
    # Un batch que solo refresca una tienda no necesita abrir Qdrant ni crear
    # tareas visuales por cada producto. El comparador web conserva el flujo
    # enriquecido completo por defecto.
    qdrant = connect_qdrant() if source in {"db", "both"} or background_side_effects else None
    warnings: list[str] = []
    errors: list[dict[str, str]] = []
    scraped: list[Product] = []
    stored: list[Product] = []
    recovery_info: dict[str, Any] | None = None
    cached_stores: dict[str, dict[str, Any]] = {}
    # Si hoy ya hubo scrape en Redis para esta consulta, no reintentar tiendas
    # faltantes: los datos del día bastan y se sirven desde caché + base.
    reuse_today_stores = False
    if source in {"scrape", "both"} and not fresh:
        cached_stores = lookup_store_products(text, chosen, max_items=max_items, qdrant=qdrant)
        reuse_today_stores = bool(cached_stores)
        if reuse_today_stores and qdrant is None:
            qdrant = connect_qdrant()
        for message in cache_warnings(
            cached_stores, chosen, titles, resume_missing=False
        ):
            logger.info("%s", message)
    pending_stores = (
        []
        if reuse_today_stores
        else (
            [store_id for store_id in chosen if store_id not in cached_stores]
            if source in {"scrape", "both"}
            else []
        )
    )
    progress = []
    for store_id in chosen:
        if source not in {"scrape", "both"}:
            state = "skip"
        elif store_id in cached_stores or reuse_today_stores:
            state = "skip"
        else:
            state = "pending"
        item = {"id": store_id, "title": titles.get(store_id, store_id), "state": state}
        if store_id in cached_stores:
            item["count"] = len(cached_stores[store_id]["products"])
            item["cached"] = True
        progress.append(item)
    by_id = {item["id"]: item for item in progress}
    for info in cached_stores.values():
        scraped.extend(info["products"])

    yield {"type": "start", "query": text, "progress": progress, "product_index": product_index}

    db_snapshot: dict[str, Any] | None = None
    # Con scrape reutilizado del día también leemos Mongo/Qdrant: la ficha ya
    # quedó actualizada y el usuario pidió no volver a las tiendas.
    if source in {"db", "both"} or reuse_today_stores:
        mongo_products: list[Product] = []
        if repo is None:
            warnings.append("MongoDB no está disponible; la búsqueda en base de datos se omitió.")
        else:
            mongo_products = [Product.from_dict(row) for row in repo.find_by_query(text)]
            stored = list(mongo_products)
        if qdrant is None:
            warnings.append("Qdrant no está disponible; el filtro semántico se omitió.")
        else:
            if mongo_products:
                try:
                    # Migra gradualmente documentos antiguos al nuevo payload
                    # con categoría, sin esperar un backfill global.
                    qdrant.upsert_products(mongo_products, query=text)
                except Exception as exc:
                    warnings.append(f"Qdrant no pudo actualizar categorías: {exc}")
            try:
                stored.extend(product for product, _score in qdrant.search(text, limit=80))
            except Exception as exc:
                warnings.append(f"Qdrant no pudo buscar: {exc}")
        allowed = set(chosen)
        stored = [item for item in stored if item.store in allowed]
        extra = {}
        if qdrant is not None:
            try:
                extra = qdrant.scores_for(text, stored)
            except Exception:
                extra = {}
        mongo_result = build_result(
            text, source, chosen, titles, [], mongo_products, [], [],
            repo=repo, qdrant=qdrant, extra_scores=extra, progress=progress,
            price_band=price_band, product_index=product_index,
        )
        mongo_count = int(mongo_result.get("offer_count") or 0)
        if recover_underfilled_db and source == "db" and mongo_count < DB_RECOVERY_MIN_RESULTS and not _cancelled(cancel):
            recovery_info = _category_recovery_plan(
                text,
                qdrant,
                recovery_stores or chosen,
                chosen,
                product_index,
            )
            recovery_info["initial_count"] = mongo_count
            chosen[:] = list(recovery_info["stores"])
            pending_stores[:] = list(chosen)
            progress[:] = [
                {"id": store_id, "title": titles.get(store_id, store_id), "state": "pending"}
                for store_id in chosen
            ]
            by_id.clear()
            by_id.update({item["id"]: item for item in progress})
            warnings.append(
                f"MongoDB devolvió {mongo_count} resultados; se inició scraping dirigido por categoría."
            )
        db_snapshot = {
            "type": "snapshot",
            "result": build_result(
                text, source, chosen, titles, scraped, stored, errors, warnings,
                repo=repo, qdrant=qdrant, extra_scores=extra, progress=progress,
                price_band=price_band, product_index=product_index,
            ),
        }
        if recovery_info is not None:
            db_snapshot["result"]["recovery"] = dict(recovery_info)

    scraped_now: dict[str, list[Product]] = {}
    released = False
    visible_done = False
    started_at = time.monotonic()
    last_visible: list[dict[str, Any] | None] = [None]
    last_snap: list[dict[str, Any] | None] = [None]
    wait_ids = [store_id for store_id in pending_stores if not is_optional_store(store_id)]
    optional_ids = [store_id for store_id in pending_stores if is_optional_store(store_id)]
    optional_pool: ThreadPoolExecutor | None = None
    optional_futures: dict[Any, str] = {}
    thumb_pool: ThreadPoolExecutor | None = None
    thumb_futures: dict[Any, tuple[str, str]] = {}
    thumb_seen: set[tuple[str, str]] = set()
    if background_side_effects and thumbs.enabled() and repo is not None:
        thumb_pool = ThreadPoolExecutor(max_workers=max(1, thumbs.WORKERS))

    def snapshot() -> dict[str, Any]:
        event = {
            "type": "snapshot",
            "result": build_result(
                text, source, chosen, titles, scraped, stored, errors, warnings,
                repo=repo, qdrant=qdrant, extra_scores={}, progress=progress,
                price_band=price_band, reveal=reveal, product_index=product_index,
            ),
        }
        if recovery_info is not None:
            event["result"]["recovery"] = dict(recovery_info)
        return event

    def apply_store_result(store_id: str, found: list[Product], error: str | None) -> None:
        if recovery_info is not None:
            inferred = next(iter(recovery_info.get("categories") or []), None)
            if not inferred:
                inferred = next(iter(recovery_info.get("groups") or []), None)
            if inferred:
                for product in found:
                    if not product.catalog_category:
                        product.catalog_category = str(inferred)
        scraped.extend(found)
        item = by_id[store_id]
        errors[:] = [row for row in errors if row["store"] != store_id]
        if error:
            item["state"] = "error"
            item["error"] = error
            item["count"] = 0
            item.pop("cached", None)
            errors.append({"store": store_id, "error": error})
            logger.warning("%s: %s", titles.get(store_id, store_id), error)
            return
        item["state"] = "ok"
        item["count"] = len(found)
        item.pop("error", None)
        scraped_now[store_id] = found

    def visible_result(*, cancelled: bool) -> dict[str, Any]:
        result = build_result(
            text, source, chosen, titles, scraped, stored, errors, warnings,
            repo=repo, qdrant=qdrant, extra_scores={}, progress=progress,
            price_band=price_band, reveal=reveal, product_index=product_index,
        )
        result["saved"] = None
        result["warnings"] = []
        cache = describe_cache(cached_stores, chosen, resume_missing=not reuse_today_stores)
        if cache:
            result["cache"] = cache
        if recovery_info is not None:
            result["recovery"] = dict(recovery_info)
        _apply_cancel_state(result, progress, chosen, cancelled=cancelled)
        return result

    def launch_side_effects() -> None:
        copied_scraped = list(scraped)
        copied_stored = list(stored)
        copied_now = {key: list(value) for key, value in scraped_now.items()}
        copied_errors = list(errors)
        copied_progress = [dict(item) for item in progress]
        stopped = _cancelled(cancel)

        def run() -> None:
            store = connect_repo()
            try:
                result = build_result(
                    text, source, chosen, titles, copied_scraped, copied_stored,
                    copied_errors, list(warnings),
                    repo=store, qdrant=qdrant, extra_scores={}, progress=copied_progress,
                    price_band=price_band, reveal=reveal, product_index=product_index,
                )
                if recovery_info is not None:
                    result["recovery"] = dict(recovery_info)
                live = bool(copied_now)
                if persist and not stopped and store is not None and (live or source == "db"):
                    try:
                        meta = dict(persist_meta or {})
                        if recovery_info is not None:
                            meta["recovery"] = dict(recovery_info)
                        result["saved"] = store.persist_search(
                            text,
                            result["groups"],
                            source=source,
                            store_errors=copied_errors,
                            extra=meta or None,
                        )
                    except Exception as exc:
                        logger.warning("No se pudieron guardar los resultados: %s", exc)
                if persist and not stopped and store is not None:
                    try:
                        enrich_thumbnails(store, result["rows"])
                        attach_thumbs(store, result["groups"], result["rows"])
                    except Exception as exc:
                        logger.warning("No se pudieron guardar las miniaturas: %s", exc)
                if persist and not stopped and qdrant is not None and live:
                    try:
                        kept = [Product.from_dict(row) for row in result["rows"]]
                        qdrant.upsert_products(kept, query=text)
                    except Exception as exc:
                        logger.warning("No se pudieron indexar en Qdrant: %s", exc)
                if copied_now:
                    try:
                        store_store_products(text, copied_now, max_items=max_items, qdrant=qdrant)
                    except Exception:
                        logger.debug("No se pudo cachear por tienda", exc_info=True)
                if not stopped:
                    store_search_result(
                        text,
                        source=source,
                        stores=chosen,
                        max_items=max_items,
                        price_band=price_band,
                        result=result,
                        qdrant=qdrant,
                    )
            except Exception:
                logger.debug("Post-búsqueda falló", exc_info=True)
            finally:
                if store is not None:
                    try:
                        store.close()
                    except Exception:
                        pass

        threading.Thread(target=run, daemon=True, name="search-finish").start()

    def elapsed() -> float:
        return time.monotonic() - started_at

    def last_offer_count() -> int:
        payload = ((last_snap[0] or {}).get("result") or {})
        return int(payload.get("offer_count") or 0)

    def wait_timeout(default: float = 0.25) -> float:
        if released or _cancelled(cancel):
            return default
        if last_offer_count() < READY_EARLY_OFFERS:
            return default
        remain = READY_EARLY_SECONDS - elapsed()
        if remain <= 0:
            return min(default, 0.05)
        return min(default, max(0.01, remain))

    def schedule_thumbs(rows: list[dict[str, Any]] | None) -> None:
        if thumb_pool is None or repo is None or _cancelled(cancel):
            return
        try:
            pending = repo.missing_thumbnails(
                thumb_targets(rows, seen=thumb_seen, limit=thumbs.default_limit())
            )
        except Exception:
            logger.debug("No se pudieron listar miniaturas pendientes", exc_info=True)
            return
        for key, url in pending:
            if _cancelled(cancel):
                return
            thumb_futures[thumb_pool.submit(thumbs.build_thumbnail, url)] = key

    def drain_thumbs(*, block: float) -> Iterator[dict[str, Any]]:
        if not thumb_futures:
            return
        finished, _left = wait(set(thumb_futures), timeout=block, return_when=FIRST_COMPLETED)
        batch: dict[tuple[str, str], dict[str, Any]] = {}
        for future in finished:
            key = thumb_futures.pop(future)
            if future.cancelled() or _cancelled(cancel):
                continue
            try:
                thumb = future.result()
            except Exception:
                thumb = None
            if thumb:
                batch[key] = thumb
        if not batch:
            return
        try:
            repo.save_thumbnails(batch)
        except Exception:
            logger.debug("No se pudieron guardar miniaturas en vivo", exc_info=True)
            return
        keys = mark_thumbs(last_snap[0].get("result") or {}, list(batch)) if last_snap[0] else []
        if last_visible[0] is not None:
            mark_thumbs(last_visible[0], list(batch))
        if keys:
            yield {"type": "thumbs", "thumbs": keys}

    def maybe_emit_ready() -> Iterator[dict[str, Any]]:
        nonlocal released
        if released or _cancelled(cancel):
            return
        payload = (last_snap[0] or {}).get("result") or {}
        offers = int(payload.get("offer_count") or 0)
        if not search_is_ready(progress, offers, elapsed()):
            return
        released = True
        if offers >= READY_EARLY_OFFERS:
            payload = dict(payload)
            payload["live_label"] = "Mostrando 10+ · sigue buscando…"
        yield {"type": "ready", "result": payload}

    def emit_progress(snap: dict[str, Any]) -> Iterator[dict[str, Any]]:
        nonlocal released, visible_done
        last_snap[0] = snap
        yield snap
        schedule_thumbs((snap.get("result") or {}).get("rows"))
        yield from drain_thumbs(block=0.0)
        if _cancelled(cancel):
            return
        yield from maybe_emit_ready()
        complete = all(item.get("state") in _DONE_STATES for item in progress)
        if not visible_done and (complete if wait_for_all else wait_set_done(progress)):
            visible_done = True
            result = visible_result(cancelled=False)
            last_visible[0] = result
            reasons = result.get("discarded_reasons") or []
            if reasons:
                logger.info(
                    "Fuera de «%s»: %s",
                    text,
                    " · ".join(f"{item['count']} {item['reason']}" for item in reasons),
                )
            yield {"type": "done", "result": result}
            if background_side_effects:
                launch_side_effects()

    def drain_optional(*, block: float) -> Iterator[dict[str, Any]]:
        yield from drain_thumbs(block=0.0)
        if not optional_futures:
            return
        finished, _left = wait(set(optional_futures), timeout=block, return_when=FIRST_COMPLETED)
        for future in finished:
            store_id = optional_futures.pop(future)
            if future.cancelled():
                if by_id[store_id].get("state") in {"pending", "running"}:
                    by_id[store_id]["state"] = "skip"
                continue
            try:
                found, error = future.result()
            except Exception as exc:
                found, error = [], str(exc)
            apply_store_result(store_id, found, error)
            yield from emit_progress(snapshot())

    if db_snapshot is not None:
        yield from emit_progress(db_snapshot)

    if optional_ids and not _cancelled(cancel):
        optional_pool = ThreadPoolExecutor(max_workers=max(1, len(optional_ids)))
        for store_id in optional_ids:
            optional_futures[
                optional_pool.submit(
                    scrape_store,
                    store_id,
                    text,
                    max_items=max_items,
                    delay=delay,
                    timeout=timeout,
                    attempts=1,
                )
            ] = store_id
            by_id[store_id]["state"] = "running"
        yield from emit_progress(snapshot())

    def run_wave(store_ids: list[str], *, attempts: int) -> Iterator[dict[str, Any]]:
        if not store_ids or _cancelled(cancel):
            yield from drain_optional(block=0.0)
            return
        remaining = list(store_ids)
        workers = max(1, min(STORE_WORKERS, len(remaining)))
        pool = ThreadPoolExecutor(max_workers=workers)
        futures: dict[Any, str] = {}
        try:
            while remaining or futures:
                yield from drain_optional(block=0.0)
                if _cancelled(cancel):
                    remaining.clear()
                    if not futures:
                        break
                    finished, _left = wait(set(futures), timeout=0.05, return_when=FIRST_COMPLETED)
                    if not finished:
                        break
                else:
                    started = False
                    while remaining and len(futures) < workers:
                        store_id = remaining.pop(0)
                        future = pool.submit(
                            scrape_store,
                            store_id,
                            text,
                            max_items=max_items,
                            delay=delay,
                            timeout=timeout,
                            attempts=attempts,
                        )
                        futures[future] = store_id
                        by_id[store_id]["state"] = "running"
                        started = True
                    if started:
                        yield from emit_progress(snapshot())
                    if not futures:
                        break
                    finished, _left = wait(set(futures), timeout=wait_timeout(), return_when=FIRST_COMPLETED)
                    if not finished:
                        yield from drain_thumbs(block=0.0)
                        yield from maybe_emit_ready()
                        continue
                for future in finished:
                    store_id = futures.pop(future)
                    if future.cancelled():
                        continue
                    try:
                        found, error = future.result()
                    except Exception as exc:
                        found, error = [], str(exc)
                    apply_store_result(store_id, found, error)
                    yield from emit_progress(snapshot())
        finally:
            _shutdown_pool(pool, cancel)

    if wait_ids and not _cancelled(cancel):
        yield from run_wave(wait_ids, attempts=1)
        failed = [
            store_id
            for store_id in wait_ids
            if by_id[store_id].get("state") == "error"
            and not _is_timeout_error(by_id[store_id].get("error"))
            and not is_optional_store(store_id)
        ]
        if failed and not _cancelled(cancel):
            logger.info(
                "Reintentando %s tiendas con error: %s",
                len(failed),
                ", ".join(titles.get(store_id, store_id) for store_id in failed),
            )
            for store_id in failed:
                by_id[store_id]["state"] = "pending"
                by_id[store_id].pop("error", None)
            errors[:] = [row for row in errors if row["store"] not in set(failed)]
            yield from emit_progress(snapshot())
            yield from run_wave(failed, attempts=1)

    while (optional_futures or thumb_futures) and not _cancelled(cancel):
        events = list(drain_optional(block=0.25 if optional_futures else 0.0))
        if events:
            yield from events
        if thumb_futures:
            yield from drain_thumbs(block=0.25 if not optional_futures else 0.0)

    stopped = _cancelled(cancel)
    if stopped:
        for item in progress:
            if item.get("state") in {"pending", "running"}:
                item["state"] = "skip"
        for future in list(optional_futures):
            optional_futures.pop(future, None)
            future.cancel()
        for future in list(thumb_futures):
            thumb_futures.pop(future, None)
            future.cancel()

    if optional_pool is not None:
        optional_pool.shutdown(wait=False, cancel_futures=_cancelled(cancel))
    if thumb_pool is not None:
        thumb_pool.shutdown(wait=False, cancel_futures=_cancelled(cancel))

    if not visible_done:
        result = visible_result(cancelled=stopped)
        last_visible[0] = result
        reasons = result.get("discarded_reasons") or []
        if reasons:
            logger.info(
                "Fuera de «%s»: %s",
                text,
                " · ".join(f"{item['count']} {item['reason']}" for item in reasons),
            )
        for message in warnings:
            logger.warning("%s", message)
        yield {"type": "done", "result": result}
        if not stopped:
            launch_side_effects()
    elif not stopped:
        result = visible_result(cancelled=False)
        last_visible[0] = result
        yield {"type": "snapshot", "result": result}
        if background_side_effects:
            launch_side_effects()

    if repo is not None:
        repo.close()
    yield {"type": "end", "result": last_visible[0] or visible_result(cancelled=stopped)}


def search_products(
    query: str,
    *,
    source: str = "both",
    stores: list[str] | None = None,
    max_items: int = 5,
    delay: float = 1.0,
    timeout: float = SEARCH_TIMEOUT,
    persist: bool = True,
    persist_meta: dict[str, Any] | None = None,
    price_band: bool = True,
    fresh: bool = False,
    background_side_effects: bool = True,
    wait_for_all: bool = False,
    preferred_stores: list[str] | None = None,
    excluded_stores: list[str] | None = None,
    recover_underfilled_db: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    for event in iter_search_events(
        query,
        source=source,
        stores=stores,
        max_items=max_items,
        delay=delay,
        timeout=timeout,
        persist=persist,
        persist_meta=persist_meta,
        price_band=price_band,
        fresh=fresh,
        background_side_effects=background_side_effects,
        wait_for_all=wait_for_all,
        preferred_stores=preferred_stores,
        excluded_stores=excluded_stores,
        recover_underfilled_db=recover_underfilled_db,
    ):
        if event.get("type") == "done":
            if not wait_for_all:
                return event["result"]
            result = event["result"]
        elif event.get("type") == "end" and event.get("result") is not None:
            result = event["result"]
    if result is not None:
        return result
    raise ValueError("La búsqueda no produjo resultados.")
