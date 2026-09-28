from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int, parse_money, strip_html
from retail.registry import StoreSpec, register

BASE = "https://miportal.entel.cl"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "application/json, text/html;q=0.8",
}
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "",
    "precio_desc": "",
}
PAGE_SIZE = 24
PROD_RE = re.compile(r"(prod\d+)", re.I)


def parse_entel_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        term = (query.get("Ntt") or query.get("q") or [None])[0]
        if parts and len(parts) >= 2 and parts[0] == "personas" and parts[1] == "busqueda":
            return Target(kind="search", query=term, raw_url=raw)
        if term:
            return Target(kind="search", query=term, raw_url=raw)
        for part in reversed(parts):
            match = PROD_RE.search(part)
            if match:
                return Target(kind="product", product_id=match.group(1).lower(), raw_url=raw)
        if parts and parts[0] == "personas" and len(parts) >= 2 and parts[1] == "catalogo":
            slug = "/".join(parts[2:])
            return Target(kind="category", category_id=slug or "celulares", category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    match = PROD_RE.fullmatch(raw) or PROD_RE.search(raw)
    if match and " " not in raw and "/" not in raw:
        return Target(kind="product", product_id=match.group(1).lower())
    if raw.startswith("catalogo/"):
        slug = raw.split("/", 1)[1].strip("/")
        return Target(kind="category", category_id=slug or "celulares", category_name=slug.split("/")[-1])
    if raw.startswith("celulares") and " " not in raw:
        return Target(kind="category", category_id=raw.strip("/"), category_name=raw.split("/")[-1])
    return Target(kind="search", query=raw)


def _attr(attrs: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key not in attrs:
            continue
        value = attrs[key]
        if isinstance(value, list):
            if not value:
                continue
            return value[0]
        if value in (None, ""):
            continue
        return value
    return None


def _record_attrs(item: dict[str, Any]) -> dict[str, Any]:
    attrs = dict(item.get("attributes") or {})
    nested = item.get("records")
    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
        child = nested[0].get("attributes") or {}
        for key, value in child.items():
            if key not in attrs or not attrs[key]:
                attrs[key] = value
    return attrs


def _abs(path: str | None) -> str | None:
    if not path:
        return None
    text = str(path).strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return urljoin(BASE + "/", text.lstrip("/"))


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    """Precio de equipo/contado: listPrice / priceFormatted. No usa cuotas ni 'desde con plan'."""
    attrs = _record_attrs(item)
    sku_info = item.get("skuPriceInfo") if isinstance(item.get("skuPriceInfo"), dict) else {}
    current = parse_money(
        _attr(attrs, "listPrice", "productListPrice", "product.listPrice", "priceFormatted", "price.formatted")
        or sku_info.get("salePrice")
        or sku_info.get("listPrice")
        or sku_info.get("amount")
    )
    normal = parse_money(_attr(attrs, "referencePrice", "referencePriceFormatted")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(_attr(attrs, "productId") or "").strip()
    if not ident:
        action = item.get("detailsAction") or {}
        state = str(action.get("recordState") or "")
        match = PROD_RE.search(state)
        ident = match.group(1).lower() if match else ""
    seo = _attr(attrs, "seoUrl")
    url = _abs(str(seo) if seo else (f"/personas/catalogo/{ident}" if ident else None))
    image = _abs(str(_attr(attrs, "productImage") or "") or None)
    return Product(
        product_id=ident,
        sku_id=str(_attr(attrs, "sku", "skuId") or ident),
        name=str(_attr(attrs, "displayName", "description") or "").strip(),
        brand=_attr(attrs, "brand") or None,
        url=url,
        seller="Entel",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        category=_attr(attrs, "parentCategoryName", "categoryDescription"),
        description=strip_html(_attr(attrs, "description")),
        store="entel",
        source=source,
        scraped_at=now_iso(),
    )


def extract_records(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    info = payload.get("endeca:assemblerRequestInformation") or {}
    total = parse_int(info.get("endeca:numRecords"))
    for block in payload.get("main") or []:
        if not isinstance(block, dict):
            continue
        rows = [row for row in (block.get("records") or []) if isinstance(row, dict)]
        if rows:
            return (
                rows,
                parse_int(block.get("totalNumRecs")) or total or len(rows),
                parse_int(block.get("recsPerPage")) or PAGE_SIZE,
            )
    rows = [row for row in (payload.get("records") or []) if isinstance(row, dict)]
    return (
        rows,
        parse_int(payload.get("totalNumRecs")) or total or len(rows),
        parse_int(payload.get("recsPerPage")) or PAGE_SIZE,
    )


@register(
    StoreSpec(
        id="entel",
        title="Entel",
        site="miportal.entel.cl",
        sort_map=SORT_MAP,
        category_help="Ruta Endeca, por ejemplo celulares o celulares/samsung",
        platform="custom",
    )
)
class EntelStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_entel_target(value)

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
        if parsed.kind == "product":
            product = self._product(parsed)
            if product.price is None:
                raise HttpError(f"Producto Entel sin precio: {parsed.product_id}")
            return [product]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items):
            product = listing_item_to_product(item, source=parsed.kind)
            if not product.price:
                continue
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, target: Target) -> Product:
        ident = str(target.product_id or "")
        for query in (ident, ident.removeprefix("prod") if ident.startswith("prod") else None):
            if not query:
                continue
            scoped = Target(kind="category", category_id="celulares", query=query)
            items, _total, _size = self._listing_page(scoped, offset=0)
            for item in items:
                product = listing_item_to_product(item, source="product")
                if ident.lower() in {product.product_id.lower(), product.sku_id.lower()}:
                    return product
            items, _total, _size = self._listing_page(Target(kind="search", query=query), offset=0)
            for item in items:
                product = listing_item_to_product(item, source="product")
                if ident.lower() in {product.product_id.lower(), product.sku_id.lower()} and product.price:
                    return product
        raise HttpError(f"Producto Entel no encontrado: {ident}")

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
    ) -> Iterator[dict[str, Any]]:
        page = 0
        yielded = 0
        page_size = PAGE_SIZE
        while True:
            items, total, page_size = self._listing_page(target, offset=page * page_size)
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if max_pages is not None and page + 1 >= max_pages:
                break
            if yielded >= total:
                break
            page += 1

    def _listing_page(self, target: Target, offset: int) -> tuple[list[dict[str, Any]], int, int]:
        params: dict[str, Any] = {"No": offset, "Nrpp": PAGE_SIZE}
        if target.kind == "search" and target.query:
            url = f"{BASE}/personas/busqueda"
            params["Ntt"] = target.query
        elif target.kind == "category" and target.category_id:
            url = f"{BASE}/personas/catalogo/{target.category_id.strip('/')}"
            if target.query:
                params["Ntt"] = target.query
                params["Nty"] = "1"
        elif target.raw_url:
            url = target.raw_url
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        return extract_records(self._json(url, params))

    def _json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                try:
                    data = json.loads(body)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en Entel: {exc}", status)
                else:
                    if isinstance(data, dict):
                        return data
                    last_error = HttpError("Respuesta Entel inesperada", status)
            else:
                last_error = HttpError(f"HTTP {status} en Entel", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Entel")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
