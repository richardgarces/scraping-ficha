from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int, strip_html
from retail.registry import StoreSpec, register

SITE = "https://dondelanegra.cl"
DASHBOARD = "https://dashboard.dondelanegra.cl"
API = f"{DASHBOARD}/api/front"
PAGE_SIZE = 24
HEADERS = {
    "Origin": SITE,
    "Referer": f"{SITE}/",
    "Accept": "application/json",
}
SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
}
_COLLECTIONS = {
    "categoria-producto": "categoria",
    "product-category": "categoria",
    "marca": "marca",
    "etiqueta-producto": "etiqueta",
}
_COLLECTION_PATH = {
    "categoria": "categories",
    "marca": "brands",
    "etiqueta": "tags",
}


def parse_dondelanegra_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] in {"producto", "product"} and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        term = (query.get("q") or query.get("s") or [None])[0]
        if (parts and parts[0] == "buscar") or term:
            return Target(kind="search", query=term, raw_url=raw)
        if parts and parts[0] in _COLLECTIONS and len(parts) > 1:
            return Target(
                kind="category",
                category_id=parts[1],
                category_name=_COLLECTIONS[parts[0]],
                raw_url=raw,
            )
        return Target(kind="url", raw_url=raw)
    return Target(kind="search", query=raw)


def _prices(item: dict[str, Any]) -> tuple[int | None, int | None]:
    regular = parse_int(item.get("price"))
    sale = parse_int(item.get("sale_price"))
    current = sale if sale and sale > 0 else regular
    normal = regular if regular and regular > 0 else current
    if current and normal and normal < current:
        normal = current
    return current, normal


def _media(src: Any) -> str | None:
    text = str(src or "").strip()
    if not text:
        return None
    if text.startswith(("http://", "https://")):
        return text
    return urljoin(f"{DASHBOARD}/", text.lstrip("/"))


def _image(item: dict[str, Any]) -> str | None:
    images = item.get("images") or []
    for image in images:
        if isinstance(image, dict):
            src = _media(image.get("src"))
        else:
            src = _media(image)
        if src:
            return src
    return _media(item.get("product_card_image"))


def _product_url(item: dict[str, Any]) -> str | None:
    permalink = str(item.get("permalink") or "").strip()
    if permalink.startswith(("http://", "https://")):
        return permalink
    slug = str(item.get("slug") or "").strip().strip("/")
    if slug:
        return f"{SITE}/producto/{slug}/"
    return None


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current, normal = _prices(item)
    slug = str(item.get("slug") or "").strip()
    sku = str(item.get("sku") or "").strip()
    cats = item.get("categories") or []
    category = None
    category_id = None
    if cats and isinstance(cats[0], dict):
        category = str(cats[0].get("name") or "").strip() or None
        category_id = str(cats[0].get("slug") or cats[0].get("id") or "").strip() or None
    return Product(
        product_id=slug or str(item.get("id") or sku),
        sku_id=sku or str(item.get("id") or slug),
        name=str(item.get("name") or "").strip(),
        url=_product_url(item),
        seller="Donde La Negra",
        price_internet=current,
        price_normal=normal,
        price=current,
        image_url=_image(item),
        category=category,
        category_id=category_id,
        description=strip_html(item.get("short_description") or item.get("description")),
        store="dondelanegra",
        source=source,
        scraped_at=now_iso(),
    )


def _sort_rows(rows: list[dict[str, Any]], sort: str | None) -> list[dict[str, Any]]:
    key = SORT_MAP.get(sort or "", sort or "")
    if key == "price_asc":
        return sorted(rows, key=lambda row: _prices(row)[0] or 10**12)
    if key == "price_desc":
        return sorted(rows, key=lambda row: -(_prices(row)[0] or 0))
    return rows


def _slug_from_target(target: Target) -> str:
    if target.raw_url:
        parsed = parse_dondelanegra_target(target.raw_url)
        if parsed.product_id:
            return parsed.product_id
    return str(target.product_id or "").strip().strip("/")


@register(
    StoreSpec(
        id="dondelanegra",
        title="Donde La Negra",
        site="dondelanegra.cl",
        sort_map=SORT_MAP,
        category_help="Slug de categoría, marca o etiqueta, por ejemplo pisco",
        platform="custom",
        group="gastronomia",
    )
)
class DondelanegraStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_dondelanegra_target(value)

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        del detalle  # el API de ficha ya trae nombre, precio y url
        parsed = target if isinstance(target, Target) else self.parse_target(target)
        if parsed.kind == "product":
            product = listing_item_to_product(self._product(parsed), source="product")
            if not product.name or product.price is None or not product.url:
                raise HttpError(f"Producto Donde La Negra incompleto: {parsed.product_id}")
            return [product]
        rows = self._rows(parsed, max_pages=max_pages, sort=sort)
        products: list[Product] = []
        for item in rows:
            product = listing_item_to_product(item, source=parsed.kind)
            if not product.name or product.price is None or not product.url or not product.product_id:
                continue
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _rows(
        self,
        target: Target,
        *,
        max_pages: int | None,
        sort: str | None,
    ) -> list[dict[str, Any]]:
        pages = 1 if max_pages is None else max(1, max_pages)
        if target.kind == "category" and target.category_id:
            rows = _sort_rows(self._collection(target), sort)
            return rows[: pages * PAGE_SIZE]
        if target.kind != "search" or not (target.query or "").strip():
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        collected: list[dict[str, Any]] = []
        last_page = 1
        for page in range(1, pages + 1):
            batch, last_page = self._search(target.query or "", page)
            collected.extend(batch)
            if page >= last_page or len(batch) < PAGE_SIZE:
                break
        return _sort_rows(collected, sort)

    def _product(self, target: Target) -> dict[str, Any]:
        slug = _slug_from_target(target)
        if not slug:
            raise ValueError("Producto Donde La Negra sin slug")
        payload = self._get_json(f"{API}/products/{slug}")
        if not isinstance(payload, dict) or not payload.get("name"):
            raise HttpError(f"Producto Donde La Negra no encontrado: {slug}")
        return payload

    def _search(self, query: str, page: int) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"q": query.strip(), "page": page, "per_page": PAGE_SIZE}
        if len(query.strip()) <= 4:
            params["exact"] = 1
        payload = self._get_json(f"{API}/search", params=params)
        if not isinstance(payload, dict):
            raise HttpError("Respuesta de búsqueda Donde La Negra inesperada")
        rows = [item for item in payload.get("data") or [] if isinstance(item, dict)]
        try:
            last_page = max(1, int(payload.get("last_page") or 1))
        except (TypeError, ValueError):
            last_page = 1
        return rows, last_page

    def _collection(self, target: Target) -> list[dict[str, Any]]:
        kind = target.category_name if target.category_name in _COLLECTION_PATH else "categoria"
        slug = str(target.category_id or "").strip().strip("/")
        payload = self._get_json(f"{API}/{_COLLECTION_PATH[kind]}/{slug}")
        rows = payload.get("products") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HttpError(f"Colección Donde La Negra no encontrada: {slug}")
        return [item for item in rows if isinstance(item, dict)]

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                try:
                    return json.loads(body)
                except ValueError as exc:
                    last_error = HttpError(f"JSON inválido en Donde La Negra: {exc}", status)
            else:
                last_error = HttpError(f"HTTP {status} en {url}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")
