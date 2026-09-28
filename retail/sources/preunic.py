from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

BASE = "https://preunic.cl"
SEARCH_API = "https://api.empathy.co/search/v1/query/preunic/search"
PAGE_SIZE = 24
SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
}


def parse_preunic_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q") or query.get("query"):
            return Target(kind="search", query=(query.get("q") or query.get("query") or [None])[0], raw_url=raw)
        if parts and parts[0] == "products" and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        if parts and parts[0] == "t" and len(parts) > 1:
            slug = "/".join(parts[1:])
            return Target(kind="category", category_id=slug, category_name=parts[-1], raw_url=raw)
        if parts and parts[0] in {"search", "buscar"}:
            return Target(kind="search", query=parts[1] if len(parts) > 1 else None, raw_url=raw)
        if parts:
            return Target(kind="category", category_id="/".join(parts), category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.strip("/").split("/")[-1])
    return Target(kind="search", query=raw)


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    prices = item.get("__prices") if isinstance(item.get("__prices"), dict) else {}
    current_block = prices.get("current") if isinstance(prices.get("current"), dict) else {}
    previous_block = prices.get("previous") if isinstance(prices.get("previous"), dict) else {}
    offer = parse_int(item.get("offerPrice") or current_block.get("value"))
    normal = parse_int(item.get("price") or previous_block.get("value"))
    card = parse_int(item.get("cardPrice"))
    current = offer if offer and offer > 0 else normal
    if card and current and card >= current:
        card = None
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("id") or item.get("sku") or item.get("__id") or "")
    slug = str(item.get("slug") or "").strip()
    cats = item.get("categories") or []
    category = None
    if isinstance(cats, list) and cats:
        category = str(cats[0])
    elif isinstance(cats, str):
        category = cats
    return Product(
        product_id=ident,
        sku_id=str(item.get("sku") or ident),
        name=str(item.get("name") or item.get("__name") or "").strip(),
        brand=item.get("brand"),
        url=f"{BASE}/products/{slug}" if slug else None,
        seller="Preunic",
        price_cmr=card,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image"),
        category=category,
        store="preunic",
        source=source,
        scraped_at=now_iso(),
    )


def _matches_product(item: dict[str, Any], product_id: str) -> bool:
    wanted = product_id.lower()
    return any(
        str(item.get(key) or "").lower() == wanted
        for key in ("id", "sku", "__id", "slug", "objectId")
    )


@register(
    StoreSpec(
        id="preunic",
        title="Preunic",
        site="preunic.cl",
        sort_map=SORT_MAP,
        category_help="Slug de categoría, por ejemplo maquillaje",
        platform="empathy",
    )
)
class PreunicStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers={"Accept": "application/json"})
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_preunic_target(value)

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
        payload = self._search(product_id, start=0, rows=8)
        items = payload.get("content") or []
        match = next((item for item in items if _matches_product(item, product_id)), None)
        if match is None and len(items) == 1:
            match = items[0]
        if match is None:
            raise HttpError(f"Producto Preunic no encontrado: {product_id}")
        return listing_item_to_product(match, source="product")

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[dict[str, Any]]:
        query = target.query or target.category_name or target.category_id or ""
        if not query:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        start = 0
        page = 0
        yielded = 0
        while True:
            payload = self._search(query, start=start, rows=PAGE_SIZE, sort=sort)
            items = payload.get("content") or []
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            total = int(payload.get("numFound") or 0)
            start += len(items)
            page += 1
            if max_pages is not None and page >= max_pages:
                break
            if start >= total:
                break

    def _search(self, query: str, *, start: int, rows: int, sort: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "query": query,
            "start": start,
            "rows": rows,
            "scope": "desktop",
            "lang": "es",
            "internal": "true",
        }
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(SEARCH_API, params=params)
            if status == 200 and body:
                try:
                    data = json.loads(body)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en Preunic: {exc}", status)
                else:
                    catalog = data.get("catalog") if isinstance(data, dict) else None
                    if isinstance(catalog, dict):
                        content = [item for item in (catalog.get("content") or []) if isinstance(item, dict)]
                        return {
                            "content": content,
                            "numFound": int(catalog.get("numFound") or 0),
                        }
                    last_error = HttpError("Respuesta Preunic inesperada", status)
            else:
                last_error = HttpError(f"HTTP {status} en Preunic", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Preunic")
