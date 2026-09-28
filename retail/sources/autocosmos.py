from __future__ import annotations

import re
import time
import unicodedata
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import now_iso, parse_money
from retail.registry import StoreSpec, register

BASE = "https://www.autocosmos.cl"
HEADERS = {
    "Referer": f"{BASE}/",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {"recomendados": "0", "precio_asc": "8", "precio_desc": "4"}
ID_RE = re.compile(r"/([0-9a-f]{32})(?:[/?#]|$)", re.I)


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "/", text).strip("/")


def parse_autocosmos_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        match = ID_RE.search(parsed.path)
        if match:
            return Target(kind="product", product_id=match.group(1).lower(), raw_url=raw)
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] == "auto":
            return Target(
                kind="category",
                category_id="/".join(parts[1:]) or "listado",
                category_name=parts[-1] if len(parts) > 1 else "Autos",
                raw_url=raw,
            )
        query = (parse_qs(parsed.query).get("q") or [None])[0]
        return Target(kind="search", query=query, raw_url=raw) if query else Target(kind="url", raw_url=raw)
    if ID_RE.search("/" + raw):
        return Target(kind="product", product_id=ID_RE.search("/" + raw).group(1).lower())
    return Target(kind="search", query=raw)


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.card_depth = 0
        self.current: dict[str, Any] | None = None
        self.active_prop: str | None = None
        self.active_class = ""
        self.cards: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        is_void = tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
        values = {key: value or "" for key, value in attrs}
        classes = values.get("class", "")
        if tag == "article" and "listing-card" in classes.split():
            self.current = {"texts": [], "specs": []}
            self.card_depth = self.depth
        self.depth += 1
        if self.current is None:
            if is_void:
                self.depth -= 1
            return
        prop = values.get("itemprop", "")
        content = values.get("content", "")
        if prop and content:
            self.current[prop] = content
        if tag == "a" and (prop == "url" or not self.current.get("url")) and values.get("href"):
            self.current["url"] = values["href"]
            if values.get("title"):
                self.current.setdefault("title", values["title"])
        if tag in {"img", "source"}:
            image = content or values.get("src") or values.get("data-src") or values.get("srcset", "").split(" ")[0]
            if image and not self.current.get("image"):
                self.current["image"] = image
        self.active_prop = prop or None
        self.active_class = classes
        if is_void:
            self.depth -= 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = " ".join(data.split())
        if not text:
            return
        self.current["texts"].append(text)
        if self.active_prop and self.active_prop not in self.current:
            self.current[self.active_prop] = text
        if "price-title" in self.active_class:
            self.current["price_title"] = text
        if "listing-card__spec" in self.active_class or "listing-card__detail" in self.active_class:
            self.current["specs"].append(text)

    def handle_endtag(self, tag: str) -> None:
        self.depth -= 1
        if self.current is not None and tag == "article" and self.depth == self.card_depth:
            self.cards.append(self.current)
            self.current = None
        self.active_prop = None
        self.active_class = ""


def extract_listing_items(html: str) -> list[dict[str, Any]]:
    parser = _ListingParser()
    parser.feed(html)
    return parser.cards


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    url = urljoin(BASE + "/", str(item.get("url") or "").lstrip("/"))
    ident_match = ID_RE.search(url)
    ident = ident_match.group(1).lower() if ident_match else ""
    price_title = str(item.get("price_title") or "").lower()
    price = None if "pie" in price_title else parse_money(item.get("price"))
    brand = str(item.get("brand") or "").strip() or None
    model = str(item.get("model") or "").strip()
    year = str(item.get("modelDate") or "").strip()
    name = str(item.get("name") or item.get("title") or "").strip()
    if not name:
        name = " ".join(part for part in (year, brand or "", model) if part)
    version = name
    for base in (year, brand, model):
        if base:
            version = re.sub(rf"\b{re.escape(base)}\b", " ", version, flags=re.I)
    version = " ".join(version.split())
    condition_schema = str(item.get("itemCondition") or "").lower()
    condition = "used" if "usedcondition" in condition_schema else "new" if "newcondition" in condition_schema else "unknown"
    mileage_raw = str(item.get("mileageFromOdometer") or "").strip()
    mileage = re.sub(r"\D", "", mileage_raw)
    location = ", ".join(
        part for part in (str(item.get("addressLocality") or "").strip(), str(item.get("addressRegion") or "").strip()) if part
    )
    specs = {
        "vehicle_type": "car",
        "year": year,
        "model": model,
        "version": version,
        "mileage_km": mileage,
        "location": location,
    }
    image = str(item.get("image") or "").strip()
    return Product(
        product_id=ident,
        sku_id=ident,
        name=name,
        brand=brand,
        url=url or None,
        price=price,
        price_internet=price,
        price_normal=price,
        image_url=urljoin(BASE + "/", image) if image else None,
        category="Autos usados" if condition == "used" else "Autos nuevos" if condition == "new" else "Autos",
        description=str(item.get("description") or "").strip() or None,
        specifications={key: value for key, value in specs.items() if value},
        condition=condition,
        condition_source="schema.org" if condition != "unknown" else None,
        condition_confidence=1.0 if condition != "unknown" else None,
        availability="available",
        store="autocosmos",
        source=source,
        scraped_at=now_iso(),
    )


@register(
    StoreSpec(
        id="autocosmos",
        title="Autocosmos",
        site="www.autocosmos.cl",
        sort_map=SORT_MAP,
        category_help="Autos nuevos/usados o ruta marca/modelo",
        platform="html",
        group="autos",
    )
)
class AutocosmosStore(StoreClient):
    def __init__(self, delay: float = 20.0, timeout: float = 30.0, retries: int = 3) -> None:
        # robots.txt publica Crawl-delay: 20; nunca se consulta más rápido.
        super().__init__(delay=max(20.0, delay), timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)

    def parse_target(self, value: str) -> Target:
        return parse_autocosmos_target(value)

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        del detalle
        parsed = target if isinstance(target, Target) else self.parse_target(target)
        pages = max(1, int(max_pages or 1))
        products: list[Product] = []
        seen: set[str] = set()
        for page in range(1, pages + 1):
            url = self._listing_url(parsed, page=page, sort=sort)
            items = extract_listing_items(self._get_html(url))
            added = 0
            for item in items:
                product = listing_item_to_product(item, source=parsed.kind)
                if not product.product_id or product.price is None or product.product_id in seen:
                    continue
                seen.add(product.product_id)
                products.append(product)
                added += 1
                if max_items is not None and len(products) >= max_items:
                    return products
            if not items or not added:
                break
        return products

    def _listing_url(self, target: Target, *, page: int, sort: str | None) -> str:
        if target.kind in {"product", "url", "category"} and target.raw_url:
            raw = target.raw_url
        elif target.kind == "category" and target.category_id:
            raw = f"{BASE}/auto/{target.category_id.strip('/')}"
        else:
            query = _slug(target.query or "")
            if not query:
                raise ValueError("Búsqueda Autocosmos sin término")
            raw = f"{BASE}/auto/listado/{query}"
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        params["sort"] = [SORT_MAP.get(sort or "recomendados", "0")]
        params["seccion"] = ["precio-final"]
        if page > 1:
            params["p"] = [str(page)]
        else:
            params.pop("p", None)
        query_string = urlencode([(key, item) for key, values in params.items() for item in values])
        return urlunparse(parsed._replace(query=query_string))

    def _get_html(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _content_type, body = self.http.get(url)
            if status == 200 and body:
                return body
            last_error = HttpError(f"HTTP {status} en {url}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(20.0, self.delay * attempt))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")
