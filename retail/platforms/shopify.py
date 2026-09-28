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

SORT_MAP = {
    "recomendados": "manual",
    "precio_asc": "price-ascending",
    "precio_desc": "price-descending",
}


def parse_shopify_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] == "products":
            return Target(kind="product", product_id=parts[1] if len(parts) > 1 else None, raw_url=raw)
        if parts and parts[0] == "collections":
            slug = parts[1] if len(parts) > 1 else None
            return Target(kind="category", category_id=slug, category_name=slug, raw_url=raw)
        if (parts and parts[0] == "search") or query.get("q"):
            return Target(kind="search", query=(query.get("q") or [None])[0], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    return Target(kind="search", query=raw)


def listing_item_to_product(item: dict[str, Any], *, store_id: str, base: str, source: str | None = None) -> Product:
    variants = item.get("variants") or []
    variant = variants[0] if variants else {}
    finite_inventory = all(item.get("inventory_policy") != "continue" for item in variants)
    stock_values = [parse_int(item.get("inventory_quantity")) for item in variants]
    known_stock = [value for value in stock_values if value is not None]
    stock = sum(max(0, value) for value in known_stock) if finite_inventory and known_stock and len(known_stock) == len(variants) else None
    available = any(bool(item.get("available")) for item in variants) if variants else None
    raw_current = item.get("price") if item.get("price") not in (None, "") else variant.get("price")
    raw_compare = (
        item.get("compare_at_price")
        if item.get("compare_at_price") not in (None, "")
        else variant.get("compare_at_price")
    )
    current = parse_int(raw_current)
    compare = parse_int(raw_compare)
    # "19990.00" pierde el punto en parse_int (1999000). Un entero "1389990" ya está en CLP.
    if current is not None and current > 1000_000 and "." in str(raw_current):
        current = current // 100
    if compare is not None and compare > 1000_000 and "." in str(raw_compare):
        compare = compare // 100
    if current is not None and current < 1000 and str(item.get("price") or "").isdigit() is False:
        # Shopify suggest sometimes returns price as "12990.00"
        current = parse_int(str(item.get("price") or "").split(".")[0])
    discount = None
    if compare and current and compare > current:
        discount = round((compare - current) * 100 / compare)
    gallery = [item.get("images"), item.get("image"), item.get("featured_image")]
    image = first_image_url(gallery)
    handle = item.get("handle") or ""
    url = item.get("url")
    if url and str(url).startswith("/"):
        url = f"{base}{url}"
    elif handle:
        url = f"{base}/products/{handle}"
    return Product(
        product_id=str(item.get("id") or handle),
        sku_id=str(variant.get("sku") or item.get("id") or handle),
        name=str(item.get("title") or "").strip(),
        brand=item.get("vendor") or None,
        url=url,
        seller=item.get("vendor"),
        price_internet=current,
        price_normal=compare or current,
        price=current,
        discount_percent=discount,
        image_url=image,
        image_urls=gallery,
        category=(item.get("product_type") or item.get("type") or None),
        description=strip_html(item.get("body_html") or item.get("description")),
        store=store_id,
        source=source,
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if available else "Sin stock") if available is not None else None,
        variants=[
            {
                "id": raw.get("id"),
                "sku": raw.get("sku"),
                "name": raw.get("title"),
                "stock": raw.get("inventory_quantity"),
                "available": raw.get("available"),
            }
            for raw in variants
            if isinstance(raw, dict)
        ],
    )


def make_shopify_store(*, store_id: str, title: str, site: str, base: str, category_help: str = "Handle de colección Shopify"):
    headers = {
        "Origin": base,
        "Referer": f"{base}/",
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    }

    @register(
        StoreSpec(
            id=store_id,
            title=title,
            site=site,
            sort_map=SORT_MAP,
            category_help=category_help,
            platform="shopify",
        )
    )
    class ShopifyStore(StoreClient):
        def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
            super().__init__(delay=delay, timeout=timeout, retries=retries)
            self.http = HttpSession(timeout=timeout, headers=headers)
            self._last_request = 0.0

        def close(self) -> None:
            self.http.close()

        def parse_target(self, value: str) -> Target:
            return parse_shopify_target(value)

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
            if parsed.kind == "product" and parsed.product_id:
                return [self._product(parsed.product_id)]
            products: list[Product] = []
            for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
                products.append(listing_item_to_product(item, store_id=store_id, base=base, source=parsed.kind))
                if max_items is not None and len(products) >= max_items:
                    break
            return products

        def _product(self, product_id: str) -> Product:
            payload = self._json(f"{base}/products/{product_id}.json")
            item = payload.get("product") if isinstance(payload, dict) else None
            if not isinstance(item, dict):
                raise HttpError(f"Producto {title} no encontrado: {product_id}")
            return listing_item_to_product(item, store_id=store_id, base=base, source="product")

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
                items = self._page(target, page, sort)
                if not items:
                    break
                for item in items:
                    yield item
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
                if max_pages is not None and page >= max_pages:
                    break
                if len(items) < 30:
                    break
                page += 1

        def _page(self, target: Target, page: int, sort: str | None) -> list[dict[str, Any]]:
            if target.kind == "search" and target.query:
                payload = self._json(
                    f"{base}/search/suggest.json",
                    {
                        "q": target.query,
                        "resources[type]": "product",
                        "resources[limit]": 50,
                        "resources[options][unavailable_products]": "last",
                    },
                )
                products = (((payload.get("resources") or {}).get("results") or {}).get("products") or [])
                return [item for item in products if isinstance(item, dict)]
            params: dict[str, Any] = {"limit": 30, "page": page}
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["sort_by"] = sort_value
            if target.kind == "category" and target.category_id:
                payload = self._json(f"{base}/collections/{target.category_id}/products.json", params)
            else:
                payload = self._json(f"{base}/products.json", params)
            return [item for item in (payload.get("products") or []) if isinstance(item, dict)]

        def _json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
            last_error: Exception | None = None
            for attempt in range(1, self.retries + 1):
                self._throttle()
                status, _ct, body = self.http.get(url, params=params)
                if status == 200 and body:
                    try:
                        data = json.loads(body)
                    except ValueError as exc:
                        last_error = HttpError(f"JSON inválido en {title}: {exc}", status)
                    else:
                        if isinstance(data, dict):
                            return data
                        last_error = HttpError(f"Respuesta inesperada en {title}", status)
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

    ShopifyStore.__name__ = "".join(part.capitalize() for part in store_id.split("_")) + "Store"
    ShopifyStore.__qualname__ = ShopifyStore.__name__
    return ShopifyStore
