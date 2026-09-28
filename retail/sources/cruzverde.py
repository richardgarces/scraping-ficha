from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url, normalize_product_url
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.cruzverde.cl"
OCAPI = "https://beta.cruzverde.cl/s/Chile/dw/shop/v19_1"
# Client id público del storefront Demandware (el mismo que usa el JS de cruzverde.cl).
STOREFRONT_CLIENT = "c19ce24d-1677-4754-b9f7-c193997c5a92"
PAGE_SIZE = 24
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price-low-to-high",
    "precio_desc": "price-high-to-low",
}


def parse_cruzverde_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q") or query.get("query"):
            return Target(kind="search", query=(query.get("q") or query.get("query") or [None])[0], raw_url=raw)
        if parts and parts[0] in {"product", "producto"} and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        if parts:
            tail = parts[-1].removesuffix(".html")
            if tail.isdigit():
                return Target(kind="product", product_id=tail, raw_url=raw)
        if parts:
            return Target(kind="category", category_id="/".join(parts), category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.strip("/").split("/")[-1])
    return Target(kind="search", query=raw)


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    prices = item.get("prices") if isinstance(item.get("prices"), dict) else {}
    current = parse_int(prices.get("price-sale-cl") or item.get("price"))
    normal = parse_int(prices.get("price-list-cl") or item.get("price")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("id") or item.get("product_id") or "")
    image = first_image_url(
        [group.get("images") for group in item.get("image_groups") or [] if isinstance(group, dict)]
    )
    return Product(
        product_id=ident,
        sku_id=str(item.get("manufacturer_sku") or ident),
        name=str(item.get("name") or item.get("product_name") or "").strip(),
        brand=item.get("brand") or item.get("c_laboratory"),
        url=normalize_product_url("cruzverde", f"{BASE}/product/{ident}", item.get("name") or item.get("product_name")) if ident else None,
        seller="Cruz Verde",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        category=item.get("primary_category_id"),
        category_id=str(item.get("primary_category_id") or ""),
        store="cruzverde",
        source=source,
        scraped_at=now_iso(),
        stock=(item.get('availability') or {}).get('in_stock') if isinstance(item.get('availability'), dict) else None,
        availability=(item.get('availability') or {}).get('message') if isinstance(item.get('availability'), dict) else None,
    )


@register(
    StoreSpec(
        id="cruzverde",
        title="Cruz Verde",
        site="www.cruzverde.cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría Demandware, por ejemplo medicamentos",
        platform="sfcc",
    )
)
class CruzVerdeStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers={"Accept": "application/json"})
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_cruzverde_target(value)

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
        for ident in self._iter_ids(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            products.append(ident)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, product_id: str) -> Product:
        payload = self._json(f"{OCAPI}/products/{product_id}", {"client_id": STOREFRONT_CLIENT, "expand": "images,prices,availability"})
        if not isinstance(payload, dict) or not payload.get("id"):
            raise HttpError(f"Producto Cruz Verde no encontrado: {product_id}")
        return listing_item_to_product(payload, source="product")

    def _iter_ids(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[Product]:
        start = 0
        page = 0
        yielded = 0
        while True:
            params: dict[str, Any] = {
                "q": target.query or target.category_name or target.category_id or "",
                "count": PAGE_SIZE,
                "start": start,
                "client_id": STOREFRONT_CLIENT,
            }
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["sort"] = sort_value
            payload = self._json(f"{OCAPI}/product_search", params)
            hits = [hit for hit in (payload.get("hits") or []) if isinstance(hit, dict)]
            if not hits:
                break
            ids = [str(hit.get("product_id") or "") for hit in hits if hit.get("product_id")]
            for item in self._products(ids):
                yield listing_item_to_product(item, source=target.kind)
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            total = int(payload.get("total") or 0)
            start += len(hits)
            page += 1
            if max_pages is not None and page >= max_pages:
                break
            if start >= total:
                break

    def _products(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        joined = ",".join(ids)
        payload = self._json(
            f"{OCAPI}/products/({joined})",
            {"client_id": STOREFRONT_CLIENT, "expand": "images,prices,availability"},
        )
        rows = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
        if isinstance(payload, dict) and payload.get("id"):
            return [payload]
        return []

    def _json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                try:
                    data = json.loads(body)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en Cruz Verde: {exc}", status)
                else:
                    if isinstance(data, dict):
                        return data
                    last_error = HttpError("Respuesta Cruz Verde inesperada", status)
            else:
                last_error = HttpError(f"HTTP {status} en Cruz Verde", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Cruz Verde")
