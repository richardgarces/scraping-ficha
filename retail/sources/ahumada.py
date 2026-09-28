from __future__ import annotations

import re
import time
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_clp, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.farmaciasahumada.cl"
AJAX = f"{BASE}/on/demandware.store/Sites-ahumada-cl-Site/default/Search-ShowAjax"
PAGE_SIZE = 24
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price-low-to-high",
    "precio_desc": "price-high-to-low",
}
_TILE_RE = re.compile(
    r'<div\s+class="product-tile\b[^"]*"([^>]*)>(.*?)<button\b[^>]*class="[^"]*product-tile-add-to-cart',
    re.DOTALL | re.IGNORECASE,
)
_ATTR_RE = re.compile(r'data-pid="([^"]+)"', re.I)
_HREF_RE = re.compile(r'<a href="([^"]+\.html)"', re.I)
_IMG_RE = re.compile(r'class="tile-image"[^>]*src="([^"]+)"[^>]*alt="([^"]*)"', re.I)
_CMR_RE = re.compile(r'cmr-price-display.*?content="(\d+)"', re.DOTALL | re.I)
_NORMAL_RE = re.compile(r'precio-normal.*?content="(\d+)"', re.DOTALL | re.I)
_STRIKE_RE = re.compile(r'strike-through[^>]*>.*?content="(\d+)"', re.DOTALL | re.I)
_SALES_RE = re.compile(r'promotion-badge-container[^>]*>\s*(?:<span>)?\$([\d.\s\u00a0]+)', re.I)
_CAT_RE = re.compile(r'data-categories="([^"]*)"', re.I)


def parse_ahumada_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q"):
            return Target(kind="search", query=query.get("q", [None])[0], raw_url=raw)
        if parts and parts[-1].endswith(".html"):
            slug = parts[-1][:-5]
            pid = slug.rsplit("-", 1)[-1]
            return Target(kind="product", product_id=pid if pid.isdigit() else slug, raw_url=raw)
        if parts:
            return Target(kind="category", category_id=parts[-1], category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _abs(url: str | None) -> str | None:
    if not url:
        return None
    return urljoin(BASE + "/", unescape(url))


def parse_tile(html: str) -> dict[str, Any] | None:
    pid_match = _ATTR_RE.search(html)
    if not pid_match:
        return None
    pid = pid_match.group(1)
    href = _HREF_RE.search(html)
    img = _IMG_RE.search(html)
    name = unescape(img.group(2)).strip() if img and img.group(2).strip() else ""
    if not name and href:
        name = unescape(href.group(1).rsplit("/", 1)[-1].replace(".html", "").replace("-", " "))
    fonasa = "badge_fonasa" in html.lower()
    cmr_match = _CMR_RE.search(html)
    cmr = parse_int(cmr_match.group(1)) if cmr_match else None
    normal_match = _NORMAL_RE.search(html) or _STRIKE_RE.search(html)
    normal = parse_int(normal_match.group(1)) if normal_match else None
    sales = None
    if not fonasa:
        sales_match = _SALES_RE.search(html)
        sales = parse_clp(sales_match.group(1)) if sales_match else None
    current = cmr or sales or normal
    cats = unescape(_CAT_RE.search(html).group(1)) if _CAT_RE.search(html) else ""
    return {
        "pid": pid,
        "name": name,
        "url": _abs(href.group(1)) if href else f"{BASE}/{pid}.html",
        "image": _abs(img.group(1)) if img else None,
        "price": current,
        "price_cmr": cmr,
        "price_internet": sales or normal,
        "price_normal": normal,
        "category": cats.split(",")[0].strip() if cats else None,
    }


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current = parse_int(item.get("price"))
    normal = parse_int(item.get("price_normal")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("pid") or "")
    return Product(
        product_id=ident,
        sku_id=ident,
        name=str(item.get("name") or "").strip(),
        brand=item.get("brand"),
        url=item.get("url"),
        seller="Farmacias Ahumada",
        price_cmr=parse_int(item.get("price_cmr")),
        price_internet=parse_int(item.get("price_internet")) or normal,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image"),
        category=item.get("category"),
        store="ahumada",
        source=source,
        scraped_at=now_iso(),
    )


def parse_tiles(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _TILE_RE.finditer(html):
        item = parse_tile(match.group(1) + match.group(2))
        if not item or item["pid"] in seen:
            continue
        seen.add(item["pid"])
        found.append(item)
    return found


@register(
    StoreSpec(
        id="ahumada",
        title="Farmacias Ahumada",
        site="www.farmaciasahumada.cl",
        sort_map=SORT_MAP,
        category_help="Texto de búsqueda; el listado público es Search-ShowAjax",
        platform="sfcc",
    )
)
class AhumadaStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_ahumada_target(value)

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
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if parsed.kind == "product" and parsed.product_id and product.product_id != parsed.product_id:
                continue
            products.append(product)
            if parsed.kind == "product":
                break
            if max_items is not None and len(products) >= max_items:
                break
        if parsed.kind == "product" and not products:
            raise HttpError(f"Producto Ahumada no encontrado: {parsed.product_id}")
        return products

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[dict[str, Any]]:
        start = 0
        page = 0
        yielded = 0
        query = target.query or target.product_id or target.category_id or ""
        while True:
            params: dict[str, Any] = {"q": query, "start": start, "sz": PAGE_SIZE}
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["srule"] = sort_value
            html = self._html(AJAX, params)
            tiles = parse_tiles(html)
            if not tiles:
                break
            for item in tiles:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if len(tiles) < PAGE_SIZE:
                break
            start += PAGE_SIZE
            page += 1
            if max_pages is not None and page >= max_pages:
                break

    def _html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body:
                return body
            last_error = HttpError(f"HTTP {status} en Ahumada", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Ahumada")
