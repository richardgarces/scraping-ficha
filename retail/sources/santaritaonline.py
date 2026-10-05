"""Santa Rita Online — WordPress/WooCommerce (tema Porto + custom Moovmedia).

La Store API (`/wp-json/wc/store/v1/products`) existe pero en la práctica suele
devolver HTTP 500, así que el cliente scrapea HTML de listados/ficha.

Age gate: cookie `resp-agev-age-verification-passed=verified` (plugin
responsive-age-verification). Sin interacción UI.

Comuna: el sitio deja por defecto Región Metropolitana / Providencia en sesión
nueva; no hace falta set_location para listar precios. Se documenta el default.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int, parse_money, strip_html
from retail.registry import StoreSpec, register

STORE_ID = "santaritaonline"
TITLE = "Santa Rita Online"
BASE = "https://santaritaonline.com"
SITE = "santaritaonline.com"

# Age verification (DesignSmoke responsive-age-verification)
AGE_COOKIE = "resp-agev-age-verification-passed=verified"
# Default shipping commune shown by the site on a fresh session.
DEFAULT_REGION = "METROPOLITANA"
DEFAULT_COMUNA = "PROVIDENCIA"

HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "text/html,application/xhtml+xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Cookie": AGE_COOKIE,
}
SORT_MAP = {
    "recomendados": "menu_order",
    "precio_asc": "price",
    "precio_desc": "price-desc",
}
PAGE_SIZE_HINT = 18

_CARD_RE = re.compile(
    r'<li[^>]*class="[^"]*product-col[^"]*product[^"]*"[^>]*>(.*?)</li>',
    re.I | re.S,
)
_GTM_RE = re.compile(r'data-gtm4wp_product_data="([^"]+)"', re.I)
_PRICE_BLOCK_RE = re.compile(
    r'<span class="price">.*?(?:</del>\s*</span>|(?:</span>\s*){3})',
    re.I | re.S,
)
_INS_PRICE_RE = re.compile(r"<ins[^>]*>(.*?)</ins>", re.I | re.S)
_DEL_PRICE_RE = re.compile(r"<del[^>]*>(.*?)</del>", re.I | re.S)
_AMOUNT_RE = re.compile(
    r'woocommerce-Price-amount[^>]*>.*?</(?:span|bdi)>',
    re.I | re.S,
)

_IMG_RE = re.compile(
    r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\'][^>]*class="[^"]*wp-post-image',
    re.I,
)
_IMG_FALLBACK_RE = re.compile(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)["\']', re.I)
_HREF_PRODUCT_RE = re.compile(
    r'href=["\'](https?://[^"\']+/producto/[^"\']+/?)["\']',
    re.I,
)
_TITLE_RE = re.compile(
    r'woocommerce-loop-product__title[^>]*>(.*?)</h3>',
    re.I | re.S,
)
_ONSALE_RE = re.compile(r'class="onsale"[^>]*>(.*?)</', re.I | re.S)
_SKU_RE = re.compile(r'data-product_sku=["\']([^"\']+)["\']', re.I)
_ID_RE = re.compile(r'data-product_id=["\'](\d+)["\']', re.I)
_POST_ID_RE = re.compile(r'\bpost-(\d+)\b', re.I)
_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_SKU_META_RE = re.compile(r'<span class="sku"[^>]*>(.*?)</span>', re.I | re.S)
_ADD_TO_CART_RE = re.compile(
    r'name=["\']add-to-cart["\'][^>]*value=["\'](\d+)["\']',
    re.I,
)


def parse_santaritaonline_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if parts and parts[0] in {"producto", "product"} and len(parts) > 1:
            return Target(kind="product", product_id=parts[1], raw_url=raw)
        term = (query.get("s") or query.get("q") or [None])[0]
        if term or (parts and parts[0] in {"search", "buscar"}):
            return Target(kind="search", query=term or "", raw_url=raw)
        if parts and parts[0] in {"categoria", "categoria-producto", "product-category"}:
            slug = "/".join(parts[1:]) if len(parts) > 1 else None
            return Target(kind="category", category_id=slug, raw_url=raw)
        if parts and parts[0] == "tienda":
            return Target(kind="category", category_id="tienda", raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    if "/" in raw and " " not in raw:
        path = raw.strip("/")
        if path.startswith(("categoria/", "categoria-producto/", "product-category/")):
            path = path.split("/", 1)[1]
        return Target(kind="category", category_id=path)
    return Target(kind="search", query=raw)


def _abs_url(path: str | None) -> str | None:
    if not path:
        return None
    text = unescape(str(path).strip())
    if not text or text.startswith("data:"):
        return None
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith(("http://", "https://")):
        return text.split("?", 1)[0]
    return urljoin(BASE + "/", text.lstrip("/")).split("?", 1)[0]


def _slug_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts and parts[0] in {"producto", "product"} and len(parts) > 1:
        return parts[1]
    return parts[-1] if parts else None


def _prices_from_price_html(block: str) -> tuple[int | None, int | None]:
    ins = _INS_PRICE_RE.findall(block)
    deleted = _DEL_PRICE_RE.findall(block)
    if ins and deleted:
        current = parse_money(strip_html(ins[0]))
        normal = parse_money(strip_html(deleted[0]))
        if current or normal:
            return current or normal, normal or current
    amounts = [parse_money(strip_html(x)) for x in _AMOUNT_RE.findall(block)]
    values = [v for v in amounts if v]
    if not values:
        plain = strip_html(block) or ""
        single = parse_money(plain)
        return single, single
    if len(values) >= 2 and values[0] != values[1]:
        # WooCommerce suele poner oferta (ins) primero y tarifa (del) después.
        low, high = min(values[0], values[1]), max(values[0], values[1])
        return low, high
    return values[0], values[0]


def _parse_gtm(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(unescape(raw))
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_listing_html(html: str) -> list[dict[str, Any]]:
    """Extrae ítems de un listado WooCommerce (ul.products / product-col)."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in _CARD_RE.finditer(html or ""):
        card = match.group(0)
        gtm_match = _GTM_RE.search(card)
        gtm = _parse_gtm(gtm_match.group(1)) if gtm_match else {}
        href_match = _HREF_PRODUCT_RE.search(card)
        url = _abs_url(gtm.get("productlink") or (href_match.group(1) if href_match else None))
        product_id = str(
            gtm.get("item_id")
            or gtm.get("internal_id")
            or gtm.get("id")
            or (_ID_RE.search(card).group(1) if _ID_RE.search(card) else "")
            or (_POST_ID_RE.search(card).group(1) if _POST_ID_RE.search(card) else "")
            or _slug_from_url(url)
            or ""
        )
        if not product_id or product_id in seen:
            continue
        seen.add(product_id)
        title_match = _TITLE_RE.search(card)
        name = str(gtm.get("item_name") or "").strip()
        if not name and title_match:
            name = strip_html(title_match.group(1)) or ""
        price_block = _PRICE_BLOCK_RE.search(card)
        current, normal = (None, None)
        if price_block:
            current, normal = _prices_from_price_html(price_block.group(0))
        if current is None:
            # Fallback: buscar ins/del en toda la tarjeta.
            current, normal = _prices_from_price_html(card)
        if current is None:
            current = parse_money(gtm.get("price"))
            normal = current
        elif normal is None:
            normal = current
        # Preferir oferta GTM si el HTML no trajo precio actual.
        gtm_price = parse_money(gtm.get("price"))
        if gtm_price and (current is None or current == normal):
            # Mantener normal del HTML si existe y es mayor.
            if normal and normal > gtm_price:
                current = gtm_price
            elif current is None:
                current = gtm_price
                normal = gtm_price
        img_match = _IMG_RE.search(card) or _IMG_FALLBACK_RE.search(card)
        image = _abs_url(img_match.group(1) if img_match else None)
        sku = str(gtm.get("sku") or "").strip()
        if not sku:
            sku_match = _SKU_RE.search(card)
            sku = sku_match.group(1).strip() if sku_match else ""
        discount = None
        onsale = _ONSALE_RE.search(card)
        if onsale:
            discount = parse_int(strip_html(onsale.group(1)))
        if discount is None and normal and current and normal > current:
            discount = round((normal - current) * 100 / normal)
        category = str(gtm.get("item_category") or "").strip() or None
        brand = str(gtm.get("item_brand") or "").strip() or None
        stock = parse_int(gtm.get("stocklevel"))
        stockstatus = str(gtm.get("stockstatus") or "").strip().lower()
        rows.append(
            {
                "id": product_id,
                "sku": sku,
                "name": name,
                "url": url,
                "slug": _slug_from_url(url),
                "price": current,
                "price_normal": normal,
                "discount_percent": discount,
                "image_url": image,
                "category": category,
                "brand": brand or "Santa Rita",
                "stock": stock,
                "availability": (
                    "En stock"
                    if stockstatus == "instock" or (stock is not None and stock > 0)
                    else ("Sin stock" if stockstatus in {"outofstock", "out-of-stock"} else None)
                ),
            }
        )
    return rows


def _schema_products(html: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for match in _LD_JSON_RE.finditer(html or ""):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if isinstance(item, dict) and item.get("@type") == "Product":
                found.append(item)
            elif isinstance(item, dict) and isinstance(item.get("@graph"), list):
                for node in item["@graph"]:
                    if isinstance(node, dict) and node.get("@type") == "Product":
                        found.append(node)
    return found


def parse_product_html(html: str) -> dict[str, Any] | None:
    """Ficha producto: schema.org Product + fallbacks HTML."""
    schemas = _schema_products(html)
    schema = schemas[0] if schemas else {}
    offers = schema.get("offers") if isinstance(schema.get("offers"), dict) else {}
    url = _abs_url(schema.get("url") or offers.get("url"))
    if not url:
        og = re.search(r'property=["\']og:url["\']\s+content=["\']([^"\']+)["\']', html or "", re.I)
        url = _abs_url(og.group(1) if og else None)
    name = str(schema.get("name") or "").strip()
    if not name:
        og = re.search(r'property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html or "", re.I)
        name = (og.group(1).split("|", 1)[0].strip() if og else "") or ""
    sku_match = _SKU_META_RE.search(html or "")
    sku = str(schema.get("sku") or schema.get("mpn") or "").strip()
    if not sku and sku_match:
        sku = strip_html(sku_match.group(1)) or ""
    product_id = (
        (_ADD_TO_CART_RE.search(html or "").group(1) if _ADD_TO_CART_RE.search(html or "") else None)
        or (_POST_ID_RE.search(html or "").group(1) if _POST_ID_RE.search(html or "") else None)
        or _slug_from_url(url)
        or sku
    )
    if not product_id and not name:
        return None
    current = parse_money(offers.get("price"))
    normal = current
    # Precio oferta/normal cerca del add-to-cart si el schema solo trae uno.
    price_near = None
    add = _ADD_TO_CART_RE.search(html or "")
    if add:
        start = max(0, add.start() - 8000)
        price_near = _PRICE_BLOCK_RE.search((html or "")[start : add.end() + 500])
    if price_near:
        offer_price, list_price = _prices_from_price_html(price_near.group(0))
        if offer_price:
            current = offer_price
        if list_price:
            normal = list_price
    images: list[str] = []
    raw_images = schema.get("image")
    if isinstance(raw_images, list):
        for img in raw_images:
            if isinstance(img, dict):
                abs_img = _abs_url(img.get("url") or img.get("contentUrl"))
            else:
                abs_img = _abs_url(str(img))
            if abs_img and abs_img not in images:
                images.append(abs_img)
    elif isinstance(raw_images, dict):
        abs_img = _abs_url(raw_images.get("url") or raw_images.get("contentUrl"))
        if abs_img:
            images.append(abs_img)
    elif raw_images:
        abs_img = _abs_url(str(raw_images))
        if abs_img:
            images.append(abs_img)
    if not images:
        og = re.search(r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html or "", re.I)
        abs_img = _abs_url(og.group(1) if og else None)
        if abs_img:
            images.append(abs_img)
    brand = None
    raw_brand = schema.get("brand")
    if isinstance(raw_brand, dict):
        brand = str(raw_brand.get("name") or "").strip() or None
    elif raw_brand:
        brand = str(raw_brand).strip() or None
    availability = None
    avail = str(offers.get("availability") or "")
    if "InStock" in avail:
        availability = "En stock"
    elif "OutOfStock" in avail:
        availability = "Sin stock"
    discount = None
    if normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    return {
        "id": str(product_id),
        "sku": sku,
        "name": name,
        "url": url,
        "slug": _slug_from_url(url),
        "price": current,
        "price_normal": normal,
        "discount_percent": discount,
        "image_url": images[0] if images else None,
        "image_urls": images,
        "brand": brand or "Santa Rita",
        "description": strip_html(schema.get("description")),
        "availability": availability,
    }


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    current = parse_money(item.get("price"))
    normal = parse_money(item.get("price_normal")) or current
    discount = parse_int(item.get("discount_percent"))
    if discount is None and normal and current and normal > current:
        discount = round((normal - current) * 100 / normal)
    url = _abs_url(item.get("url"))
    slug = str(item.get("slug") or _slug_from_url(url) or "").strip()
    product_id = str(item.get("id") or slug or item.get("sku") or "").strip()
    sku = str(item.get("sku") or "").strip()
    images = item.get("image_urls") if isinstance(item.get("image_urls"), list) else []
    image = _abs_url(item.get("image_url")) or (_abs_url(images[0]) if images else None)
    return Product(
        product_id=product_id,
        sku_id=sku or product_id,
        name=str(item.get("name") or "").strip(),
        brand=str(item.get("brand") or "").strip() or None,
        url=url,
        seller=TITLE,
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=image,
        image_urls=[u for u in (_abs_url(x) for x in images) if u] if images else ([image] if image else []),
        category=str(item.get("category") or "").strip() or None,
        description=strip_html(item.get("description")),
        store=STORE_ID,
        source=source,
        scraped_at=now_iso(),
        stock=parse_int(item.get("stock")),
        availability=str(item.get("availability") or "").strip() or None,
    )


def _with_page(url: str, page: int, sort: str | None) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if page > 1:
        query["paged"] = [str(page)]
    elif "paged" in query:
        query.pop("paged", None)
    sort_value = SORT_MAP.get(sort or "", sort)
    if sort_value and sort_value != "menu_order":
        query["orderby"] = [sort_value]
    new_query = urlencode({k: v[-1] if isinstance(v, list) else v for k, v in query.items()})
    return urlunparse(parsed._replace(query=new_query))


@register(
    StoreSpec(
        id=STORE_ID,
        title=TITLE,
        site=SITE,
        sort_map=SORT_MAP,
        category_help="Slug o ruta de categoría, por ejemplo lineas-de-vino/ultra-premium",
        platform="woocommerce",
        group="gastronomia",
    )
)
class SantaritaonlineStore(StoreClient):
    """Scraping HTML WooCommerce; age gate vía cookie; comuna default Providencia."""

    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._bootstrapped = False

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_santaritaonline_target(value)

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
        self._ensure_session()
        if parsed.kind == "product":
            item = self._product(parsed)
            product = listing_item_to_product(item, source="product")
            if not product.name or product.price is None or not product.url:
                raise HttpError(f"Producto {TITLE} incompleto: {parsed.product_id}")
            return [product]
        products: list[Product] = []
        for item in self._iter_listing(parsed, max_pages=max_pages, max_items=max_items, sort=sort):
            product = listing_item_to_product(item, source=parsed.kind)
            if not product.name or product.price is None or not product.url or not product.product_id:
                continue
            if detalle and product.url:
                try:
                    detail = parse_product_html(self._get(product.url))
                except HttpError:
                    detail = None
                if detail:
                    merged = {**item, **{k: v for k, v in detail.items() if v not in (None, "", [])}}
                    product = listing_item_to_product(merged, source=parsed.kind)
            products.append(product)
            if max_items is not None and len(products) >= max_items:
                break
        return products

    def _ensure_session(self) -> None:
        """Visita home para PHPSESSID; comuna default ya es Providencia."""
        if self._bootstrapped:
            return
        try:
            self._get(f"{BASE}/")
        except HttpError:
            pass
        self._bootstrapped = True

    def _product(self, target: Target) -> dict[str, Any]:
        ident = str(target.product_id or "").strip().strip("/")
        url = target.raw_url
        if url and "/producto/" in url:
            html = self._get(url)
            item = parse_product_html(html)
            if item:
                return item
        if ident.isdigit():
            # WP REST da slug/link; la ficha HTML trae precio (Store API suele 500).
            status, _ct, raw = self._request("GET", f"{BASE}/wp-json/wp/v2/product/{ident}")
            if status == 200 and raw:
                try:
                    payload = json.loads(raw.lstrip("\ufeff"))
                except ValueError:
                    payload = None
                if isinstance(payload, dict) and payload.get("link"):
                    html = self._get(str(payload["link"]))
                    item = parse_product_html(html)
                    if item:
                        item["id"] = str(payload.get("id") or ident)
                        if payload.get("slug"):
                            item["slug"] = str(payload["slug"])
                        return item
            raise HttpError(f"Producto {TITLE} no encontrado: {ident}", status)
        html = self._get(f"{BASE}/producto/{ident.strip('/')}/")
        item = parse_product_html(html)
        if not item:
            raise HttpError(f"Producto {TITLE} no encontrado: {ident}")
        return item

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
            rows = self._page(target, page, sort)
            if not rows:
                break
            for row in rows:
                yield row
                yielded += 1
                if max_items is not None and yielded >= max_items:
                    return
            if max_pages is not None and page >= max_pages:
                break
            if len(rows) < PAGE_SIZE_HINT:
                break
            page += 1

    def _page(self, target: Target, page: int, sort: str | None) -> list[dict[str, Any]]:
        url = self._listing_url(target)
        page_url = _with_page(url, page, sort)
        html = self._get(page_url)
        return parse_listing_html(html)

    def _listing_url(self, target: Target) -> str:
        if target.kind == "search":
            query = str(target.query or "").strip()
            return f"{BASE}/?{urlencode({'s': query, 'post_type': 'product'})}"
        if target.kind == "category":
            if target.raw_url and urlparse(target.raw_url).path.strip("/"):
                return target.raw_url.split("?", 1)[0].rstrip("/") + "/"
            category = str(target.category_id or "").strip().strip("/")
            if not category or category == "tienda":
                return f"{BASE}/tienda/"
            return f"{BASE}/categoria/{category}/"
        if target.kind == "url" and target.raw_url:
            return target.raw_url
        raise ValueError(f"No se puede scrapear el objetivo: {target}")

    def _get(self, url: str) -> str:
        from retail.scrapling_html import fetch_html_optional

        scrapling_body = fetch_html_optional(
            STORE_ID, url, timeout=self.timeout
        )
        if scrapling_body:
            return scrapling_body
        status, _ct, text = self._request("GET", url)
        if status != 200 or not text:
            raise HttpError(f"HTTP {status} en {TITLE}: {url}", status)
        return text

    def _request(self, method: str, url: str) -> tuple[int, str, str]:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            try:
                if method.upper() != "GET":
                    raise HttpError(f"Método no soportado: {method}")
                status, content_type, text = self.http.get(url)
            except HttpError:
                raise
            except Exception as exc:  # noqa: BLE001 — reintentos de red
                last_error = exc
                if attempt < self.retries:
                    time.sleep(min(8.0, self.delay * attempt * 2))
                    continue
                raise
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                last_error = HttpError(f"HTTP {status} en {TITLE}", status)
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            return status, content_type, text
        raise last_error or HttpError(f"Fallo al consultar {TITLE}")
