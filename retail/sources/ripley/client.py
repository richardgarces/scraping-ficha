from __future__ import annotations

import math
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import extract_next_data
from retail.sources.ripley.parsers import (
    listing_from_next_data,
    listing_item_to_product,
    product_detail_to_product,
)
from retail.sources.ripley.urls import parse_target, product_url

BASE = "https://simple.ripley.cl"
HEADERS = {
    "Origin": "https://simple.ripley.cl",
    "Referer": "https://simple.ripley.cl/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "relevance_desc",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
    "rating": "score_desc",
}


class RipleyClient:
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        self.delay = delay
        self.retries = retries
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> RipleyClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def search(self, query: str, page: int = 1, sort: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        else:
            params["sort"] = SORT_MAP["recomendados"]
        url = f"{BASE}/search/{quote(query)}"
        return listing_from_next_data(extract_next_data(self._get_html(url, params)))

    def category(self, slug: str, page: int = 1, sort: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sort"] = sort_value
        url = f"{BASE}/{slug.strip('/')}"
        return listing_from_next_data(extract_next_data(self._get_html(url, params)))

    def product(self, sku: str) -> dict[str, Any]:
        html = self._get_html(product_url(sku))
        return extract_next_data(html)

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        parsed = target if isinstance(target, Target) else parse_target(target)
        if parsed.kind == "product" and parsed.product_id:
            return [product_detail_to_product(self.product(parsed.product_id))]

        source = parsed.kind
        products: list[Product] = []
        for item in self.iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=source)
            ident = product.product_id if str(product.product_id).upper().startswith("MPM") else product.sku_id
            if detalle and ident:
                try:
                    product = product_detail_to_product(self.product(ident))
                    product.source = source
                except HttpError:
                    pass
            products.append(product)
        return products

    def iter_listing(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        parsed = target if isinstance(target, Target) else parse_target(target)
        page = 1
        yielded = 0
        while True:
            data = self._listing_page(parsed, page, sort)
            results = data.get("results") or []
            if not results:
                break
            for item in results:
                if not isinstance(item, dict):
                    continue
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            pagination = data.get("pagination") or {}
            current = int(pagination.get("currentPage") or page)
            count = int(pagination.get("count") or 0)
            per_page = int(pagination.get("perPage") or 48) or 48
            total_pages = math.ceil(count / per_page) if count else current
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break
            page = current + 1

    def _listing_page(self, target: Target, page: int, sort: str | None) -> dict[str, Any]:
        if target.kind == "search" and target.query:
            return self.search(target.query, page=page, sort=sort)
        if target.kind == "category" and target.category_id:
            return self.category(target.category_id, page=page, sort=sort)
        if target.raw_url:
            return listing_from_next_data(extract_next_data(self._get_html(target.raw_url, {"page": page})))
        raise ValueError(f"No se puede scrapear el objetivo: {target}")

    def _get_html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _content_type, body = self.http.get(url, params=params)
            if status == 200 and body and "__NEXT_DATA__" in body:
                return body
            last_error = HttpError(f"HTTP {status} en {url}?{urlencode(params or {})}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        wait = self.delay - elapsed
        if wait > 0 and self._last_request:
            time.sleep(wait)
        self._last_request = time.monotonic()
