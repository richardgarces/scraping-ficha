from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_int, parse_money, strip_html
from retail.registry import StoreSpec, register

BASE = "https://catalogo.movistar.cl"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price",
    "precio_desc": "price",
}
PAGE_SIZE = 36
ITEM_RE = re.compile(r'<li[^>]*class="[^"]*product-item[^"]*"[\s\S]*?</li>', re.I)
ID_RE = re.compile(r'data-crosss-id-catalog="(\d+)"')
INFO_ID_RE = re.compile(r'id="product-item-info\s*(\d+)"')
LINK_TAG_RE = re.compile(r"<a\b([^>]*product-item-(?:link|photo)[^>]*)>", re.I)
HREF_RE = re.compile(r'href="([^"]+)"', re.I)
TITLE_RE = re.compile(r'title="([^"]*)"', re.I)
H2_RE = re.compile(r"<h2[^>]*>([\s\S]*?)</h2>", re.I)
CASH_PRICE_RE = re.compile(
    r'class="divCon-plan-txt-valor-sinLabel"[^>]*>\s*([^<]+)',
    re.I,
)
ONE_PRICE_RE = re.compile(r'class="[^"]*onePrice[^"]*"[\s\S]*?(\$[\d.\s\u00a0]+)', re.I)
IMG_RE = re.compile(r'class="product-image-photo"[^>]*src="([^"]+)"', re.I)
TOTAL_RE = re.compile(r"Mostrando\s+\d+\s+al\s+\d+\s+de\s+(\d+)", re.I)
TOOLBAR_RE = re.compile(r"toolbar-number[^>]*>([^<]+)")
PROVIDER_ID_RE = re.compile(r'"items":\{"(\d+)":')
PRICE_INFO_RE = re.compile(r'"price_info":\{"final_price":(\d+)[^}]*"regular_price":(\d+)')
PRICE_VALUE_RE = re.compile(r"class=['\"]price_value['\"]>\s*([^<]+)", re.I)
MARCA_RE = re.compile(r'class="nombreEquipo-marca[^"]*"[^>]*>([\s\S]*?)</span>', re.I)
MODELO_RE = re.compile(r'class="nombreEquipo-modelo[^"]*"[^>]*>([\s\S]*?)</span>', re.I)


def parse_movistar_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q"):
            return Target(kind="search", query=query["q"][0], raw_url=raw)
        if parts and parts[0] == "catalogsearch":
            return Target(kind="search", query=None, raw_url=raw)
        if parts and parts[0] == "tienda" and len(parts) >= 2:
            slug = "/".join(parts[1:])
            last = parts[-1]
            if re.search(r"\d", last):
                return Target(kind="product", product_id=last, raw_url=raw)
            return Target(kind="category", category_id=slug, category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if raw.startswith("tienda/"):
        slug = raw.split("/", 1)[1].strip("/")
        if re.search(r"\d", slug.split("/")[-1]):
            return Target(kind="product", product_id=slug)
        return Target(kind="category", category_id=slug, category_name=slug.split("/")[-1])
    if "/" in raw and " " not in raw:
        path = raw.strip("/")
        return Target(kind="category", category_id=path, category_name=path.split("/")[-1])
    return Target(kind="search", query=raw)


def parse_listing_html(html: str) -> tuple[list[dict[str, Any]], int]:
    page = unescape(html).replace("&#x20;", " ")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for card in ITEM_RE.findall(page):
        ident = ID_RE.search(card) or INFO_ID_RE.search(card) or re.search(r"product_item_info_(\d+)", card)
        href = None
        title = None
        for attrs in LINK_TAG_RE.findall(card):
            found = HREF_RE.search(attrs)
            if found:
                href = found
                title = TITLE_RE.search(attrs)
                if "product-item-link" in attrs:
                    break
        heading = H2_RE.search(card)
        name = strip_html(heading.group(1) if heading else "") or ""
        if title and title.group(1):
            name = name or unescape(title.group(1)).strip()
        url = unescape(href.group(1)) if href else None
        cash = CASH_PRICE_RE.search(card) or ONE_PRICE_RE.search(card)
        image = IMG_RE.search(card)
        key = url or (ident.group(1) if ident else name)
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(
            {
                "id": ident.group(1) if ident else (url.rsplit("/", 1)[-1] if url else ""),
                "name": name,
                "url": url,
                "price": cash.group(1).strip() if cash else None,
                "image": unescape(image.group(1)) if image else None,
            }
        )
    totals = [parse_int(value) for value in TOOLBAR_RE.findall(page)]
    shown = parse_int(match.group(1)) if (match := TOTAL_RE.search(page)) else None
    count = shown or max((value for value in totals if value), default=len(items))
    return items, count or len(items)


def parse_product_html(html: str, *, product_id: str | None = None, raw_url: str | None = None) -> dict[str, Any]:
    items, _count = parse_listing_html(html)
    if items:
        return items[0]
    marca = strip_html(MARCA_RE.search(html).group(1)) if MARCA_RE.search(html) else None
    modelo = strip_html(MODELO_RE.search(html).group(1)) if MODELO_RE.search(html) else None
    name = " ".join(part for part in (marca, modelo) if part).strip()
    brand = marca
    sku = None
    image = None
    for block in re.findall(r'<script type="application/ld\+json">\s*([\s\S]*?)</script>', html, re.I):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if not isinstance(row, dict) or row.get("@type") != "Product":
                continue
            name = name or str(row.get("name") or "").strip()
            sku = str(row.get("sku") or "").strip() or sku
            brand_row = row.get("brand")
            if isinstance(brand_row, dict):
                brand = brand or brand_row.get("name")
            image = first_image_url(row.get("image")) or image
    ident = PROVIDER_ID_RE.search(html)
    price_info = PRICE_INFO_RE.search(html)
    cash = PRICE_VALUE_RE.search(html)
    current = parse_money(price_info.group(1) if price_info else (cash.group(1) if cash else None))
    normal = parse_money(price_info.group(2) if price_info else None) or current
    return {
        "id": ident.group(1) if ident else (product_id or ""),
        "sku": sku,
        "name": name or (product_id or ""),
        "brand": brand,
        "url": raw_url,
        "price": current,
        "price_normal": normal,
        "image": image,
    }


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current = parse_money(item.get("price"))
    normal = parse_money(item.get("price_normal")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("id") or "")
    url = item.get("url")
    if url and not str(url).startswith("http"):
        url = urljoin(BASE + "/", str(url).lstrip("/"))
    return Product(
        product_id=ident,
        sku_id=str(item.get("sku") or ident),
        name=str(item.get("name") or "").strip(),
        brand=item.get("brand") or None,
        url=url,
        seller="Movistar",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image"),
        store="movistar",
        source=source,
        scraped_at=now_iso(),
    )


@register(
    StoreSpec(
        id="movistar",
        title="Movistar",
        site="catalogo.movistar.cl",
        sort_map=SORT_MAP,
        category_help="Slug de tienda, por ejemplo celulares",
        platform="custom",
    )
)
class MovistarStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_movistar_target(value)

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
                raise HttpError(f"Producto Movistar sin precio: {parsed.product_id}")
            return [product]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if not product.price:
                continue
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, target: Target) -> Product:
        if target.raw_url:
            html = self._html(target.raw_url)
            item = parse_product_html(html, product_id=target.product_id, raw_url=target.raw_url)
            if item.get("price") or item.get("name"):
                return listing_item_to_product(item, source="product")
        ident = str(target.product_id or "")
        if ident and not ident.isdigit():
            html = self._html(f"{BASE}/tienda/{ident}")
            item = parse_product_html(html, product_id=ident, raw_url=f"{BASE}/tienda/{ident}")
            return listing_item_to_product(item, source="product")
        items, _count = self._listing_page(Target(kind="search", query=ident), page=1, sort=None)
        for item in items:
            if ident and ident in {str(item.get("id") or ""), str(item.get("sku") or "")}:
                return listing_item_to_product(item, source="product")
        if items:
            return listing_item_to_product(items[0], source="product")
        raise HttpError(f"Producto Movistar no encontrado: {ident}")

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
            items, total = self._listing_page(target, page, sort)
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if max_pages is not None and page >= max_pages:
                break
            if yielded >= total:
                break
            page += 1

    def _listing_page(self, target: Target, page: int, sort: str | None) -> tuple[list[dict[str, Any]], int]:
        params: dict[str, Any] = {"p": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["product_list_order"] = sort_value
            if sort == "precio_desc":
                params["product_list_dir"] = "desc"
        if target.kind == "search" and target.query:
            params["q"] = target.query
            url = f"{BASE}/catalogsearch/result/"
        elif target.kind == "category" and target.category_id:
            url = f"{BASE}/tienda/{target.category_id.strip('/')}"
        elif target.raw_url:
            url = target.raw_url
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        return parse_listing_html(self._html(url, params))

    def _html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                return body
            last_error = HttpError(f"HTTP {status} en Movistar", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Movistar")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
