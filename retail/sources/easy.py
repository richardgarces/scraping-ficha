from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import extract_next_data, now_iso, parse_int, strip_html
from retail.registry import StoreSpec, register

BASE = "https://www.easy.cl"
HEADERS = {
    "Origin": "https://www.easy.cl",
    "Referer": "https://www.easy.cl/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "orders:desc",
    "precio_asc": "price:asc",
    "precio_desc": "price:desc",
}


def parse_easy_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and (parts[-1] == "p" or parsed.path.endswith("/p")):
            slug = parts[-2] if parts[-1] == "p" else parts[-1][:-2]
            return Target(kind="product", product_id=slug, raw_url=raw)
        if parts and parts[0] == "search":
            return Target(kind="search", query=parts[1] if len(parts) > 1 else None, raw_url=raw)
        if parts:
            return Target(kind="category", category_id="/".join(parts), category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.endswith("/p") or raw.isdigit():
        return Target(kind="product", product_id=raw.removesuffix("/p"))
    if "/" in raw and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.strip("/"))
    return Target(kind="search", query=raw)


def _prices(item: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    prices = item.get("prices") or {}
    offer = parse_int(prices.get("offerPrice"))
    normal = parse_int(prices.get("normalPrice"))
    card = parse_int(prices.get("brandPrice"))
    default = ((item.get("commercialOffer") or {}).get("defaultOffer") or {}).get("prices") or {}
    offer = offer or parse_int(default.get("offerPrice"))
    normal = normal or parse_int(default.get("normalPrice"))
    card = card or parse_int(default.get("brandPrice"))
    return offer or card or normal, normal, card


def _specs(raw: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    if not isinstance(raw, list):
        return specs
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        values = item.get("values") or []
        value = values[0] if values else None
        if isinstance(value, dict):
            value = value.get("value") or value.get("name")
        if name and value:
            specs[str(name)] = str(value)
    return specs


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current, normal, card = _prices(item)
    default_offer = ((item.get("commercialOffer") or {}).get("defaultOffer") or {})
    raw_stock = default_offer.get("AvailableQuantity")
    if raw_stock is None:
        raw_stock = default_offer.get("availableQuantity")
    stock = parse_int(raw_stock)
    discount = None
    for adj in item.get("adjustments") or []:
        if isinstance(adj, dict) and adj.get("percentageDiscount"):
            discount = parse_int(adj["percentageDiscount"])
            break
    if discount is None and normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    link = item.get("linkText") or ""
    cats = item.get("categories") or []
    return Product(
        product_id=str(item.get("productId") or item.get("sku") or ""),
        sku_id=str(item.get("sku") or item.get("productId") or ""),
        name=str(item.get("productName") or item.get("name") or "").strip(),
        brand=item.get("brand") or None,
        url=f"{BASE}/{link}" if link else None,
        seller=item.get("sellerName") or ("Easy" if not item.get("isMarketplace") else None),
        price_cmr=card,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("imageUrl"),
        is_sponsored=bool(item.get("sponsoredProductData")),
        category=str(cats[0]).split("/")[-1] if cats else None,
        specifications=_specs(item.get("specifications")),
        description=strip_html(item.get("description")),
        store="easy",
        source=source,
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if stock > 0 else "Sin stock") if stock is not None else None,
    )


def product_detail_to_product(payload: dict[str, Any]) -> Product:
    page = payload.get("props", {}).get("pageProps", payload)
    product = page.get("product") or payload
    items = product.get("items") or []
    item = items[0] if items else {}
    sellers = item.get("sellers") or []
    seller = sellers[0] if sellers else {}
    offer = seller.get("commertialOffer") or seller.get("commercialOffer") or item.get("offering") or {}
    raw_stock = offer.get("AvailableQuantity")
    if raw_stock is None:
        raw_stock = offer.get("availableQuantity")
    stock = parse_int(raw_stock)
    prices = (product.get("commercialOffer") or {}).get("defaultOffer", {}).get("prices") or {}
    current = parse_int(
        prices.get("offerPrice")
        or offer.get("Price")
        or offer.get("price")
    )
    normal = parse_int(prices.get("normalPrice") or offer.get("ListPrice") or offer.get("listPrice"))
    image = first_image_url(item.get("images"))
    cats = product.get("categories") or []
    link = product.get("linkText") or ""
    return Product(
        product_id=str(product.get("productId") or ""),
        sku_id=str(page.get("productSku") or item.get("itemId") or product.get("productId") or ""),
        name=str(product.get("productName") or "").strip(),
        brand=product.get("brand") or None,
        url=f"{BASE}/{link}/p" if link and not str(link).endswith("/p") else (f"{BASE}/{link}" if link else None),
        seller=seller.get("sellerName") or "Easy",
        seller_id=str(seller.get("sellerId")) if seller.get("sellerId") is not None else None,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=(
            round((normal - current) * 100 / normal) if normal and current and normal > current else None
        ),
        image_url=image,
        category=str(cats[0]).strip("/") if cats else None,
        category_id=str(product.get("categoryId") or ""),
        description=strip_html(product.get("description") or product.get("metaTagDescription")),
        specifications=_specs(product.get("specifications")),
        store="easy",
        source="product",
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if stock > 0 else "Sin stock") if stock is not None else None,
    )


def listing_from_next_data(payload: dict[str, Any], page: int) -> dict[str, Any]:
    props = payload.get("props", {}).get("pageProps", {})
    data = props.get("serverProductsResponse") or {}
    results = data.get("productList") or []
    total = int(data.get("recordsFiltered") or props.get("productsCount") or 0)
    return {
        "results": results,
        "pagination": {"count": total, "perPage": 40, "currentPage": page},
    }


@register(
    StoreSpec(
        id="easy",
        title="Easy Chile",
        site="www.easy.cl",
        sort_map=SORT_MAP,
        category_help="Slug de categoría, por ejemplo herramientas/herramientas-electricas/taladros-y-atornilladores",
    )
)
class EasyStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_easy_target(value)

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
            return [product_detail_to_product(self._product_payload(parsed))]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if detalle and (parsed.raw_url or product.url):
                try:
                    product = product_detail_to_product(
                        extract_next_data(self._get_html(product.url or parsed.raw_url or ""))
                    )
                    product.source = parsed.kind
                except (HttpError, ValueError):
                    pass
            products.append(product)
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
            data = self._listing_page(target, page, sort)
            results = data.get("results") or []
            if not results:
                break
            for item in results:
                if isinstance(item, dict):
                    yield item
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
            pagination = data.get("pagination") or {}
            count = int(pagination.get("count") or 0)
            per_page = int(pagination.get("perPage") or 40) or 40
            total_pages = math.ceil(count / per_page) if count else page
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break
            page += 1

    def _listing_page(self, target: Target, page: int, sort: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        if target.kind == "search" and target.query:
            url = f"{BASE}/search/{quote(target.query)}"
        elif target.kind == "category" and target.category_id:
            url = f"{BASE}/{target.category_id.strip('/')}"
        elif target.raw_url:
            url = target.raw_url
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        return listing_from_next_data(extract_next_data(self._get_html(url, params)), page)

    def _product_payload(self, target: Target) -> dict[str, Any]:
        if target.raw_url:
            return extract_next_data(self._get_html(target.raw_url))
        product_id = (target.product_id or "").strip("/")
        if "/" in product_id:
            url = f"{BASE}/{product_id}"
            if not url.endswith("/p"):
                url += "/p"
            return extract_next_data(self._get_html(url))
        listing = self._listing_page(Target(kind="search", query=product_id), page=1, sort=None)
        results = listing.get("results") or []
        if results:
            link = results[0].get("linkText")
            if link:
                url = f"{BASE}/{str(link).lstrip('/')}"
                if not url.endswith("/p"):
                    url += "/p"
                return extract_next_data(self._get_html(url))
        raise HttpError(f"Producto Easy no encontrado: {product_id}")

    def _get_html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body and "__NEXT_DATA__" in body:
                return body
            last_error = HttpError(f"HTTP {status} en {url}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
