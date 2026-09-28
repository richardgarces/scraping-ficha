from __future__ import annotations

import json
import math
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import extract_next_data
from retail.sources.falabella.parsers import (
    listing_from_next_data,
    listing_item_to_product,
    product_detail_to_product,
)
from retail.sources.falabella.urls import parse_target

SORT_MAP = {
    "recomendados": "_score,desc",
    "precio_asc": "derived.price.search,asc",
    "precio_desc": "derived.price.search,desc",
    "rating": "product.averageOverallRating,desc",
}


class FalabellaClient:
    store_id = "falabella"
    base = "https://www.falabella.com"
    site = "falabella-cl"
    headers: dict[str, str] | None = {
        "Origin": "https://www.falabella.com",
        "Referer": "https://www.falabella.com/falabella-cl/",
    }
    product_host = "https://www.falabella.com"

    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        self.delay = delay
        self.retries = retries
        self.http = HttpSession(timeout=timeout, headers=self.headers)
        self._geo: dict[str, Any] | None = None
        self._last_request = 0.0

    def rewrite_url(self, url: str) -> str:
        return url

    def parse_target(self, value: str) -> Target:
        return parse_target(value)

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> FalabellaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def pid(self) -> str:
        return str(self.geo()["politicalId"])

    def geo(self) -> dict[str, Any]:
        if self._geo is None:
            payload = self._get_json(f"{self.base}/s/geo/v2/districts/cl", {"politicalId": "default"})
            self._geo = payload.get("data") or payload
        return self._geo

    def search(self, query: str, page: int = 1, sort: str | None = None) -> dict[str, Any]:
        params = self._common_params(page, sort)
        params["Ntt"] = query
        payload = self._get_json(
            f"{self.base}/s/browse/v1/search/cl",
            params,
            ok_types={"Success", "alt"},
        )
        if payload.get("responseType") == "alt":
            return {
                "results": [],
                "pagination": {"count": 0, "perPage": 48, "currentPage": page},
                "altUrl": (payload.get("data") or {}).get("altUrl"),
            }
        return payload.get("data") or payload

    def category(
        self,
        category_id: str,
        category_name: str = "productos",
        page: int = 1,
        sort: str | None = None,
    ) -> dict[str, Any]:
        params = self._common_params(page, sort)
        params["categoryId"] = category_id
        params["categoryName"] = category_name
        payload = self._get_json(f"{self.base}/s/browse/v1/listing/cl", params)
        return payload.get("data") or payload

    def product(self, product_id: str) -> dict[str, Any]:
        hosts = [self.base]
        if self.base.rstrip("/") != self.product_host.rstrip("/"):
            hosts.append(self.product_host)
        seen: set[str] = set()
        current = product_id
        last_error: Exception | None = None
        while current and current not in seen:
            seen.add(current)
            redirected = False
            for host in hosts:
                try:
                    payload = self._get_json(
                        f"{host}/s/browse/v1/product/cl",
                        {"productId": current, "pid": self.pid},
                        ok_types={"Success", "alt"},
                    )
                except HttpError as exc:
                    last_error = exc
                    continue
                if payload.get("responseType") == "alt":
                    next_id = self._product_id_from_path(
                        str((payload.get("data") or {}).get("altUrl") or "")
                    )
                    if next_id and next_id not in seen:
                        current = next_id
                        redirected = True
                        break
                    last_error = HttpError(f"Redirección de producto inválida: {payload}")
                    continue
                return payload
            if not redirected:
                break
        raise last_error or HttpError(f"Producto no encontrado: {product_id}")

    @staticmethod
    def _product_id_from_path(url: str) -> str | None:
        parts = [p for p in url.split("/") if p]
        if "product" in parts:
            idx = parts.index("product")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return None

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
            try:
                return [
                    product_detail_to_product(
                        self.product(parsed.product_id),
                        store=self.store_id,
                        rewrite_url=self.rewrite_url,
                    )
                ]
            except HttpError:
                match = self._product_from_search(parsed.product_id)
                if match:
                    return [match]
                raise

        source = parsed.kind
        products: list[Product] = []
        for item in self.iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(
                item,
                source=source,
                store=self.store_id,
                rewrite_url=self.rewrite_url,
            )
            if detalle and product.product_id:
                try:
                    product = product_detail_to_product(
                        self.product(product.product_id),
                        store=self.store_id,
                        rewrite_url=self.rewrite_url,
                    )
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
        parsed = target if isinstance(target, Target) else self.parse_target(target)
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

    def _product_from_search(self, product_id: str) -> Product | None:
        data = self.search(product_id, page=1)
        alt_id = self._product_id_from_path(str(data.get("altUrl") or ""))
        if alt_id:
            return product_detail_to_product(
                self.product(alt_id),
                store=self.store_id,
                rewrite_url=self.rewrite_url,
            )
        for item in data.get("results") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("productId") or "") == str(product_id) or str(
                item.get("skuId") or ""
            ) == str(product_id):
                return listing_item_to_product(
                    item,
                    source="product",
                    store=self.store_id,
                    rewrite_url=self.rewrite_url,
                )
        return None

    def _listing_page(self, target: Target, page: int, sort: str | None) -> dict[str, Any]:
        if target.kind == "search" and target.query:
            return self.search(target.query, page=page, sort=sort)
        if target.kind == "category" and target.category_id:
            return self.category(
                target.category_id,
                target.category_name or "productos",
                page=page,
                sort=sort,
            )
        if target.raw_url:
            return self._listing_from_html(target.raw_url, page)
        raise ValueError(f"No se puede scrapear el objetivo: {target}")

    def _listing_from_html(self, url: str, page: int) -> dict[str, Any]:
        separator = "&" if "?" in url else "?"
        paged = url if page == 1 and "page=" in url else f"{url}{separator}page={page}"
        html = self._get_text(paged, accept="text/html")
        return listing_from_next_data(extract_next_data(html))

    def _common_params(self, page: int, sort: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "pid": self.pid}
        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            params["sortBy"] = sort_value
        return params

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        ok_types: set[str] | None = None,
    ) -> dict[str, Any]:
        body = self._request(url, params=params)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HttpError(f"Respuesta no JSON desde {url}") from exc
        if not isinstance(payload, dict):
            raise HttpError(f"JSON inesperado desde {url}")
        response_type = payload.get("responseType")
        allowed = ok_types or {"Success"}
        if response_type and response_type not in allowed:
            raise HttpError(f"Error de API Falabella ({response_type}): {payload}")
        return payload

    def _get_text(self, url: str, accept: str | None = None) -> str:
        return self._request(url, accept=accept)

    def _request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, content_type, body = self.http.get(url, params=params)
            if status == 200 and body:
                if accept and "json" in accept and "json" not in content_type and body.lstrip()[:1] != "{":
                    last_error = HttpError(f"{url} no devolvió JSON", status)
                    continue
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
