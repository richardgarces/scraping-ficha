from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import extract_next_data, now_iso, parse_clp, parse_float, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.lider.cl"
HEADERS = {
    "Origin": "https://www.lider.cl",
    "Referer": "https://www.lider.cl/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "best_match",
    "precio_asc": "price_low",
    "precio_desc": "price_high",
    "rating": "best_seller",
}


def parse_lider_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] == "ip":
            product_id = parts[-1]
            return Target(kind="product", product_id=product_id, raw_url=raw)
        if query.get("query") or query.get("Ntt"):
            term = (query.get("query") or query.get("Ntt") or [None])[0]
            return Target(kind="search", query=term, raw_url=raw)
        cat_id = (query.get("catId") or query.get("cat_id") or [None])[0]
        if cat_id:
            return Target(kind="category", category_id=cat_id, category_name=cat_id, raw_url=raw)
        if parts and parts[0] == "browse" and len(parts) > 1:
            return Target(
                kind="category",
                category_id=parts[-1],
                category_name=parts[-2] if len(parts) > 2 else parts[-1],
                raw_url=raw,
            )
        return Target(kind="url", raw_url=raw)
    if "_" in raw and raw.replace("_", "").isdigit():
        return Target(kind="category", category_id=raw, category_name=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _listing_items(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    page = payload.get("props", {}).get("pageProps", {})
    result = (page.get("initialData") or {}).get("searchResult") or {}
    stacks = result.get("itemStacks") or []
    items = (stacks[0].get("items") or []) if stacks else []
    pagination = result.get("paginationV2") or {}
    return [item for item in items if isinstance(item, dict)], {
        "count": int(result.get("aggregatedCount") or result.get("count") or 0),
        "perPage": len(items) or 40,
        "currentPage": int((page.get("initialSearchQueryVariables") or {}).get("page") or 1),
        "maxPage": int(pagination.get("maxPage") or 1),
    }


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    info = item.get("priceInfo") or {}
    current = parse_int(item.get("price")) or parse_clp(info.get("linePrice") or info.get("itemPrice"))
    # savingsAmt es el ahorro en pesos, no un porcentaje: sirve para reconstruir
    # el precio normal cuando Lider no publica wasPrice.
    savings = parse_clp(info.get("savingsAmt"))
    normal = parse_clp(info.get("wasPrice")) or (current + savings if current and savings else None) or current
    discount = round((normal - current) * 100 / normal) if normal and current and normal > current else None
    images = item.get("imageInfo") or {}
    gallery = [images.get("thumbnailUrl"), item.get("image"), images.get("allImages")]
    image = (
        first_image_url(images.get("thumbnailUrl"))
        or first_image_url(item.get("image"))
        or first_image_url(images.get("allImages"))
    )
    path = item.get("canonicalUrl") or ""
    cats = ((item.get("category") or {}).get("path") or [])
    last_cat = cats[-1] if cats and isinstance(cats[-1], dict) else {}
    raw_stock = item.get("availableQuantity")
    if raw_stock is None:
        raw_stock = item.get("quantity")
    if raw_stock is None:
        raw_stock = item.get("stock")
    return Product(
        product_id=str(item.get("usItemId") or item.get("id") or ""),
        sku_id=str(item.get("usItemId") or item.get("id") or ""),
        name=str(item.get("name") or "").strip(),
        brand=item.get("brand") or item.get("manufacturerName") or None,
        url=f"{BASE}{path}" if path else None,
        seller=item.get("sellerName") or "Lider",
        seller_id=str(item.get("sellerId")) if item.get("sellerId") is not None else None,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        rating=parse_float(item.get("averageRating") or item.get("rating")),
        reviews=parse_int(item.get("numberOfReviews")),
        image_url=image,
        image_urls=gallery,
        is_sponsored=bool(item.get("isSponsoredFlag") or item.get("sponsoredProduct")),
        category=last_cat.get("name"),
        category_id=str((item.get("category") or {}).get("categoryPathId") or last_cat.get("url") or ""),
        description=item.get("shortDescription") or item.get("description"),
        store="lider",
        source=source,
        scraped_at=now_iso(),
        stock=parse_int(raw_stock),
        availability=(item.get("availabilityMessage") or item.get("availability") or None),
    )


@register(
    StoreSpec(
        id="lider",
        title="Lider Chile",
        site="www.lider.cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría, por ejemplo 65672745",
    )
)
class LiderStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_lider_target(value)

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
        items, _pagination = self._browse({"query": product_id, "page": 1})
        for item in items:
            if str(item.get("usItemId") or "") == str(product_id) or str(item.get("id") or "") == str(product_id):
                return listing_item_to_product(item, source="product")
        if items:
            return listing_item_to_product(items[0], source="product")
        raise HttpError(f"Producto Lider no encontrado: {product_id}")

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
            params = self._params(target, page, sort)
            items, pagination = self._browse(params)
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            total_pages = int(pagination.get("maxPage") or 1)
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break
            page += 1

    def _params(self, target: Target, page: int, sort: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        if target.kind == "search" and target.query:
            params["query"] = target.query
        elif target.kind == "category" and target.category_id:
            params["catId"] = target.category_id.split("_")[-1]
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        return params

    def _browse(self, params: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(f"{BASE}/browse", params=params)
            if status == 200 and body and "__NEXT_DATA__" in body:
                return _listing_items(extract_next_data(body))
            if body and "Robot or human" in body:
                last_error = HttpError("Lider bloqueó la request (PerimeterX)", status)
            else:
                last_error = HttpError(f"HTTP {status} en Lider browse", status)
            if status in {403, 412, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Lider")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
