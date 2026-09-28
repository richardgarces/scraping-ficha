from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_int, strip_html
from retail.registry import StoreSpec, register

PAGE_SIZE = 10
SORT_MAP = {
    "recomendados": "popularity",
    "precio_asc": "price",
    "precio_desc": "price",
}


def parse_woocommerce_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] in {"producto", "product", "products"} and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        if query.get("s") or query.get("q") or (parts and parts[0] == "search"):
            term = (query.get("s") or query.get("q") or [None])[0]
            return Target(kind="search", query=term, raw_url=raw)
        if parts and parts[0] in {"categoria-producto", "product-category"}:
            return Target(kind="category", category_id=parts[1] if len(parts) > 1 else None, raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def listing_item_to_product(
    item: dict[str, Any],
    *,
    store_id: str,
    seller: str | None = None,
    source: str | None = None,
) -> Product:
    prices = item.get("prices") or {}
    current = parse_int(prices.get("sale_price") or prices.get("price"))
    normal = parse_int(prices.get("regular_price") or prices.get("price")) or current
    minor = parse_int(prices.get("currency_minor_unit")) or 0
    if minor and current:
        current = current // (10**minor)
    if minor and normal:
        normal = normal // (10**minor)
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    gallery = item.get("images") or []
    image = first_image_url(gallery)
    sku = str(item.get("sku") or "")
    cats = item.get("categories") or []
    category = None
    if cats and isinstance(cats[0], dict):
        category = cats[0].get("name")
    brands = item.get("brands") or []
    brand = None
    if brands and isinstance(brands[0], dict):
        brand = brands[0].get("name")
    raw_stock = item.get("stock_quantity")
    if raw_stock is None:
        raw_stock = item.get("low_stock_remaining")
    stock = parse_int(raw_stock)
    in_stock = item.get("is_in_stock")
    return Product(
        product_id=str(item.get("id") or sku),
        sku_id=sku or str(item.get("id") or ""),
        name=str(item.get("name") or "").strip(),
        brand=brand,
        url=item.get("permalink"),
        seller=seller,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        image_urls=gallery,
        category=category,
        description=strip_html(item.get("short_description") or item.get("description")),
        specifications={"ean": sku} if sku.isdigit() and len(sku) >= 8 else {},
        store=store_id,
        source=source,
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if in_stock else "Sin stock") if isinstance(in_stock, bool) else None,
    )


def make_woocommerce_store(
    *,
    store_id: str,
    title: str,
    site: str,
    base: str,
    category_help: str = "Slug WooCommerce, por ejemplo lacteos",
):
    headers = {
        "Origin": base,
        "Referer": f"{base}/",
        "Accept": "application/json",
    }
    search_api = f"{base}/wp-json/wc/store/v1/products"

    @register(
        StoreSpec(
            id=store_id,
            title=title,
            site=site,
            sort_map=SORT_MAP,
            category_help=category_help,
            platform="woocommerce",
        )
    )
    class WooStore(StoreClient):
        def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
            super().__init__(delay=delay, timeout=timeout, retries=retries)
            self.http = HttpSession(timeout=timeout, headers=headers)
            self._last_request = 0.0

        def close(self) -> None:
            self.http.close()

        def parse_target(self, value: str) -> Target:
            return parse_woocommerce_target(value)

        def scrape(
            self,
            target: str | Target,
            *,
            max_pages: int | None = 1,
            max_items: int | None = None,
            sort: str | None = None,
            detalle: bool = False,
        ) -> list[Product]:
            parsed = target if isinstance(target, Target) else self.parse_target(target)
            products: list[Product] = []
            for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
                product = listing_item_to_product(item, store_id=store_id, seller=title, source=parsed.kind)
                if parsed.kind == "product" and parsed.product_id:
                    needle = parsed.product_id.lower()
                    if needle not in {product.product_id, product.sku_id} and needle not in (product.url or "").lower():
                        continue
                products.append(product)
                if parsed.kind == "product":
                    break
                if max_items is not None and len(products) >= max_items:
                    break
            if parsed.kind == "product" and not products:
                raise HttpError(f"Producto {title} no encontrado: {parsed.product_id}")
            return products

        def _iter_listing(
            self,
            target: Target,
            *,
            max_pages: int | None,
            max_items: int | None,
            sort: str | None,
        ) -> Iterator[dict[str, Any]]:
            page = 1
            yielded = 0
            while True:
                rows = self._page(target, page, sort)
                if not rows:
                    break
                for row in rows:
                    yield row
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
                if max_pages is not None and page >= max_pages:
                    break
                if len(rows) < PAGE_SIZE:
                    break
                page += 1

        def _page(self, target: Target, page: int, sort: str | None) -> list[dict[str, Any]]:
            params: dict[str, Any] = {"page": page, "per_page": PAGE_SIZE}
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["orderby"] = sort_value
                if sort == "precio_desc":
                    params["order"] = "desc"
            if target.kind == "search" and target.query:
                params["search"] = target.query
            elif target.kind == "product" and target.product_id:
                if str(target.product_id).isdigit():
                    params["include"] = target.product_id
                else:
                    params["search"] = target.product_id
            elif target.kind == "category" and target.category_id:
                params["category"] = target.category_id
            else:
                raise ValueError(f"No se puede scrapear el objetivo: {target}")
            last_error: Exception | None = None
            for attempt in range(1, self.retries + 1):
                self._throttle()
                status, _ct, raw = self.http.get(search_api, params=params)
                if status == 200 and raw:
                    try:
                        payload = json.loads(raw.lstrip("\ufeff"))
                    except ValueError as exc:
                        last_error = HttpError(f"JSON inválido en {title}: {exc}", status)
                    else:
                        if isinstance(payload, list):
                            return [item for item in payload if isinstance(item, dict)]
                        last_error = HttpError(f"Respuesta {title} inesperada", status)
                else:
                    last_error = HttpError(f"HTTP {status} en {title}", status)
                if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(min(8.0, self.delay * attempt * 2))
                    continue
                break
            raise last_error or HttpError(f"Fallo al consultar {title}")

        def _throttle(self) -> None:
            if self.delay <= 0:
                return
            elapsed = time.monotonic() - self._last_request
            if self._last_request and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self._last_request = time.monotonic()

    WooStore.__name__ = "".join(part.capitalize() for part in store_id.split("_")) + "Store"
    WooStore.__qualname__ = WooStore.__name__
    return WooStore
