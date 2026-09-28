from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_clp, parse_int, strip_html
from retail.registry import StoreSpec, register

BASE = "https://www.unimarc.cl"
SEARCH_API = "https://bff-unimarc-web.unimarc.cl/bff-api/products/v2/searches-intelligence"
PAGE_SIZE = 10
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "application/json",
    "source": "web",
    "version": "0.24.0",
}
SORT_MAP = {
    "recomendados": "score",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
}


def parse_unimarc_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and (parts[-1] == "p" or parsed.path.endswith("/p")):
            slug = parts[-2] if parts[-1] == "p" else parts[-1]
            return Target(kind="product", product_id=slug, raw_url=raw)
        if parts and parts[0] in {"search", "buscar"}:
            return Target(kind="search", query=parts[1] if len(parts) > 1 else None, raw_url=raw)
        if parts and parts[0] == "category":
            return Target(kind="category", category_id="/".join(parts[1:]), category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def listing_item_to_product(row: dict[str, Any], *, source: str | None = None) -> Product:
    item = row.get("item") if isinstance(row.get("item"), dict) else row
    price = row.get("price") if isinstance(row.get("price"), dict) else {}
    promo = row.get("promotion") if isinstance(row.get("promotion"), dict) else {}
    current = parse_clp(price.get("price")) or parse_int(promo.get("price"))
    normal = parse_clp(price.get("listPrice") or price.get("priceWithoutDiscount")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    image = first_image_url(item.get("images"))
    slug = str(item.get("slug") or "").strip()
    url = f"{BASE}{slug}" if slug.startswith("/") else (f"{BASE}/{slug}" if slug else None)
    cats = item.get("categories") or []
    ean = str(item.get("ean") or "").strip()
    specs = {"ean": ean} if ean else {}
    return Product(
        product_id=str(item.get("productId") or item.get("itemId") or ""),
        sku_id=str(item.get("sku") or item.get("itemId") or item.get("productId") or ""),
        name=str(item.get("name") or item.get("nameComplete") or "").strip(),
        brand=item.get("brand") or None,
        url=url,
        seller="Unimarc",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        category=str(cats[0]).strip("/") if cats else None,
        category_id=str(item.get("categoryId") or ""),
        description=strip_html(item.get("description") or item.get("descriptionShort")),
        specifications=specs,
        store="unimarc",
        source=source,
        scraped_at=now_iso(),
    )


@register(
    StoreSpec(
        id="unimarc",
        title="Unimarc",
        site="www.unimarc.cl",
        sort_map=SORT_MAP,
        category_help="Texto de búsqueda; Unimarc no expone slugs de categoría en el BFF público",
    )
)
class UnimarcStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_unimarc_target(value)

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
        query = parsed.query or parsed.product_id or parsed.category_id
        if not query:
            raise ValueError(f"No se puede scrapear el objetivo: {parsed}")
        products: list[Product] = []
        for item in self._iter_listing(query, max_pages=max_pages, max_items=max_items):
            product = listing_item_to_product(item, source=parsed.kind)
            if parsed.kind == "product" and parsed.product_id:
                needle = parsed.product_id.lower()
                if needle not in {product.product_id, product.sku_id} and needle not in (product.url or ""):
                    continue
            products.append(product)
            if parsed.kind == "product":
                break
            if max_items is not None and len(products) >= max_items:
                break
        if parsed.kind == "product" and not products:
            raise HttpError(f"Producto Unimarc no encontrado: {parsed.product_id}")
        return products

    def _iter_listing(self, query: str, *, max_pages: int | None, max_items: int | None) -> Iterator[dict[str, Any]]:
        page = 0
        yielded = 0
        while True:
            start = page * PAGE_SIZE
            end = start + PAGE_SIZE - 1
            payload = self._search(query, start, end)
            rows = payload.get("availableProducts") or []
            if not rows:
                break
            for row in rows:
                if isinstance(row, dict):
                    yield row
                    yielded += 1
                    if max_items is not None and yielded >= max_items:
                        return
            if max_pages is not None and page + 1 >= max_pages:
                break
            if len(rows) < PAGE_SIZE:
                break
            page += 1

    def _search(self, query: str, start: int, end: int) -> dict[str, Any]:
        last_error: Exception | None = None
        body = {"query": query, "from": str(start), "to": str(end)}
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, raw = self.http.post(SEARCH_API, json_body=body)
            if status == 200 and raw:
                try:
                    payload = json.loads(raw)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en Unimarc: {exc}", status)
                else:
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if isinstance(data, dict) and not payload.get("error"):
                        return data
                    last_error = HttpError(str((payload or {}).get("message") or "Respuesta Unimarc inesperada"), status)
            else:
                last_error = HttpError(f"HTTP {status} en Unimarc", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Unimarc")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
