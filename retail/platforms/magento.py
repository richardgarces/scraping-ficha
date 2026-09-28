from __future__ import annotations

import re
import time
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int, strip_html
from retail.registry import StoreSpec, register

SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price",
    "precio_desc": "price",
}
ITEM_RE = re.compile(r'<li[^>]*class="[^"]*product-item[^"]*"[^>]*>.*?</li>', re.S)
LINK_TAG_RE = re.compile(r'<a([^>]*product-item-link[^>]*)>(.*?)</a>', re.S)
HREF_RE = re.compile(r'href="([^"]+)"')
PRICE_RE = re.compile(r'data-price-amount="([^"]+)"[^>]*data-price-type="finalPrice"')
PRICE_ID_RE = re.compile(r'id="product-price-(\d+)"[^>]*data-price-amount="([^"]+)"')
OLD_PRICE_RE = re.compile(r'data-price-amount="([^"]+)"[^>]*data-price-type="oldPrice"')
ID_RE = re.compile(r'data-product-id="(\d+)"')
INFO_ID_RE = re.compile(r'id="product-item-info_(\d+)"')
IMG_RE = re.compile(r'(?:data-src|data-original|data-lazy|src)="([^"]+)"')
META_IMAGE_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)',
    re.I,
)
BRAND_RE = re.compile(r'<span class="brand">\s*(.*?)\s*</span>', re.S)
TOTAL_RE = re.compile(r'toolbar-number[^>]*>([^<]+)')


def parse_magento_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q"):
            return Target(kind="search", query=query["q"][0], raw_url=raw)
        if parts and parts[0] == "catalogsearch":
            return Target(kind="search", query=None, raw_url=raw)
        if len(parts) >= 2 and parts[-1].endswith(".html"):
            return Target(kind="category", category_id="/".join(parts), category_name=parts[-1].removesuffix(".html"), raw_url=raw)
        if parts and parts[-1].endswith(".html"):
            return Target(kind="product", product_id=parts[-1].removesuffix(".html"), raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        path = raw.strip("/")
        if not path.endswith(".html"):
            path += ".html"
        return Target(kind="category", category_id=path, category_name=path.split("/")[-1].removesuffix(".html"))
    return Target(kind="search", query=raw)


def listing_item_to_product(item: dict[str, Any], *, store_id: str, source: str | None = None) -> Product:
    current = parse_int(item.get("price"))
    normal = parse_int(item.get("price_normal")) or current
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    return Product(
        product_id=str(item.get("id") or ""),
        sku_id=str(item.get("id") or ""),
        name=str(item.get("name") or "").strip(),
        brand=item.get("brand") or None,
        url=item.get("url"),
        seller=item.get("seller"),
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image"),
        category=item.get("category"),
        store=store_id,
        source=source,
        scraped_at=now_iso(),
    )


def parse_listing_html(html: str) -> tuple[list[dict[str, Any]], int]:
    page = unescape(html).replace("&#x20;", " ")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ident, amount in PRICE_ID_RE.findall(page):
        marker = f'id="product-price-{ident}"'
        pos = page.find(marker)
        window = page[max(0, pos - 5000) : pos + 200]
        link = None
        for attrs, label in LINK_TAG_RE.findall(window):
            href = HREF_RE.search(attrs)
            if href and href.group(1).endswith(".html"):
                link = (unescape(href.group(1)), strip_html(label) or "")
        if not link:
            href = HREF_RE.search(window)
            alt = re.search(r'alt="([^"]+)"', window)
            if href:
                link = (unescape(href.group(1)), unescape(alt.group(1)) if alt else ident)
        if not link or link[0].startswith("#") or link[0] in seen:
            continue
        seen.add(link[0])
        image = IMG_RE.search(window)
        brand = BRAND_RE.search(window)
        old = OLD_PRICE_RE.search(window)
        items.append(
            {
                "id": ident,
                "name": link[1],
                "url": link[0],
                "price": amount,
                "price_normal": old.group(1) if old else None,
                "image": unescape(image.group(1)) if image else None,
                "brand": strip_html(brand.group(1)) if brand else None,
            }
        )
    if not items:
        amounts = PRICE_RE.findall(page) or re.findall(r'data-price-amount="([^"]+)"', page)
        links = LINK_TAG_RE.findall(page)
        for index, (attrs, label) in enumerate(links):
            href = HREF_RE.search(attrs)
            if not href or not href.group(1).endswith(".html"):
                continue
            url = unescape(href.group(1))
            if url in seen:
                continue
            seen.add(url)
            nearby = page[max(0, page.find(url) - 400) : page.find(url) + 1200]
            local_price = PRICE_RE.search(nearby) or re.search(r'data-price-amount="([^"]+)"', nearby)
            ident = ID_RE.search(nearby)
            image = IMG_RE.search(nearby)
            amount = local_price.group(1) if local_price else (amounts[index] if index < len(amounts) else None)
            items.append(
                {
                    "id": ident.group(1) if ident else url.rsplit("/", 1)[-1].removesuffix(".html"),
                    "name": strip_html(label) or "",
                    "url": url,
                    "price": amount,
                    "image": unescape(image.group(1)) if image else None,
                    "brand": None,
                }
            )
    totals = [parse_int(value) for value in TOTAL_RE.findall(page)]
    count = max((value for value in totals if value), default=len(items))
    return items, count or len(items)


def make_magento_store(
    *,
    store_id: str,
    title: str,
    site: str,
    base: str,
    category_help: str = "Slug Magento, por ejemplo camas-y-colchones/colchones",
):
    headers = {
        "Origin": base,
        "Referer": f"{base}/",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    }

    @register(
        StoreSpec(
            id=store_id,
            title=title,
            site=site,
            sort_map=SORT_MAP,
            category_help=category_help,
            platform="magento",
        )
    )
    class MagentoStore(StoreClient):
        def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
            super().__init__(delay=delay, timeout=timeout, retries=retries)
            self.http = HttpSession(timeout=timeout, headers=headers)
            self._last_request = 0.0

        def close(self) -> None:
            self.http.close()

        def parse_target(self, value: str) -> Target:
            return parse_magento_target(value)

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
                product = listing_item_to_product(item, store_id=store_id, source=parsed.kind)
                product.seller = title
                products.append(product)
                if max_items is not None and len(products) >= max_items:
                    break
            return products

        def _product(self, target: Target) -> Product:
            if target.raw_url:
                html = self._html(target.raw_url)
            elif target.product_id and not str(target.product_id).isdigit():
                html = self._html(f"{base}/{target.product_id}.html")
            else:
                items, _count = self._listing_page(Target(kind="search", query=target.product_id), page=1, sort=None)
                if not items:
                    raise HttpError(f"Producto {title} no encontrado: {target.product_id}")
                return listing_item_to_product(items[0], store_id=store_id, source="product")
            items, _count = parse_listing_html(html)
            if items:
                return listing_item_to_product(items[0], store_id=store_id, source="product")
            heading = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            price_match = PRICE_RE.search(html) or re.search(r'data-price-amount="([^"]+)"', html)
            image_match = META_IMAGE_RE.search(html)
            name = strip_html(heading.group(1) if heading else "")
            price = price_match.group(1) if price_match else None
            return Product(
                product_id=str(target.product_id or ""),
                sku_id=str(target.product_id or ""),
                name=name or str(target.product_id or ""),
                url=target.raw_url,
                seller=title,
                price=parse_int(price),
                price_internet=parse_int(price),
                image_url=unescape(image_match.group(1)) if image_match else None,
                store=store_id,
                source="product",
                scraped_at=now_iso(),
            )

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
                url = f"{base}/catalogsearch/result/"
            elif target.kind == "category" and target.category_id:
                path = target.category_id.strip("/")
                url = f"{base}/{path}"
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
                last_error = HttpError(f"HTTP {status} en {title}", status)
                if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                    time.sleep(min(8.0, self.delay * attempt * 2))
                    continue
                break
            raise last_error or HttpError(f"Fallo al consultar {title}")

        def _throttle(self) -> None:
            if self.delay <= 0:
                return
            elapsed = time.monotonic() - self._last_request
            if self._last_request and elapsed < self.delay:
                time.sleep(self.delay - elapsed)
            self._last_request = time.monotonic()

    MagentoStore.__name__ = "".join(part.capitalize() for part in store_id.split("_")) + "Store"
    MagentoStore.__qualname__ = MagentoStore.__name__
    return MagentoStore
