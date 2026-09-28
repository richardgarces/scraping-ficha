from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

SEARCH_API = "https://be-paris-backend-cl-ms-search.ccom.paris.cl/products/"
HEADERS = {
    "Origin": "https://www.paris.cl",
    "Referer": "https://www.paris.cl/",
    "Accept": "application/json",
    "Content-Type": "application/json",
}
SORT_MAP = {
    "recomendados": "relevance desc",
    "precio_asc": "price asc",
    "precio_desc": "price desc",
    "rating": "rating desc",
}


def _loc(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("es-CL") or value.get("es") or next(iter(value.values()), None)
    if value is None:
        return None
    return str(value)


def _cents(block: Any) -> int | None:
    if not isinstance(block, dict):
        return None
    amount = (block.get("value") or {}).get("centAmount")
    return int(amount) if amount not in (None, "") else None


def parse_paris_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[-1].endswith(".html"):
            slug = parts[-1][:-5]
            product_id = slug.rsplit("-", 1)[-1] if "-" in slug else slug
            return Target(kind="product", product_id=product_id, raw_url=raw)
        if parts:
            return Target(kind="category", category_id=parts[-1], category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if raw[0].islower() and any(c.isupper() for c in raw) and " " not in raw and "/" not in raw:
        return Target(kind="category", category_id=raw, category_name=raw)
    return Target(kind="search", query=raw)


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    variant = item.get("masterVariant") or {}
    prices = variant.get("prices") or {}
    offer = _cents(prices.get("offer"))
    regular = _cents(prices.get("regular"))
    card = _cents(prices.get("paymentMethod"))
    current = card or offer or regular
    discount = None
    offer_block = prices.get("offer") or {}
    if isinstance(offer_block, dict) and offer_block.get("discountOnRegular"):
        discount = round(float(offer_block["discountOnRegular"]) * 100)
    elif regular and current and regular > current:
        discount = round((regular - current) * 100 / regular)
    gallery = variant.get("images") or []
    image = first_image_url(gallery)
    specs = {
        str(attr.get("label") or attr.get("name")): str(attr.get("value"))
        for attr in (variant.get("mainAttributes") or [])
        if isinstance(attr, dict) and attr.get("value")
    }
    slug = _loc(item.get("slug"))
    product_id = str(item.get("id") or variant.get("id") or "")
    sellers = item.get("sellers") or []
    seller = sellers[0] if sellers else None
    raw_stock = variant.get("availableQuantity")
    if raw_stock is None:
        raw_stock = variant.get("stock")
    stock = parse_int(raw_stock)
    return Product(
        product_id=product_id,
        sku_id=str(variant.get("sku") or product_id),
        name=(_loc(item.get("name")) or "").strip(),
        brand=item.get("brand") or None,
        url=f"https://www.paris.cl/{slug}.html" if slug else None,
        seller=seller,
        price_cmr=card,
        price_internet=offer or regular,
        price_normal=regular,
        price=current,
        discount_percent=discount,
        image_url=image,
        image_urls=gallery,
        category_id=(item.get("categories") or [{}])[0].get("id") if item.get("categories") else None,
        specifications=specs,
        store="paris",
        source=source,
        scraped_at=now_iso(),
        stock=stock,
        availability=("En stock" if stock > 0 else "Sin stock") if stock is not None else None,
    )


@register(
    StoreSpec(
        id="paris",
        title="Paris Chile",
        site="www.paris.cl",
        sort_map=SORT_MAP,
        category_help="ID interno, por ejemplo tecCompNotebooks",
    )
)
class ParisStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_paris_target(value)

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
            return [listing_item_to_product(self._product_raw(parsed.product_id), source="product")]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if detalle and product.product_id:
                try:
                    product = listing_item_to_product(
                        self._product_raw(product.product_id),
                        source=parsed.kind,
                    )
                except HttpError:
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
            data = self._search_page(target, page, sort)
            results = data.get("results") or []
            if not results:
                break
            for item in results:
                if isinstance(item, dict):
                    yield item
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
            total = int(data.get("total") or 0)
            limit = int(data.get("limit") or 20) or 20
            total_pages = math.ceil(total / limit) if total else page
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break
            page += 1

    def _search_page(self, target: Target, page: int, sort: str | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "pagination": {"page": page, "pageSize": 40},
        }
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            body["sort"] = sort_value
        if target.kind == "search" and target.query:
            body["term"] = target.query
        elif target.kind == "category" and target.category_id:
            body["filters"] = [{"key": "group_id", "stringValues": [target.category_id]}]
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        return self._post_json(body)

    def _product_raw(self, product_id: str) -> dict[str, Any]:
        data = self._post_json(
            {"term": product_id, "pagination": {"page": 1, "pageSize": 5}}
        )
        results = data.get("results") or []
        for item in results:
            if str(item.get("id")) == str(product_id):
                return item
        if results:
            return results[0]
        raise HttpError(f"Producto Paris no encontrado: {product_id}")

    def _post_json(self, body: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, text = self.http.post(SEARCH_API, json_body=body)
            if status == 200 and text:
                payload = json.loads(text)
                if isinstance(payload, dict) and "results" in payload:
                    return payload
                last_error = HttpError(f"Respuesta Paris inesperada: {payload}")
            else:
                last_error = HttpError(f"HTTP {status} en Paris search", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Paris")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
