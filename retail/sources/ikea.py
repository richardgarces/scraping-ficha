from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_float, parse_int, strip_html
from retail.registry import StoreSpec, register

BASE = "https://www.ikea.com"
SITE = f"{BASE}/cl/es"
SEARCH_API = "https://sik.search.blue.cdtapps.com/cl/es/search-result-page"
CATEGORY_API = "https://sik.search.blue.cdtapps.com/cl/es/product-list-page"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{SITE}/",
    "Accept": "application/json",
}
PAGE_SIZE = 24
SORT_MAP = {
    "recomendados": "RELEVANCE",
    "precio_asc": "PRICE_LOW_TO_HIGH",
    "precio_desc": "PRICE_HIGH_TO_LOW",
    "rating": "RATING",
}


def parse_ikea_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q") or query.get("search"):
            term = (query.get("q") or query.get("search") or [None])[0]
            return Target(kind="search", query=term, raw_url=raw)
        if "cat" in parts:
            slug = parts[parts.index("cat") + 1] if parts[-1] != "cat" else parts[-1]
            cat_id = slug.rsplit("-", 1)[-1] if slug else None
            return Target(kind="category", category_id=cat_id, category_name=slug, raw_url=raw)
        if "p" in parts or (parts and parts[-1].replace("-", "").isdigit() is False and parts[-1][-8:].isdigit()):
            last = parts[-1]
            product_id = last.rsplit("-", 1)[-1] if "-" in last else last
            return Target(kind="product", product_id=product_id, raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit() and len(raw) == 8:
        return Target(kind="product", product_id=raw)
    if raw[:2].isalpha() and raw[2:].isdigit() and 4 <= len(raw) <= 8:
        return Target(kind="category", category_id=raw, category_name=raw)
    return Target(kind="search", query=raw)


def _sales_price(item: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    block = item.get("salesPrice") or {}
    current = parse_int(block.get("numeral"))
    previous = block.get("previous") or block.get("regular") or {}
    normal = parse_int(previous.get("numeral")) if isinstance(previous, dict) else None
    discount = None
    raw_discount = block.get("discount")
    if isinstance(raw_discount, dict):
        discount = parse_int(raw_discount.get("numeral") or raw_discount.get("percentage"))
    elif raw_discount not in (None, ""):
        discount = parse_int(raw_discount)
    if discount is None and normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    return current, normal or current, discount


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    product = item.get("product") if isinstance(item.get("product"), dict) else item
    current, normal, discount = _sales_price(product)
    ident = str(product.get("itemNo") or product.get("id") or product.get("itemNoGlobal") or "")
    name = " ".join(
        part for part in [str(product.get("name") or "").strip(), str(product.get("typeName") or "").strip()] if part
    )
    badge = product.get("badge") or {}
    return Product(
        product_id=ident,
        sku_id=str(product.get("itemNoGlobal") or ident),
        name=name,
        brand="IKEA",
        url=product.get("pipUrl") or (f"{SITE}/p/{ident}/" if ident else None),
        seller="IKEA",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        rating=parse_float(product.get("ratingValue")),
        reviews=parse_int(product.get("ratingCount")),
        image_url=product.get("mainImageUrl"),
        is_bestseller=str(badge.get("type") or "") == "TOP_SELLER",
        category=product.get("typeName") or product.get("filterClass"),
        description=strip_html(product.get("itemMeasureReferenceText")),
        store="ikea",
        source=source,
        scraped_at=now_iso(),
    )


def _listing_items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = payload.get("searchResultPage") or {}
    if page:
        main = ((page.get("products") or {}).get("main") or {})
        items = [item for item in (main.get("items") or []) if isinstance(item, dict)]
        return items, {
            "start": int(main.get("start") or 0),
            "end": int(main.get("end") or 0),
            "count": int(main.get("max") or 0),
        }
    plp = payload.get("productListPage") or {}
    window = plp.get("productWindow") or []
    items = [item if isinstance(item, dict) else {} for item in window]
    return items, {
        "start": 0,
        "end": len(items),
        "count": int(plp.get("productCount") or len(items)),
    }


@register(
    StoreSpec(
        id="ikea",
        title="IKEA Chile",
        site="www.ikea.com/cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría IKEA, por ejemplo fu002 (sale del final de /cat/sillas-fu002/)",
    )
)
class IkeaStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_ikea_target(value)

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
            products.append(listing_item_to_product(item, source=parsed.kind))
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, product_id: str) -> Product:
        items, _pagination = self._request(SEARCH_API, {"q": product_id, "size": 4})
        for item in items:
            product = item.get("product") if isinstance(item.get("product"), dict) else item
            ident = str(product.get("itemNo") or product.get("id") or "")
            if ident == product_id:
                return listing_item_to_product(item, source="product")
        if items:
            return listing_item_to_product(items[0], source="product")
        raise HttpError(f"Producto IKEA no encontrado: {product_id}")

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[dict[str, Any]]:
        yielded = 0
        items, _pagination = self._page(target, sort)
        for item in items:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                return

    def _page(self, target: Target, sort: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        params: dict[str, Any] = {"size": PAGE_SIZE}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        if target.kind == "search" and target.query:
            params["q"] = target.query
            return self._request(SEARCH_API, params)
        if target.kind == "category" and target.category_id:
            params["category"] = target.category_id
            return self._request(CATEGORY_API, params)
        raise ValueError(f"No se puede scrapear el objetivo: {target}")

    def _request(self, url: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                try:
                    return _listing_items(json.loads(body))
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en IKEA: {exc}", status)
            else:
                last_error = HttpError(f"HTTP {status} en IKEA", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar IKEA")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
