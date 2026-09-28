from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.pcfactory.cl"
API = "https://api.pcfactory.cl/pcfactory-services-catalogo/v1/catalogo/productos"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "application/json",
}
PAGE_SIZE = 24
SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
}


def parse_pcfactory_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("search") or query.get("q"):
            term = (query.get("search") or query.get("q") or [None])[0]
            return Target(kind="search", query=term, raw_url=raw)
        if parts and parts[0] == "producto" and len(parts) > 1:
            return Target(kind="product", product_id=parts[1].split("-")[0], raw_url=raw)
        if parts and parts[0] in {"categoria", "category"} and len(parts) > 1:
            return Target(kind="category", category_id=parts[1], category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _brand(item: dict[str, Any]) -> str | None:
    marca = item.get("marca")
    if isinstance(marca, dict):
        return marca.get("nombre") or None
    return str(marca) if marca else None


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    prices = item.get("precio") or {}
    current = parse_int(prices.get("efectivo") or prices.get("normal"))
    normal = parse_int(prices.get("referencia") or prices.get("normal")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    cat = item.get("categoria") or {}
    ident = str(item.get("id") or "")
    slug = item.get("slug") or ident
    thumb = item.get("thumbnail") or ""
    image = f"https://assets.pcfactory.cl{thumb}" if thumb.startswith("/") else thumb
    gallery = [image]
    for src in re.findall(r'<img\b[^>]*\bsrc=["\']([^"\']+)', str(item.get("descripcion") or ""), re.I):
        if src not in gallery:
            gallery.append(src)
    return Product(
        product_id=ident,
        sku_id=ident,
        name=str(item.get("nombre") or "").strip(),
        brand=_brand(item),
        url=f"{BASE}/producto/{slug}" if slug else None,
        seller="PC Factory",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image or None,
        image_urls=gallery,
        category=cat.get("nombre"),
        category_id=str(cat.get("id") or ""),
        store="pcfactory",
        source=source,
        scraped_at=now_iso(),
    )


@register(
    StoreSpec(
        id="pcfactory",
        title="PC Factory",
        site="www.pcfactory.cl",
        sort_map=SORT_MAP,
        category_help="Texto de búsqueda acotado; el listado público exige el parámetro search",
    )
)
class PcFactoryStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_pcfactory_target(value)

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
        items, _pagination = self._search(Target(kind="search", query=product_id), page=0, sort=None)
        for item in items:
            if str(item.get("id") or "") == str(product_id):
                return listing_item_to_product(item, source="product")
        payload = self._json(f"{API}/{product_id}")
        if not isinstance(payload, dict) or not payload.get("id"):
            raise HttpError(f"Producto PC Factory no encontrado: {product_id}")
        if items:
            listing = items[0]
            payload = {**payload, "precio": payload.get("precio") or listing.get("precio")}
        return listing_item_to_product(payload, source="product")

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
            items, pagination = self._search(target, page, sort)
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            total_pages = int(pagination.get("totalPages") or 1)
            if max_pages is not None and page + 1 >= max_pages:
                break
            if page + 1 >= total_pages:
                break
            page += 1

    def _search(self, target: Target, page: int, sort: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        params: dict[str, Any] = {"page": page, "size": PAGE_SIZE, "search": target.query or target.category_id or ""}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        payload = self._json(API, params)
        content = payload.get("content") or {}
        items = [item for item in (content.get("items") or []) if isinstance(item, dict)]
        return items, content.get("pageable") or {}

    def _json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                try:
                    data = json.loads(body)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en PC Factory: {exc}", status)
                else:
                    if isinstance(data, dict):
                        return data
                    last_error = HttpError("Respuesta PC Factory inesperada", status)
            else:
                last_error = HttpError(f"HTTP {status} en PC Factory", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar PC Factory")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
