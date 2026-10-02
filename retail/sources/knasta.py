from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import extract_next_data, now_iso, parse_float, parse_int, parse_money
from retail.registry import StoreSpec, register

BASE = "https://knasta.cl"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "pasc",
    "precio_desc": "pdesc",
}


def parse_knasta_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        term = (query.get("q") or [None])[0]
        category = (query.get("category") or [None])[0]
        if parts and parts[0] == "detail" and len(parts) >= 3:
            return Target(kind="product", product_id=f"{parts[1]}#{parts[2]}", raw_url=raw)
        slug = parts[1] if parts and parts[0] == "results" and len(parts) > 1 else None
        cat = category or slug
        if term:
            return Target(
                kind="search",
                query=term,
                category_id=cat,
                category_name=slug,
                raw_url=raw,
            )
        if cat:
            return Target(kind="category", category_id=cat, category_name=slug or cat, raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if "#" in raw and " " not in raw:
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _name(value: Any) -> str:
    text = str(value or "").replace('""', '"')
    return re.sub(r"\s+", " ", text).strip()


def _unwrap_partner(url: str) -> str:
    parsed = urlparse(url)
    landing = (parse_qs(parsed.query).get("dl") or [None])[0]
    if landing and landing.startswith(("http://", "https://")):
        return landing
    return url


def offer_url(item: dict[str, Any]) -> str | None:
    raw = str(item.get("url") or "").strip()
    retail = str(item.get("retail") or "").strip() or None
    product_id = str(item.get("product_id") or "").strip() or None
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/"):
        parsed = urlparse(raw)
        partner = (parse_qs(parsed.query).get("partner_url") or [None])[0]
        if partner:
            return _unwrap_partner(partner)
        return urljoin(BASE + "/", raw.lstrip("/"))
    if retail and product_id:
        return f"{BASE}/detail/{retail}/{product_id}"
    return None


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    retail = str(item.get("retail") or "").strip()
    sku = str(item.get("product_id") or "").strip()
    kid = str(item.get("kid") or "").strip()
    if not kid and retail and sku:
        kid = f"{retail}#{sku}"
    current = parse_money(item.get("current_price"))
    internet = parse_money(item.get("price_internet"))
    card = parse_money(item.get("price_card"))
    previous = parse_money(item.get("last_variation_price"))
    normal = previous if previous and current and previous > current else None
    if normal is None and internet and current and internet > current:
        normal = internet
    seller = str(item.get("retail_label") or "").strip() or None
    return Product(
        product_id=kid,
        sku_id=sku or kid,
        name=_name(item.get("title") or item.get("seo_title")),
        brand=str(item.get("brand") or "").strip() or None,
        url=offer_url(item),
        seller=seller,
        price_cmr=card,
        price_internet=internet or current,
        price_normal=normal or current,
        price=current,
        rating=parse_float(item.get("rating_average")),
        reviews=parse_int(item.get("rating_total")),
        image_url=first_image_url(item.get("image")) or first_image_url(item.get("thumbnail_image")),
        store="knasta",
        source=source,
        scraped_at=now_iso(),
    )


def extract_listing(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = ((payload.get("props") or {}).get("pageProps") or {}).get("initialData") or {}
    if not isinstance(data, dict):
        return [], 1
    products = [item for item in data.get("products") or [] if isinstance(item, dict)]
    try:
        total_pages = max(1, int(data.get("total_pages") or 1))
    except (TypeError, ValueError):
        total_pages = 1
    return products, total_pages


def extract_detail_product(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = ((payload.get("props") or {}).get("pageProps") or {}).get("initialData") or {}
    product = data.get("product") if isinstance(data, dict) else None
    return product if isinstance(product, dict) else None


@register(
    StoreSpec(
        id="knasta",
        # Es un agregador, no la tienda que vende. La presentación usa el
        # comercio de destino y cae en “Otro” cuando no puede identificarlo.
        # El id interno se mantiene; el título público nunca nombra la fuente.
        title="Otro",
        site="knasta.cl",
        sort_map=SORT_MAP,
        category_help="Slug o ID de categoría, por ejemplo tecnologia o 20497",
        platform="custom",
        group="retail",
    )
)
class KnastaStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)

    def parse_target(self, value: str) -> Target:
        return parse_knasta_target(value)

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        del detalle  # el listado SSR ya trae nombre, precio y link
        parsed = target if isinstance(target, Target) else self.parse_target(target)
        if parsed.kind == "product":
            product = self._product(parsed)
            if not product.name or product.price is None or not product.url:
                raise HttpError(f"Oferta incompleta: {parsed.product_id}")
            return [product]
        products: list[Product] = []
        pages = 1 if max_pages is None else max(1, max_pages)
        for page in range(1, pages + 1):
            batch, total_pages = self._listing(parsed, page=page, sort=sort)
            for item in batch:
                product = listing_item_to_product(item, source=parsed.kind)
                if not product.name or product.price is None or not product.url or not product.product_id:
                    continue
                products.append(product)
                if max_items is not None and len(products) >= max_items:
                    return products
            if page >= total_pages:
                break
        return products

    def _product(self, target: Target) -> Product:
        ident = str(target.product_id or "")
        if target.raw_url:
            url = target.raw_url
        else:
            retail, _, sku = ident.partition("#")
            if not retail or not sku:
                raise ValueError(f"Aviso inválido: {ident}")
            url = f"{BASE}/detail/{retail}/{sku}"
        item = extract_detail_product(extract_next_data(self._get_html(url)))
        if not item:
            raise HttpError(f"No se devolvió la oferta {ident}")
        return listing_item_to_product(item, source="product")

    def _listing(
        self,
        target: Target,
        *,
        page: int,
        sort: str | None,
    ) -> tuple[list[dict[str, Any]], int]:
        url, params = self._listing_request(target, page=page, sort=sort)
        payload = extract_next_data(self._get_html(url, params=params))
        return extract_listing(payload)

    def _listing_request(
        self,
        target: Target,
        *,
        page: int,
        sort: str | None,
    ) -> tuple[str, dict[str, Any] | None]:
        params: dict[str, Any] = {}
        order = SORT_MAP.get(sort or "recomendados", SORT_MAP["recomendados"])
        if order:
            params["order"] = order
        if page > 1:
            params["page"] = page
        if target.kind == "url" and target.raw_url:
            return target.raw_url, params or None
        query = (target.query or "").strip()
        cat = (target.category_id or "").strip().strip("/")
        if query:
            if cat and not cat.isdigit():
                url = f"{BASE}/results/{cat}"
            else:
                url = f"{BASE}/results"
                if cat:
                    params["category"] = cat
            params["q"] = query
            return url, params
        if cat:
            if cat.isdigit():
                params["category"] = cat
                return f"{BASE}/results", params
            return f"{BASE}/results/{cat}", params or None
        raise ValueError("Búsqueda sin término")

    def _get_html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body and "__NEXT_DATA__" in body:
                return body
            lowered = (body or "").lower()
            if status in {403, 503} and ("cloudflare" in lowered or "just a moment" in lowered):
                last_error = HttpError("La fuente bloqueó la solicitud (Cloudflare)", status)
            else:
                last_error = HttpError(f"HTTP {status} en {url}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")
