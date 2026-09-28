from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_float, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.mercadolibre.cl"
HEADERS = {
    "Origin": "https://www.mercadolibre.cl",
    "Referer": "https://www.mercadolibre.cl/",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "relevance",
    "precio_asc": "price_asc",
    "precio_desc": "price_desc",
}
MLC_RE = re.compile(r"MLC-?(\d+)", re.I)
CATEGORY_HINTS = {
    "MLC1648": ("notebook", "laptop", "computador", "pc", "tablet", "impresora", "mouse", "teclado"),
    "MLC1051": ("iphone", "celular", "telefono", "samsung", "xiaomi", "motorola"),
    "MLC1000": ("tv", "televisor", "parlante", "audifono", "auricular"),
    "MLC1574": ("zapatilla", "zapatillas", "ropa", "polera"),
    "MLC1246": ("shampoo", "perfume", "crema", "belleza"),
    "MLC1384": ("bebé", "bebe", "pañal", "pañales"),
    "MLC1403": ("leche", "cafe", "café", "arroz", "alimento"),
}


def parse_mercadolibre_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("category"):
            cat = query["category"][0]
            return Target(kind="category", category_id=cat, category_name=cat, raw_url=raw)
        if parts and parts[0] == "ofertas" and query.get("q"):
            return Target(kind="search", query=query["q"][0], raw_url=raw)
        if "listado.mercadolibre" in parsed.netloc:
            slug = "/".join(parts)
            return Target(kind="search", query=slug.replace("-", " ") or None, raw_url=raw)
        if parts and parts[0] == "p":
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        item = MLC_RE.search(parsed.path)
        if item:
            digits = item.group(1)
            ident = f"MLC{digits}"
            kind = "category" if len(digits) <= 5 else "product"
            return Target(
                kind=kind,
                product_id=ident if kind == "product" else None,
                category_id=ident if kind == "category" else None,
                category_name=ident if kind == "category" else None,
                raw_url=raw,
            )
        return Target(kind="url", raw_url=raw)
    match = MLC_RE.fullmatch(raw.replace("_", "")) or MLC_RE.fullmatch(raw)
    if match:
        digits = match.group(1)
        ident = f"MLC{digits}"
        if len(digits) <= 5:
            return Target(kind="category", category_id=ident, category_name=ident)
        return Target(kind="product", product_id=ident)
    return Target(kind="search", query=raw)


def _ctx(html: str) -> dict[str, Any]:
    marker = html.find("_n.ctx.r=")
    if marker < 0:
        raise HttpError("Mercado Libre no devolvió el JSON de ofertas")
    raw = html[marker + 9 :]
    depth = 0
    for index, char in enumerate(raw):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(raw[: index + 1])
    raise HttpError("JSON de ofertas incompleto")


def _component(card: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for item in card.get("components") or []:
        if isinstance(item, dict) and item.get("type") == kind:
            return item
    return None


def _prices(card: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    block = (_component(card, "price") or {}).get("price") or {}
    current = parse_int((block.get("current_price") or {}).get("value"))
    normal = None
    discount = None
    for label in block.get("price_labels") or []:
        for value in label.get("values") or []:
            price = value.get("price") or {}
            if price.get("previous"):
                normal = parse_int(price.get("value"))
    pill = ((block.get("discount_polylabel") or {}).get("values") or [{}])[0]
    discount = parse_int(((pill.get("pill") or {}).get("text")))
    if discount is None and normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    return current, normal or current, discount


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    card = item.get("card") or item
    meta = card.get("metadata") or {}
    title = ((_component(card, "title") or {}).get("title") or {}).get("text") or ""
    seller_raw = ((_component(card, "seller") or {}).get("seller") or {}).get("text") or ""
    seller = re.sub(r"\{[^}]+\}", "", seller_raw).strip() or None
    review = (_component(card, "review_compacted") or {}).get("review_compacted") or {}
    rating = None
    for value in review.get("values") or []:
        if value.get("key") == "label":
            rating = parse_float((value.get("label") or {}).get("text"))
    current, normal, discount = _prices(card)
    pictures = ((card.get("pictures") or {}).get("pictures") or [])
    pic_id = next(
        (str(picture.get("id")).strip() for picture in pictures if isinstance(picture, dict) and picture.get("id")),
        None,
    )
    path = meta.get("url") or ""
    product_id = str(meta.get("id") or meta.get("product_id") or "")
    # Attempt to extract availability/stock from metadata, card fields or components
    def _extract_availability(card: dict[str, Any]) -> tuple[int | None, str | None]:
        meta = card.get("metadata") or {}
        # common metadata fields
        for key in ("available_quantity", "availableQuantity", "availableQuantity"):
            if key in meta and meta.get(key) is not None:
                return (parse_int(meta.get(key)), None)
        # direct card fields
        for key in ("available_quantity", "available", "stock", "quantity"):
            if key in card and card.get(key) is not None:
                return (parse_int(card.get(key)), None)
        # components may contain human-friendly availability
        for comp in card.get("components") or []:
            if not isinstance(comp, dict):
                continue
            ctype = str(comp.get("type") or "").lower()
            if "availability" in ctype or ctype in ("availability", "shipping"):
                # try numeric indicators
                qty = comp.get("availableQuantity") or comp.get("available_quantity") or comp.get("stock") or None
                text = None
                # possible places for human text
                if isinstance(comp.get("texts"), list):
                    for t in comp.get("texts"):
                        if isinstance(t, dict) and t.get("text"):
                            text = t.get("text")
                            break
                if qty is not None:
                    return (parse_int(qty), text)
                if comp.get("availability") and isinstance(comp.get("availability"), dict):
                    msg = comp.get("availability").get("message") or comp.get("availability").get("text")
                    if msg:
                        return (None, str(msg))
        return (None, None)

    stock_val, availability_val = _extract_availability(card)
    return Product(
        product_id=product_id,
        sku_id=str(meta.get("product_id") or product_id),
        name=title.strip(),
        url=f"https://{path}" if path else None,
        seller=seller,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        rating=rating,
        image_url=f"https://http2.mlstatic.com/D_NQ_NP_2X_{pic_id}-F.webp" if pic_id else None,
        store="mercadolibre",
        source=source,
        scraped_at=now_iso(),
        stock=stock_val,
        availability=availability_val,
    )


def _title_matches(name: str, query: str) -> bool:
    tokens = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
    hay = name.lower()
    return all(token in hay for token in tokens) if tokens else True


def _guess_category(query: str, categories: list[dict[str, Any]]) -> str | None:
    q = query.lower()
    for cat_id, hints in CATEGORY_HINTS.items():
        if any(hint in q for hint in hints):
            return cat_id
    best_id = None
    best = 0
    for cat in categories:
        name = str(cat.get("name") or "").lower()
        score = sum(1 for token in q.split() if token and token in name)
        if score > best:
            best = score
            best_id = str(cat.get("id"))
    return best_id if best else None


@register(
    StoreSpec(
        id="mercadolibre",
        title="Mercado Libre Chile",
        site="www.mercadolibre.cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría, por ejemplo MLC1648 (Computación)",
    )
)
class MercadoLibreStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0
        self._warmed = False

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_mercadolibre_target(value)

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
            return [self._product(parsed.product_id, max_pages=max_pages or 3)]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items):
            product = listing_item_to_product(item, source=parsed.kind)
            if parsed.kind == "search" and parsed.query and not _title_matches(product.name, parsed.query):
                continue
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _product(self, product_id: str, *, max_pages: int) -> Product:
        needle = product_id.replace("-", "").upper()
        for item in self._iter_listing(Target(kind="category"), max_pages=max_pages, max_items=None):
            meta = (item.get("card") or {}).get("metadata") or {}
            ids = {str(meta.get("id") or "").replace("-", "").upper(), str(meta.get("product_id") or "").upper()}
            if needle in ids:
                return listing_item_to_product(item, source="product")
        raise HttpError(
            f"Producto {product_id} no está en las ofertas públicas. "
            "El listado general y las fichas /articulo/ están bloqueados."
        )

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
    ) -> Iterator[dict[str, Any]]:
        self._warmup()
        category_id = target.category_id
        if target.kind == "search" and target.query and not category_id:
            category_id = _guess_category(target.query, [])
            if not category_id:
                preview = self._ofertas_page(1, None)
                category_id = _guess_category(target.query, preview.get("categories") or [])
        page = 1
        yielded = 0
        while True:
            data = self._ofertas_page(page, category_id)
            items = data.get("items") or []
            if not items:
                break
            for item in items:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            total_pages = int(data.get("total_pages") or 1)
            if max_pages is not None and page >= max_pages:
                break
            if page >= total_pages:
                break
            page += 1

    def _ofertas_page(self, page: int, category_id: str | None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if category_id:
            params["category"] = category_id
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle()
            status, _ct, body = self.http.get(f"{BASE}/ofertas", params=params)
            if status == 200 and body and "_n.ctx.r=" in body:
                payload = _ctx(body)
                data = payload.get("appProps", {}).get("pageProps", {}).get("data") or {}
                paging = data.get("paging") or {}
                limit = int(paging.get("limit") or 48) or 48
                total = int(paging.get("total") or 0)
                categories = []
                for filt in data.get("availableFilters") or []:
                    if filt.get("id") == "category":
                        categories = filt.get("values") or []
                return {
                    "items": [item for item in (data.get("items") or []) if isinstance(item, dict)],
                    "total_pages": max(1, (total + limit - 1) // limit) if total else 1,
                    "categories": categories,
                }
            if body and ("bot_challenge" in body or "suspicious-traffic" in body):
                last_error = HttpError("Mercado Libre bloqueó la request", status)
            else:
                last_error = HttpError(f"HTTP {status} en Mercado Libre ofertas", status)
            if attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
        raise last_error or HttpError("Fallo al consultar Mercado Libre")

    def _warmup(self) -> None:
        if self._warmed:
            return
        self._throttle()
        self.http.get(BASE + "/")
        self._warmed = True

    def _throttle(self) -> None:
        if self.delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request
        if self._last_request and elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request = time.monotonic()
