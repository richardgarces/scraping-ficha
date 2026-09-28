from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_int, strip_html
from retail.registry import StoreSpec, register

PAGE_SIZE = 10


def normalize_vtex_ft(query: str) -> str:
    """Quita huecos raros. `mini led` queda en una frase, no en un `ft` crudo con espacios."""
    return " ".join(str(query or "").split())


def encode_vtex_query(params: dict[str, Any]) -> str:
    """Query string con `ft` en %20. Un espacio crudo en `ft=` dispara HTTP 400 (WAF)."""
    parts: list[str] = []
    for key, value in params.items():
        if value is None or key == "_path":
            continue
        raw = normalize_vtex_ft(str(value)) if key == "ft" else str(value)
        parts.append(f"{quote(str(key), safe='')}={quote(raw, safe='')}")
    return "&".join(parts)


SORT_MAP = {
    "recomendados": "OrderByScoreDESC",
    "precio_asc": "OrderByPriceASC",
    "precio_desc": "OrderByPriceDESC",
    "rating": "OrderByReviewRateDESC",
}

# Intelligent Search usa otro vocabulario de orden.
INTEL_SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price:asc",
    "precio_desc": "price:desc",
    "rating": "release:desc",
}


def parse_vtex_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and (parts[-1] == "p" or parsed.path.endswith("/p")):
            slug = parts[-2] if parts[-1] == "p" else parts[-1]
            return Target(kind="product", product_id=slug, raw_url=raw)
        if parts and parts[0] == "search":
            return Target(kind="search", query=parts[1] if len(parts) > 1 else None, raw_url=raw)
        if parts:
            return Target(kind="category", category_id="/".join(parts), category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.strip("/").split("/")[-1])
    return Target(kind="search", query=raw)


def listing_item_to_product(
    item: dict[str, Any],
    *,
    store_id: str,
    base: str,
    default_brand: str | None = None,
    source: str | None = None,
) -> Product:
    variants = item.get("items") or []
    sku = variants[0] if variants else {}
    sellers = sku.get("sellers") or []
    seller = sellers[0] if sellers else {}
    offer = seller.get("commertialOffer") or {}
    current = parse_int(offer.get("Price"))
    normal = parse_int(offer.get("ListPrice"))
    stock = parse_int(offer.get("AvailableQuantity"))
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    gallery = sku.get("images") or []
    image = first_image_url(gallery)
    cats = item.get("categories") or []
    link = item.get("linkText") or ""
    return Product(
        product_id=str(item.get("productId") or ""),
        sku_id=str(sku.get("itemId") or item.get("productReference") or item.get("productId") or ""),
        name=str(item.get("productName") or item.get("productTitle") or "").strip(),
        brand=item.get("brand") or default_brand,
        url=f"{base}/{link}/p" if link else item.get("link"),
        seller=seller.get("sellerName") or default_brand,
        seller_id=str(seller.get("sellerId")) if seller.get("sellerId") is not None else None,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        image_urls=gallery,
        category=str(cats[0]).strip("/") if cats else None,
        category_id=str(item.get("categoryId") or ""),
        description=strip_html(item.get("description") or item.get("metaTagDescription")),
        specifications={
            key: ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            for key in item.get("allSpecifications") or []
            if (value := item.get(key))
        },
        store=store_id,
        source=source,
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if stock > 0 else "Sin stock") if stock is not None else None,
        variants=[
            {
                "id": raw.get("itemId"),
                "sku": raw.get("itemId"),
                "name": raw.get("nameComplete") or raw.get("name"),
                "stock": (((raw.get("sellers") or [{}])[0].get("commertialOffer") or {}).get("AvailableQuantity")),
                "available": None,
            }
            for raw in variants
            if isinstance(raw, dict) and (raw.get("sellers") or [])
        ],
    )


def make_vtex_store(
    *,
    store_id: str,
    title: str,
    site: str,
    base: str,
    default_brand: str | None = None,
    category_help: str = "Slug VTEX, por ejemplo ropa/polerones",
    intelligent_search: bool = False,
    group: str | None = None,
    product_by_path: bool = False,
):
    headers = {
        "Origin": base,
        "Referer": f"{base}/",
        "Accept": "application/json",
        "REST-Range": "resources=0-9",
    }
    search_api = f"{base}/api/catalog_system/pub/products/search"
    intel_api = f"{base}/api/io/_v/api/intelligent-search/product_search"
    sort_map = INTEL_SORT_MAP if intelligent_search else SORT_MAP

    @register(
        StoreSpec(
            id=store_id,
            title=title,
            site=site,
            sort_map=sort_map,
            category_help=category_help,
            platform="vtex",
            group=group,
        )
    )
    class VtexStore(StoreClient):
        def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
            super().__init__(delay=delay, timeout=timeout, retries=retries)
            self.http = HttpSession(timeout=timeout, headers=headers)
            self._last_request = 0.0

        def close(self) -> None:
            self.http.close()

        def parse_target(self, value: str) -> Target:
            return parse_vtex_target(value)

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
                products.append(
                    listing_item_to_product(
                        item,
                        store_id=store_id,
                        base=base,
                        default_brand=default_brand,
                        source=parsed.kind,
                    )
                )
                if max_items is not None and len(products) >= max_items:
                    break
            return products

        def _product(self, product_id: str) -> Product:
            if product_id.isdigit():
                items = self._catalog_search({"fq": f"productId:{product_id}", "_from": 0, "_to": 0})
            else:
                items = self._catalog_search({"fq": f"alternateIds_Link:{product_id}", "_from": 0, "_to": 0})
                if not items:
                    items = self._catalog_search({"ft": product_id, "_from": 0, "_to": 0})
                if not items and product_by_path:
                    items = self._catalog_search({"_path": f"{product_id}/p", "_from": 0, "_to": 0})
            if not items:
                raise HttpError(f"Producto {title} no encontrado: {product_id}")
            return listing_item_to_product(
                items[0],
                store_id=store_id,
                base=base,
                default_brand=default_brand,
                source="product",
            )

        def _iter_listing(
            self,
            target: Target,
            *,
            max_pages: int | None,
            max_items: int | None,
            sort: str | None,
        ) -> Iterator[dict[str, Any]]:
            page = 0
            yielded = 0
            while True:
                start = page * PAGE_SIZE
                items = self._search(self._params(target, start, sort))
                if not items:
                    break
                for item in items:
                    yield item
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
                if max_pages is not None and page + 1 >= max_pages:
                    break
                if len(items) < PAGE_SIZE:
                    break
                page += 1

        def _params(self, target: Target, start: int, sort: str | None) -> dict[str, Any]:
            if intelligent_search and target.kind == "search" and target.query:
                params: dict[str, Any] = {
                    "_intel": True,
                    "query": normalize_vtex_ft(target.query),
                    "page": start // PAGE_SIZE + 1,
                    "count": PAGE_SIZE,
                }
                sort_value = INTEL_SORT_MAP.get(sort or "", sort)
                if sort_value:
                    params["sort"] = sort_value
                return params
            params = {"_from": start, "_to": start + PAGE_SIZE - 1}
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["O"] = sort_value
            if target.kind == "search" and target.query:
                params["ft"] = target.query
            elif target.kind == "category" and target.category_id:
                params["_path"] = target.category_id.strip("/")
            else:
                raise ValueError(f"No se puede scrapear el objetivo: {target}")
            return params

        def _search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
            if params.pop("_intel", False):
                return self._intel_search(params)
            return self._catalog_search(params)

        def _intel_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
            last_error: Exception | None = None
            for attempt in range(1, self.retries + 1):
                self._throttle()
                status, _ct, body = self.http.get(intel_api, params=params)
                if status == 200:
                    text = (body or "").strip()
                    if not text:
                        return []
                    try:
                        payload = json.loads(body)
                    except ValueError as exc:
                        last_error = HttpError(f"JSON inválido en {title}: {exc}", status)
                    else:
                        if isinstance(payload, dict):
                            products = payload.get("products") or []
                            if isinstance(products, list):
                                return [item for item in products if isinstance(item, dict)]
                        last_error = HttpError(f"Respuesta {title} inesperada", status)
                else:
                    last_error = HttpError(f"HTTP {status} en {title}", status)
                if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(min(8.0, self.delay * attempt * 2))
                    continue
                break
            raise last_error or HttpError(f"Fallo al consultar {title}")

        def _catalog_search(self, params: dict[str, Any]) -> list[dict[str, Any]]:
            path = params.pop("_path", None)
            query = encode_vtex_query(params)
            url = f"{search_api}/{path}" if path else search_api
            if query:
                url = f"{url}?{query}"
            last_error: Exception | None = None
            for attempt in range(1, self.retries + 1):
                self._throttle()
                status, _ct, body = self.http.get(url)
                if status in {200, 206}:
                    text = (body or "").strip()
                    if not text or text == "[]":
                        return []
                    try:
                        payload = json.loads(body)
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

    VtexStore.__name__ = "".join(part.capitalize() for part in store_id.split("_")) + "Store"
    VtexStore.__qualname__ = VtexStore.__name__
    return VtexStore
