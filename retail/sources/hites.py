from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from retail.base import StoreClient
from retail.http import HttpError
from retail.models import Product, Target
from retail.parsers import now_iso, parse_int
from retail.registry import StoreSpec, register

BASE = "https://www.hites.com"
GRID = f"{BASE}/on/demandware.store/Sites-HITES-Site/default/Search-UpdateGrid"
PAGE_SIZE = 12
SORT_MAP = {
    "recomendados": "",
    "precio_asc": "price-low-to-high",
    "precio_desc": "price-high-to-low",
}
_GTM_RE = re.compile(r'data-gtmselectitem="([^"]+)"')
_HREF_RE = re.compile(r'href="(/[^"]+-(\d+)\.html)"')
# Formato antiguo: /pim/978689001/978689001_1.jpg
# Formato nuevo: .../images/original/television-y-video/961015001_1.jpg
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.I)
_IMG_SRC_RE = re.compile(r'\bsrc="([^"]+)"', re.I)
_IMG_PID_RE = re.compile(
    r"/pim/(\d+)/|/(?:images/original/[^\"?]*/)?(\d{6,})(?:_\d+)?\.(?:jpe?g|png|webp)",
    re.I,
)


def _product_id_from_image_url(url: str) -> str | None:
    match = _IMG_PID_RE.search(url or "")
    if not match:
        return None
    return match.group(1) or match.group(2)


def _collect_hites_images(html_text: str) -> dict[str, str]:
    """Primera imagen de producto por ID (tile o galería)."""
    images: dict[str, str] = {}
    for tag in _IMG_TAG_RE.findall(html_text):
        src_match = _IMG_SRC_RE.search(tag)
        if not src_match:
            continue
        image_url = html.unescape(src_match.group(1))
        lowered = tag.lower()
        # Evita logos/ribbons; acepta tiles y cualquier imagen con ID de producto.
        if "product-warranty" in lowered or "ribbon-" in lowered:
            continue
        pid = _product_id_from_image_url(image_url)
        if not pid:
            continue
        if "tile-image" not in lowered and "js-image" not in lowered and "/pim/" not in image_url and "mastercatalog" not in image_url:
            continue
        images.setdefault(pid, image_url)
    return images


def parse_hites_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if query.get("q"):
            return Target(kind="search", query=query["q"][0], raw_url=raw)
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


def parse_hites_grid(html_text: str) -> list[dict[str, Any]]:
    hrefs = {pid: urljoin(BASE + "/", path) for path, pid in _HREF_RE.findall(html_text)}
    # Cada tarjeta puede traer una galería (js-image1, js-image2, ...). El mapa
    # conserva la primera URL no vacía que aparece para el ID del producto.
    images = _collect_hites_images(html_text)

    def image_for(pid: str) -> str | None:
        direct = images.get(pid)
        if direct:
            return direct
        # Hites publica item_id 953407, pero las imágenes pertenecen a la
        # primera variante 953407001. El orden del HTML corresponde al orden
        # de la galería, por lo que la primera coincidencia es la portada.
        root = pid[:6] if len(pid) >= 6 and pid[:6].isdigit() else pid
        return next(
            (url for image_pid, url in images.items() if image_pid.startswith(pid) or image_pid.startswith(root)),
            None,
        )
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in _GTM_RE.findall(html_text):
        try:
            payload = json.loads(html.unescape(raw))
        except ValueError:
            continue
        item = payload.get("item") if isinstance(payload.get("item"), dict) else payload
        if not isinstance(item, dict):
            continue
        pid = str(item.get("item_id") or payload.get("item_id") or "")
        if not pid or pid in seen:
            continue
        price = parse_int(item.get("price") or payload.get("value"))
        if not price:
            continue
        seen.add(pid)
        discount_clp = parse_int(item.get("discount")) or 0
        normal = price + discount_clp if discount_clp else price
        found.append(
            {
                "pid": pid,
                "name": str(item.get("item_name") or "").strip(),
                "brand": item.get("item_brand") or None,
                "url": hrefs.get(pid) or (hrefs.get(pid[:6]) if len(pid) == 9 and pid.isdigit() else None),
                "image": image_for(pid),
                "price": price,
                "price_normal": normal,
                "category": item.get("item_category") or None,
            }
        )
    return [item for item in found if item["url"]]


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
        seller="Hites",
        price_internet=current,
        price_normal=normal,
        price=current,
        discount_percent=discount,
        image_url=item.get("image"),
        category=item.get("category"),
        store="hites",
        source=source,
        scraped_at=now_iso(),
    )


@register(
    StoreSpec(
        id="hites",
        title="Hites",
        site="www.hites.com",
        sort_map=SORT_MAP,
        category_help="Texto de búsqueda; el listado público es Search-UpdateGrid",
        platform="sfcc",
        group="retail",
    )
)
class HitesStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.open_http({"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8", "Referer": f"{BASE}/"})

    def close(self) -> None:
        if self.http:
            self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_hites_target(value)

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
            raise HttpError(f"Producto Hites no encontrado: {parsed.product_id}")
        return products

    def _iter_listing(
        self,
        target: Target,
        *,
        max_pages: int | None,
        max_items: int | None,
        sort: str | None,
    ) -> Iterator[dict[str, Any]]:
        query = target.query or target.product_id or (target.category_name or "").replace("-", " ")
        if not query:
            raise ValueError(f"No se puede scrapear el objetivo: {target}")
        start = 0
        page = 0
        yielded = 0
        while True:
            params: dict[str, Any] = {"q": query, "start": start, "sz": PAGE_SIZE}
            sort_value = SORT_MAP.get(sort or "", sort)
            if sort_value:
                params["srule"] = sort_value
            tiles = parse_hites_grid(self._html(GRID, params))
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
        http = self.http
        if http is None:
            raise HttpError("Sesión HTTP de Hites no inicializada")
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = http.get(url, params=params)
            if status == 200 and body:
                return body
            last_error = HttpError(f"HTTP {status} en Hites", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                continue
            break
        raise last_error or HttpError("Fallo al consultar Hites")
