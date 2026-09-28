from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target, first_image_url
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

BASE = "https://salcobrand.cl"
SITEMAP = f"{BASE}/sitemap.xml"
SORT_MAP = {"recomendados": "", "precio_asc": "", "precio_desc": ""}
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_LD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL | re.I)
_LOC_RE = re.compile(r"<loc>(.*?)</loc>", re.I)


def parse_salcobrand_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0] == "products" and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        if parts and parts[0] == "t" and len(parts) > 1:
            return Target(kind="category", category_id=parts[1], category_name=parts[-1], raw_url=raw)
        return Target(kind="url", raw_url=raw)
    lowered = raw.lower().strip("/")
    if lowered in {"medicamentos", "dermocosmetica", "bebe"} or lowered.startswith("t/"):
        slug = lowered.split("/")[-1]
        return Target(kind="category", category_id=slug, category_name=slug)
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", lowered):
        return Target(kind="product", product_id=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


def _graph(html: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in _LD_RE.findall(html):
        try:
            payload = json.loads(block)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("@graph"), list):
            rows.extend(item for item in payload["@graph"] if isinstance(item, dict))
        elif isinstance(payload, dict):
            rows.append(payload)
    return rows


def _types(node: dict[str, Any]) -> str:
    value = node.get("@type")
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def product_from_graph(nodes: list[dict[str, Any]], *, source: str | None = None) -> Product | None:
    by_id = {str(node.get("@id")): node for node in nodes if node.get("@id")}
    product = next((node for node in nodes if "Product" in _types(node)), None)
    if not product:
        return None
    offer = product.get("offers")
    if isinstance(offer, dict) and offer.get("@id") and not offer.get("price"):
        offer = by_id.get(str(offer["@id"]), offer)
    if not isinstance(offer, dict):
        offer = {}
    current = parse_int(offer.get("price"))
    normal = current
    for spec in offer.get("priceSpecification") or []:
        if not isinstance(spec, dict):
            continue
        if "StrikethroughPrice" in str(spec.get("priceType") or ""):
            normal = parse_int(spec.get("price")) or normal
            break
    brand = product.get("brand")
    brand_name = brand.get("name") if isinstance(brand, dict) else brand
    image = first_image_url(product.get("image"))
    ident = str(product.get("sku") or "")
    url = str(product.get("url") or "")
    slug = urlparse(url).path.rstrip("/").split("/")[-1] if url else ident
    return Product(
        product_id=slug or ident,
        sku_id=ident or slug,
        name=str(product.get("name") or "").strip(),
        brand=str(brand_name) if brand_name else None,
        url=url or (f"{BASE}/products/{slug}" if slug else None),
        seller="Salcobrand",
        price_internet=current,
        price_normal=normal,
        price=current,
        image_url=image,
        store="salcobrand",
        source=source,
        scraped_at=now_iso(),
    )


def item_list_urls(nodes: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for node in nodes:
        if "ItemList" not in _types(node):
            continue
        for entry in node.get("itemListElement") or []:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url") or (entry.get("item") or {}).get("url")
            if url:
                urls.append(str(url))
    return urls


def score_url(url: str, tokens: list[str]) -> int:
    slug = urlparse(url).path.lower()
    if not tokens:
        return 0
    hits = sum(1 for token in tokens if token in slug)
    if hits == len(tokens):
        return 100 + hits
    return hits


@register(
    StoreSpec(
        id="salcobrand",
        title="Salcobrand",
        site="www.salcobrand.cl",
        sort_map=SORT_MAP,
        category_help="Taxon Spree, por ejemplo medicamentos",
        extra_category=True,
    )
)
class SalcobrandStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout)
        self._last_request = 0.0
        self._product_urls: list[str] | None = None

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_salcobrand_target(value)

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
        urls = list(self._iter_urls(parsed, max_items=max_items))
        products: list[Product] = []
        for url in urls:
            product = self._product_page(url, source=parsed.kind)
            if product:
                products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        if parsed.kind == "product" and not products:
            raise HttpError(f"Producto Salcobrand no encontrado: {parsed.product_id}")
        return products

    def _iter_urls(self, target: Target, *, max_items: int | None) -> Iterator[str]:
        if target.kind == "product":
            slug = target.product_id or ""
            yield target.raw_url or f"{BASE}/products/{slug}"
            return
        if target.kind == "category":
            html = self._html(f"{BASE}/t/{target.category_id}")
            for url in item_list_urls(_graph(html)):
                yield url
            return
        query = (target.query or "").lower()
        tokens = _TOKEN_RE.findall(query)
        ranked = sorted(
            ((score_url(url, tokens), url) for url in self._sitemap_products()),
            key=lambda item: item[0],
            reverse=True,
        )
        limit = max_items or 8
        yielded = 0
        for score, url in ranked:
            if score <= 0:
                break
            yield url
            yielded += 1
            if yielded >= limit:
                return

    def _sitemap_products(self) -> list[str]:
        if self._product_urls is not None:
            return self._product_urls
        index = self._html(SITEMAP)
        urls: list[str] = []
        for loc in _LOC_RE.findall(index):
            if "sitemap" not in loc or loc.rstrip("/").endswith("sitemap.xml"):
                continue
            body = self._html(loc, pause=0.15)
            for url in _LOC_RE.findall(body):
                if "/products/" in url and url.count("/") >= 4:
                    urls.append(url)
        self._product_urls = urls
        return urls

    def _product_page(self, url: str, *, source: str | None) -> Product | None:
        html = self._html(url)
        return product_from_graph(_graph(html), source=source)

    def _html(self, url: str, *, pause: float | None = None) -> str:
        last_error: Exception | None = None
        wait = self.delay if pause is None else pause
        for attempt in range(1, self.retries + 1):
            if wait > 0:
                elapsed = time.monotonic() - self._last_request
                if self._last_request and elapsed < wait:
                    time.sleep(wait - elapsed)
            self._last_request = time.monotonic()
            status, _ct, body = self.http.get(url)
            if status == 200 and body:
                return body
            last_error = HttpError(f"HTTP {status} en Salcobrand", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError("Fallo al consultar Salcobrand")
