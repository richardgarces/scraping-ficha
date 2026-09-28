"""Busca en segundo plano el mismo producto de una ficha en otras tiendas.

No bloquea el render: el visor abre el stream después de pintar la ficha.
La identidad es la de `compare` (envase incluido: 1 unidad no es 6).
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Iterator

from retail.compare import compare_code, compare_products, is_catalog_mirror, same_product_pack
from retail.index.products import stores_for, unmatched_fallback_stores
from retail.models import Product
from retail.registry import list_stores
from retail.relevance import fold
from retail.search import OPTIONAL_STORES, SEARCH_TIMEOUT, STORE_WORKERS, scrape_store

logger = logging.getLogger(__name__)

# No barrer las 150 cadenas: primero las que el índice enruta, y un tope.
SWEEP_STORE_CAP = 24
SWEEP_MAX_ITEMS = 6
PREFERRED_STORES = (
    "falabella",
    "paris",
    "ripley",
    "lider",
    "sodimac",
    "easy",
    "tottus",
    "mercadolibre",
    "unimarc",
    "ahumada",
    "cruzverde",
    "preunic",
)

_notice_lock = threading.Lock()
_noticed: set[tuple[str, str, str, str, int]] = set()


def clp(value: int) -> str:
    return f"${int(value):,}".replace(",", ".")


def lower_price_message(store_title: str, price: int) -> str:
    return f"Encontramos un precio menor en {store_title}: {clp(price)}"


def as_product(value: Product | dict[str, Any]) -> Product:
    if isinstance(value, Product):
        return value
    return Product.from_dict(value)


def search_query(document: dict[str, Any] | Product) -> str:
    item = as_product(document)
    name = " ".join((item.name or "").split())
    brand = " ".join((item.brand or "").split())
    text = name
    if brand and brand.lower() not in name.lower():
        text = f"{brand} {name}".strip()
    return text[:160]


def scope_other_stores(query: str, current: str, available: list[str]) -> list[str]:
    """Tiendas distintas a la ficha, acotadas por el índice o por el fallback."""
    text = (query or "").strip()
    if not text or not available:
        return []
    routed: list[str] = []
    try:
        routed = list(stores_for(text, available) or [])
    except Exception:
        logger.debug("No se pudo enrutar tiendas de la ficha", exc_info=True)
        routed = []
    chosen = routed or list(unmatched_fallback_stores(available, query=text))
    current_id = (current or "").lower().strip()
    pool = [store_id for store_id in chosen if store_id and store_id != current_id]
    return _prioritize(pool)


def _prioritize(stores: list[str], cap: int = SWEEP_STORE_CAP) -> list[str]:
    optional = [store_id for store_id in stores if store_id in OPTIONAL_STORES]
    core = [store_id for store_id in stores if store_id not in OPTIONAL_STORES]
    preferred = [store_id for store_id in PREFERRED_STORES if store_id in core]
    rest = [store_id for store_id in core if store_id not in preferred]
    room = max(0, cap - len(optional))
    return (preferred + rest)[:room] + optional


def same_comparable(anchor: Product | dict[str, Any], candidate: Product | dict[str, Any]) -> bool:
    """Misma identidad y mismo envase. 1 unidad no calza con 6."""
    left = as_product(anchor)
    right = as_product(candidate)
    if not left.name or not right.name or not right.store:
        return False
    if left.store and left.store == right.store and left.product_id and left.product_id == right.product_id:
        return False
    if not same_product_pack(left, right):
        return False
    if is_catalog_mirror(left.to_dict(flatten_specs=False), right.to_dict(flatten_specs=False)):
        return False
    groups = compare_products([left, right])
    if len(groups) != 1:
        return False
    keys = {(row.get("store"), row.get("product_id")) for row in groups[0].get("offers") or []}
    return (left.store, left.product_id) in keys and (right.store, right.product_id) in keys


def offer_decision(
    anchor: Product | dict[str, Any],
    candidate: Product | dict[str, Any],
    *,
    best_price: int | None,
    shown: set[tuple[str, int]] | None = None,
) -> dict[str, Any] | None:
    """Misma identidad entra a la tabla. El aviso solo si el precio es menor."""
    if not same_comparable(anchor, candidate):
        return None
    product = as_product(candidate)
    if product.price in (None, 0):
        return None
    price = int(product.price)
    threshold = int(best_price) if best_price not in (None, 0) else None
    already = (product.store, price) in (shown or set())
    notice = threshold is not None and price < threshold and not already
    return {
        "add": True,
        "notice": notice,
        "price": price,
        "store": product.store,
        "product_id": product.product_id,
        "name": product.name,
        "url": product.url,
        "brand": product.brand,
    }


def follows_product(watches: list[dict[str, Any]] | None, document: dict[str, Any]) -> bool:
    store = str(document.get("store") or "")
    product_id = str(document.get("product_id") or "")
    code = str(document.get("compare_code") or "")
    name = fold(str(document.get("name") or ""))
    for watch in watches or []:
        if watch.get("active") is False:
            continue
        if store and product_id and str(watch.get("store") or "") == store and str(watch.get("product_id") or "") == product_id:
            return True
        if code and watch.get("compare_code") and str(watch.get("compare_code")) == code:
            return True
        query = fold(str(watch.get("query") or ""))
        if len(query) >= 8 and name and (query == name or query in name):
            return True
    return False


def claim_notice(user_id: str, anchor_store: str, anchor_id: str, store: str, price: int) -> bool:
    """No reenviar el mismo aviso Telegram de tienda+precio en este proceso."""
    key = (str(user_id or ""), str(anchor_store or ""), str(anchor_id or ""), str(store or ""), int(price))
    with _notice_lock:
        if key in _noticed:
            return False
        _noticed.add(key)
        if len(_noticed) > 4000:
            _noticed.clear()
            _noticed.add(key)
        return True


def _titles() -> dict[str, str]:
    return {spec.id: spec.title for spec in list_stores()}


def _known_prices(document: dict[str, Any], others: list[dict[str, Any]]) -> tuple[int | None, set[tuple[str, int]]]:
    prices: list[int] = []
    shown: set[tuple[str, int]] = set()
    if document.get("price"):
        prices.append(int(document["price"]))
    for item in others:
        if not item.get("price"):
            continue
        price = int(item["price"])
        prices.append(price)
        shown.add((str(item.get("store") or ""), price))
    return (min(prices) if prices else None), shown


def _persist(repo: Any, document: dict[str, Any], product: Product, query: str) -> str:
    code = str(document.get("compare_code") or "")
    if not code:
        groups = compare_products([as_product(document), product])
        code = groups[0]["compare_code"] if len(groups) == 1 else compare_code(product)
    offer = product.to_dict(flatten_specs=False)
    offer["compare_code"] = code
    repo.upsert_offers([offer], query, extra={"source": "ficha_sweep"})
    return code


def _maybe_telegram(repo: Any, user: dict[str, Any] | None, document: dict[str, Any], product: Product, message: str) -> None:
    if not user or not user.get("id"):
        return
    try:
        watches = repo.list_watches(active_only=True, user_id=user["id"])
        raw = repo.find_user_by_id(user["id"]) or {}
    except Exception:
        logger.debug("No se pudieron leer seguimientos de la ficha", exc_info=True)
        return
    from retail.batch.alerts import _chat_values, product_page_url, send_to_user

    if not follows_product(watches, document) or not _chat_values(raw):
        return
    if not claim_notice(user["id"], document.get("store") or "", document.get("product_id") or "", product.store, int(product.price or 0)):
        return
    from retail.short_links import short_product_url

    ficha = short_product_url(repo, product.store, product.product_id)
    text = f"{message}\n{product.name or document.get('name') or ''}"
    if ficha:
        text += f"\n🔗 Ficha: {ficha}"
    text = text.strip()

    def send() -> None:
        try:
            send_to_user(raw, text, image_url=product.image_url)
        except Exception:
            logger.debug("Telegram de ficha no salió", exc_info=True)

    threading.Thread(target=send, daemon=True, name="ficha-telegram").start()


def iter_ficha_sweep(
    document: dict[str, Any],
    others: list[dict[str, Any]],
    *,
    repo: Any,
    user: dict[str, Any] | None = None,
    available: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Eventos SSE: start, offer (tabla + aviso si es menor), done."""
    query = search_query(document)
    store_ids = available if available is not None else [spec.id for spec in list_stores()]
    stores = scope_other_stores(query, str(document.get("store") or ""), store_ids)
    yield {"type": "start", "query": query, "stores": stores, "background": True}
    if not stores or not query:
        yield {"type": "done", "found": 0}
        return

    best, shown = _known_prices(document, others)
    titles = _titles()
    found = 0
    pool = ThreadPoolExecutor(max_workers=max(1, min(STORE_WORKERS, len(stores))))
    futures = {
        pool.submit(
            scrape_store,
            store_id,
            query,
            max_items=SWEEP_MAX_ITEMS,
            delay=0.0,
            timeout=SEARCH_TIMEOUT,
        ): store_id
        for store_id in stores
    }
    try:
        for future in as_completed(futures):
            try:
                products, _error = future.result()
            except Exception:
                logger.debug("Barrido de ficha falló en una tienda", exc_info=True)
                continue
            for product in products:
                decision = offer_decision(document, product, best_price=best, shown=shown)
                if not decision:
                    continue
                code = ""
                try:
                    code = _persist(repo, document, product, query)
                except Exception:
                    logger.debug("No se pudo guardar la oferta de la ficha", exc_info=True)
                shown.add((product.store, decision["price"]))
                payload = product.to_dict(flatten_specs=False)
                from retail.store_display import display_store

                payload["display_store"], payload["store_title"] = display_store(payload, titles)
                payload["compare_code"] = code or document.get("compare_code")
                payload["price"] = decision["price"]
                event: dict[str, Any] = {"type": "offer", "offer": payload, "notice": False}
                if decision["notice"]:
                    title = payload["store_title"]
                    message = lower_price_message(title, decision["price"])
                    event["notice"] = True
                    event["message"] = message
                    best = decision["price"]
                    _maybe_telegram(repo, user, document, product, message)
                found += 1
                yield event
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    yield {"type": "done", "found": found}
