"""Decathlon Chile — storefront Next.js propio (no VTEX/Shopify/SFCC).

Listados (búsqueda y categoría PLP) traen productos embebidos en el payload
RSC (`self.__next_f`) con forma:

  {"id":"{supermodelId}_{modelId}","supermodelId":"...","label":"...",
   "images":[{"src":"..."}],"url":"/p/...","models":[{...,"price":{...}}]}

Búsqueda: GET /search?Ntt={q}&from={offset}&size={page_size}
Categoría: GET /{slug}?from={offset}&size={page_size}
  (ej. mujer/calzado-mujer)

Ficha: JSON-LD Product / ProductGroup + path /p/{slug}/{supermodelId}/{variance}m{modelId}

Limitaciones:
- Cloudflare Bot Management puede devolver 403 a clientes sin JS/cookies.
- Algolia figura como experimento (flag off); el listado público es SSR/RSC.
- Hubs CMS (ej. /deportes/running) no son PLP paginados; usar PLPs o search.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

STORE_ID = "decathlon"
TITLE = "Decathlon"
BASE = "https://www.decathlon.cl"
SITE = "www.decathlon.cl"

PAGE_SIZE = 40
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price-asc",
    "precio_desc": "price-desc",
}

HEADERS = {
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
    "Referer": f"{BASE}/",
}

# Producto listado en RSC (tras desescapar \" → ").
_LISTING_PRODUCT_RE = re.compile(
    r'\{"id":"(?P<id>\d+_\d+)",'
    r'"supermodelId":"(?P<super>\d+)",'
    r'"skuId":"(?P<sku>[^"]+)",'
    r'"label":"(?P<label>(?:\\.|[^"\\])*)",'
    r'"images":\[\{"src":"(?P<img>[^"]+)"[^\]]*],"url":"(?P<url>[^"]+)"',
)
_BRAND_RE = re.compile(r'"brand":"([^"]+)"')
_NATURE_RE = re.compile(r'"nature":"([^"]+)"')
_VALUE_RE = re.compile(r'"valueWithTaxes":(\d+)')
_REF_RE = re.compile(r'"referenceValueWithTaxes":(\d+)')
_DISC_RE = re.compile(r'"discountPercentage":(\d+)')
_NEXT_PAGE_RE = re.compile(r'"next":"([^"]+)"')
_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_PRODUCT_PATH_RE = re.compile(
    r"/p/([^/]+)/(\d+)/([^/?#]*m(\d+))",
    re.I,
)


def _decode_rsc_text(raw: str) -> str:
    """Normaliza escapes típicos del flight data de Next.js."""
    text = unescape(raw)
    # Dentro de self.__next_f.push([1,"..."]) los JSON vienen con \"
    text = text.replace('\\"', '"')
    text = text.replace("\\u0026", "&")
    text = text.replace("\\/", "/")
    return text


def _decode_label(raw: str) -> str:
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace('\\"', '"').strip()


def parse_decathlon_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] == "p" and len(parts) >= 3:
            match = _PRODUCT_PATH_RE.search(parsed.path)
            if match:
                model_id = match.group(4)
                super_id = match.group(2)
                return Target(
                    kind="product",
                    product_id=f"{super_id}_{model_id}",
                    raw_url=raw,
                )
            return Target(kind="product", product_id=parts[2], raw_url=raw)
        term = (query.get("Ntt") or query.get("q") or query.get("s") or [None])[0]
        if parts and parts[0] == "search":
            return Target(kind="search", query=term or "", raw_url=raw)
        if parts:
            return Target(
                kind="category",
                category_id="/".join(parts),
                category_name=parts[-1],
                raw_url=raw,
            )
        return Target(kind="url", raw_url=raw)
    if re.fullmatch(r"\d+(?:_\d+)?", raw):
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        path = raw.strip("/")
        return Target(kind="category", category_id=path, category_name=path.split("/")[-1])
    return Target(kind="search", query=raw)


def _price_from_window(window: str) -> tuple[int | None, int | None, int | None]:
    value_m = _VALUE_RE.search(window)
    if not value_m:
        return None, None, None
    # Limita el precio al bloque de la primera aparición de valueWithTaxes
    # (evita arrastrar referenceValue del producto siguiente en el RSC).
    local = window[value_m.start() : value_m.start() + 400]
    ref_m = _REF_RE.search(local)
    disc_m = _DISC_RE.search(local)
    value = parse_int(value_m.group(1))
    reference = parse_int(ref_m.group(1) if ref_m else None)
    discount = parse_int(disc_m.group(1) if disc_m else None)
    normal = reference if reference and value and reference > value else value
    if discount is None and normal and value and normal > value:
        discount = round((normal - value) * 100 / normal)
    return value, normal, discount


def parse_listing_html(html: str) -> list[dict[str, Any]]:
    """Extrae productos del payload RSC de listados search/categoría."""
    text = _decode_rsc_text(html)
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _LISTING_PRODUCT_RE.finditer(text):
        pid = match.group("id")
        if pid in seen:
            continue
        window = text[match.end() : match.end() + 1800]
        next_prod = text.find('{"id":"', match.end())
        if next_prod != -1:
            window = text[match.end() : min(match.end() + 1800, next_prod)]
        price, normal, discount = _price_from_window(window)
        if not price:
            continue
        brand_m = _BRAND_RE.search(window)
        nature_m = _NATURE_RE.search(window)
        path = match.group("url")
        seen.add(pid)
        found.append(
            {
                "id": pid,
                "supermodel_id": match.group("super"),
                "sku": match.group("sku"),
                "name": _decode_label(match.group("label")),
                "brand": brand_m.group(1) if brand_m else None,
                "category": nature_m.group(1) if nature_m else None,
                "url": urljoin(BASE + "/", path.lstrip("/")),
                "image_url": match.group("img"),
                "price": price,
                "price_normal": normal or price,
                "discount_percent": discount,
            }
        )
    return found


def _iter_ld_nodes(payload: Any) -> Iterator[dict[str, Any]]:
    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            for node in payload["@graph"]:
                if isinstance(node, dict):
                    yield node
            return
        yield payload
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_ld_nodes(item)


def parse_product_html(
    html: str,
    *,
    product_id: str | None = None,
    raw_url: str | None = None,
) -> dict[str, Any] | None:
    """Parsea ficha vía JSON-LD Product (+ IDs del path)."""
    path_match = _PRODUCT_PATH_RE.search(raw_url or "")
    super_id = path_match.group(2) if path_match else None
    model_id = path_match.group(4) if path_match else None

    product_node: dict[str, Any] | None = None
    group_node: dict[str, Any] | None = None
    for block in _LD_JSON_RE.findall(html):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in _iter_ld_nodes(payload):
            types = node.get("@type")
            type_set = {types} if isinstance(types, str) else set(types or [])
            if "Product" in type_set and product_node is None:
                product_node = node
            if "ProductGroup" in type_set and group_node is None:
                group_node = node

    if product_node is None and group_node is None:
        # Fallback: mismo parser de listado si el PDP reusa el blob.
        rows = parse_listing_html(html)
        if product_id:
            for row in rows:
                if row["id"] == product_id or row["id"].endswith(f"_{product_id}") or row["id"].startswith(f"{product_id}_"):
                    return row
        return rows[0] if rows else None

    name = str(
        (product_node or {}).get("name")
        or (group_node or {}).get("name")
        or ""
    ).strip()
    brand = None
    brand_raw = (product_node or {}).get("brand") or (group_node or {}).get("brand")
    if isinstance(brand_raw, dict):
        brand = brand_raw.get("name")
    elif isinstance(brand_raw, str):
        brand = brand_raw

    offers = (product_node or {}).get("offers") or {}
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price_spec = offers.get("priceSpecification") if isinstance(offers, dict) else {}
    if not isinstance(price_spec, dict):
        price_spec = {}
    price = parse_int(price_spec.get("price") or offers.get("price"))
    # En ficha el JSON-LD suele traer solo el precio actual; el normal puede
    # aparecer en el flight data.
    text = _decode_rsc_text(html)
    window_price, window_normal, window_disc = _price_from_window(text)
    if price is None:
        price = window_price
    normal = window_normal if window_normal and price and window_normal >= price else price
    discount = window_disc
    if discount is None and normal and price and normal > price:
        discount = round((normal - price) * 100 / normal)

    image = (product_node or {}).get("image") or (group_node or {}).get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url")

    url = None
    if isinstance(offers, dict):
        url = offers.get("url")
    url = url or raw_url
    if url and url.startswith("/"):
        url = urljoin(BASE + "/", url.lstrip("/"))

    if group_node and group_node.get("productGroupID"):
        super_id = str(group_node["productGroupID"])
    ident = product_id
    if not ident and super_id and model_id:
        ident = f"{super_id}_{model_id}"
    elif not ident:
        ident = model_id or super_id
    if not ident or not name or not price:
        return None

    category = None
    crumbs = None
    for block in _LD_JSON_RE.findall(html):
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in _iter_ld_nodes(payload):
            if node.get("@type") == "BreadcrumbList":
                crumbs = node.get("itemListElement") or []
                break
        if crumbs:
            break
    if isinstance(crumbs, list) and crumbs:
        last = crumbs[-1]
        if isinstance(last, dict):
            category = last.get("name")

    return {
        "id": str(ident),
        "supermodel_id": super_id,
        "sku": model_id or str(ident),
        "name": name,
        "brand": brand,
        "category": category,
        "url": url,
        "image_url": image,
        "price": price,
        "price_normal": normal or price,
        "discount_percent": discount,
    }


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current = parse_int(item.get("price"))
    normal = parse_int(item.get("price_normal")) or current
    discount = parse_int(item.get("discount_percent"))
    if discount is None and normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    ident = str(item.get("id") or "")
    return Product(
        product_id=ident,
        sku_id=str(item.get("sku") or ident),
        name=str(item.get("name") or "").strip(),
        brand=item.get("brand"),
        url=item.get("url"),
        seller=TITLE,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image_url"),
        category=item.get("category"),
        store=STORE_ID,
        source=source,
        scraped_at=now_iso(),
    )


def _matches_product_id(item: dict[str, Any], product_id: str) -> bool:
    pid = str(item.get("id") or "")
    if pid == product_id:
        return True
    if product_id.isdigit():
        return pid == product_id or pid.endswith(f"_{product_id}") or pid.startswith(f"{product_id}_")
    return False


@register(
    StoreSpec(
        id=STORE_ID,
        title=TITLE,
        site=SITE,
        sort_map=SORT_MAP,
        category_help="Slug PLP Decathlon, por ejemplo mujer/calzado-mujer o deportes/educacion-fisica/zapatillas-educacion-fisica-ninos",
        platform="decathlon",
        group="deporte",
    )
)
class DecathlonStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.open_http(HEADERS)

    def close(self) -> None:
        if self.http:
            self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_decathlon_target(value)

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
        for item in self._iter_items(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            products.append(product)
            if parsed.kind == "product":
                break
            if max_items is not None and len(products) >= max_items:
                break
        if parsed.kind == "product" and not products:
            raise HttpError(f"Producto Decathlon no encontrado: {parsed.product_id}")
        return products

    def _iter_items(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[dict[str, Any]]:
        if target.kind == "product":
            yield from self._iter_product(target)
            return
        if target.kind == "search":
            query = (target.query or "").strip()
            if not query:
                raise ValueError("Búsqueda Decathlon sin query")
            path = "search"
            base_params: dict[str, Any] = {"Ntt": query}
        elif target.kind == "category":
            path = (target.category_id or "").strip("/")
            if not path:
                raise ValueError("Categoría Decathlon vacía")
            base_params = {}
        elif target.kind == "url" and target.raw_url:
            parsed = urlparse(target.raw_url)
            path = parsed.path.strip("/") or "search"
            base_params = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
        else:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")

        sort_value = SORT_MAP.get(sort or "", sort)
        if sort_value:
            base_params["sort"] = sort_value

        offset = 0
        page = 0
        yielded = 0
        while True:
            params = dict(base_params)
            params["from"] = offset
            params["size"] = PAGE_SIZE
            html = self._html(f"{BASE}/{path}", params)
            rows = parse_listing_html(html)
            if not rows:
                break
            for item in rows:
                yield item
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            page += 1
            if max_pages is not None and page >= max_pages:
                break
            if len(rows) < PAGE_SIZE:
                break
            next_path = self._next_offset(html, offset)
            if next_path is None:
                break
            offset = next_path

    def _iter_product(self, target: Target) -> Iterator[dict[str, Any]]:
        if target.raw_url and "/p/" in target.raw_url:
            html = self._html(target.raw_url)
            item = parse_product_html(html, product_id=target.product_id, raw_url=target.raw_url)
            if item:
                yield item
                return
        # Sin URL: buscar por id (supermodel / model / compuesto).
        query = (target.product_id or "").replace("_", " ")
        html = self._html(f"{BASE}/search", {"Ntt": query, "from": 0, "size": PAGE_SIZE})
        for item in parse_listing_html(html):
            if target.product_id and _matches_product_id(item, target.product_id):
                yield item
                return
        # Si el id es compuesto y no hubo match, intentar ficha con URL mínima no es viable
        # sin slug/variance; devolver vacío y que scrape() eleve HttpError.

    @staticmethod
    def _next_offset(html: str, current: int) -> int | None:
        text = _decode_rsc_text(html)
        match = _NEXT_PAGE_RE.search(text)
        if not match:
            return current + PAGE_SIZE
        nxt = unescape(match.group(1)).replace("\\u0026", "&")
        qs = parse_qs(urlparse("?" + nxt.split("?", 1)[-1]).query) if "?" in nxt else parse_qs(urlparse(nxt).query)
        # next puede ser "search?Ntt=...&from=40&size=40" o path relativo
        if "from" not in qs and "?" in nxt:
            qs = parse_qs(nxt.split("?", 1)[1])
        if "from" in qs:
            return parse_int(qs["from"][0])
        return current + PAGE_SIZE

    def _html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        http = self.http
        if http is None:
            raise HttpError("Sesión HTTP de Decathlon no inicializada")
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = http.get(url, params=params)
            if status == 200 and body and "Just a moment" not in body[:500]:
                return body
            last_error = HttpError(f"HTTP {status} en Decathlon", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                continue
            if status == 200 and body and "Just a moment" in body[:500]:
                last_error = HttpError("Cloudflare challenge en Decathlon", 403)
                if attempt < self.retries:
                    continue
            break
        raise last_error or HttpError("Fallo al consultar Decathlon")
