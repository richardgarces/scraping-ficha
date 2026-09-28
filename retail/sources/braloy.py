from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError
from retail.models import Product, Target
from retail.parsers import now_iso, parse_money, strip_html
from retail.registry import StoreSpec, register

BASE = "https://braloy.cl"
SEARCH = f"{BASE}/search"
PAGE_SIZE = 12
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price.asc",
    "precio_desc": "price.desc",
}
_PRICE_RE = re.compile(r'class="product-price"[^>]*content="([^"]+)"|content="([^"]+)"[^>]*class="product-price"')


def parse_braloy_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("s") or query.get("q"):
            return Target(kind="search", query=(query.get("s") or query.get("q") or [None])[0], raw_url=raw)
        if parts and parts[-1].endswith(".html"):
            slug = parts[-1][:-5]
            pid = slug.split("-", 1)[0]
            return Target(kind="product", product_id=pid if pid.isdigit() else slug, raw_url=raw)
        if parts and "-" in parts[-1] and parts[-1].split("-", 1)[0].isdigit():
            return Target(kind="category", category_id=parts[-1], category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _image(cover: Any) -> str | None:
    if not isinstance(cover, dict):
        return None
    by_size = cover.get("bySize") or {}
    if isinstance(by_size, dict):
        for key in ("home_default", "large_default", "medium_default"):
            node = by_size.get(key) or {}
            if isinstance(node, dict) and node.get("url"):
                return str(node["url"])
    for key in ("large", "medium", "small"):
        node = cover.get(key)
        if isinstance(node, dict) and node.get("url"):
            return str(node["url"])
        if isinstance(node, str) and node:
            return node
    return None


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current = parse_money(item.get("price_amount") or item.get("price"))
    normal = parse_money(item.get("regular_price_amount") or item.get("regular_price")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("id_product") or item.get("id") or "")
    url = item.get("canonical_url") or item.get("url") or item.get("link")
    return Product(
        product_id=ident,
        sku_id=str(item.get("reference") or ident),
        name=str(item.get("name") or "").strip(),
        brand=item.get("manufacturer_name") or None,
        url=str(url) if url else None,
        seller="Braloy",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=_image(item.get("cover")),
        description=strip_html(item.get("description_short")),
        store="braloy",
        source=source,
        scraped_at=now_iso(),
    )


def products_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("products")
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


@register(
    StoreSpec(
        id="braloy",
        title="Braloy",
        site="braloy.cl",
        sort_map=SORT_MAP,
        category_help="Slug PrestaShop, por ejemplo 201-accesorios",
        platform="prestashop",
        group="otros",
    )
)
class BraloyStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.open_http({"Accept": "application/json", "Referer": f"{BASE}/"})

    def close(self) -> None:
        if self.http:
            self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_braloy_target(value)

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
            return [self._product(parsed)]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if not product.name or not product.price or not product.url:
                continue
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, target: Target) -> Product:
        rows = self._rows(Target(kind="search", query=target.product_id), page=1, sort=None)
        for item in rows:
            if str(item.get("id_product")) == str(target.product_id):
                return listing_item_to_product(item, source="product")
        if target.raw_url:
            payload = self._get(target.raw_url)
            if isinstance(payload, dict):
                product = payload.get("product") if isinstance(payload.get("product"), dict) else None
                rows = products_from_payload(payload)
                item = product or (rows[0] if rows else None)
                if item:
                    return listing_item_to_product(item, source="product")
            if isinstance(payload, str):
                price = _PRICE_RE.search(payload)
                name = re.search(r"<h1[^>]*>(.*?)</h1>", payload, re.S)
                amount = parse_money((price.group(1) or price.group(2)) if price else None)
                if amount and name:
                    return listing_item_to_product(
                        {
                            "id_product": target.product_id,
                            "name": strip_html(name.group(1)),
                            "price_amount": amount,
                            "url": target.raw_url,
                        },
                        source="product",
                    )
        raise HttpError(f"Producto Braloy no encontrado: {target.product_id}")

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
            rows = self._rows(target, page, sort)
            if not rows:
                break
            for item in rows:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if max_pages is not None and page >= max_pages:
                break
            if len(rows) < PAGE_SIZE:
                break
            page += 1

    def _rows(self, target: Target, page: int, sort: str | None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"page": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["order"] = sort_value
        if target.kind == "search" and target.query:
            params["controller"] = "search"
            params["s"] = target.query
            url = SEARCH
        elif target.kind == "category" and target.category_id:
            url = f"{BASE}/{target.category_id.strip('/')}"
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        payload = self._get(url, params)
        if isinstance(payload, dict):
            return products_from_payload(payload)
        return []

    def _get(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | str:
        last_error: Exception | None = None
        http = self.http
        if http is None:
            raise HttpError("Sesión HTTP de Braloy no inicializada")
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, ctype, body = http.get(url, params=params)
            if status == 200 and body:
                if "json" in ctype or body[:1] in "{[":
                    try:
                        data = json.loads(body)
                    except ValueError as exc:
                        last_error = HttpError(f"JSON inválido en Braloy: {exc}", status)
                    else:
                        if isinstance(data, dict):
                            return data
                        last_error = HttpError("Respuesta Braloy inesperada", status)
                else:
                    return body
            else:
                last_error = HttpError(f"HTTP {status} en Braloy", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                continue
            break
        raise last_error or HttpError("Fallo al consultar Braloy")
