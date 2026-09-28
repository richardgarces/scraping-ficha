from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

from retail.base import StoreClient
from retail.http import HttpError, HttpSession
from retail.models import Product, Target
from retail.parsers import extract_next_data, now_iso, parse_money
from retail.registry import StoreSpec, register

BASE = "https://www.chileautos.cl"
HEADERS = {
    "Origin": BASE,
    "Referer": f"{BASE}/",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
SORT_MAP = {
    "recomendados": "topdeal",
    "precio_asc": "~Price",
    "precio_desc": "Price",
}
AD_RE = re.compile(r"((?:CL|CP|GI)-AD-\d+)", re.I)
SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug_parts(value: str) -> list[str]:
    text = value.strip().lower()
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    return [part for part in SLUG_RE.split(text) if part]


def parse_chileautos_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [unquote(p) for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        ad = AD_RE.search(parsed.path)
        if ad or (parts and parts[0] == "vehiculos" and len(parts) >= 2 and parts[1] == "detalles"):
            ident = (ad.group(1) if ad else parts[-1]).upper()
            return Target(kind="product", product_id=ident, raw_url=raw)
        term = (query.get("q") or [None])[0]
        if term:
            return Target(kind="search", query=term, raw_url=raw)
        if parts and parts[0] == "vehiculos":
            rest = [p for p in parts[1:] if not p.startswith("_")]
            if rest:
                return Target(
                    kind="category",
                    category_id="/".join(rest),
                    category_name=rest[-1],
                    raw_url=raw,
                )
        return Target(kind="url", raw_url=raw)
    match = AD_RE.fullmatch(raw.replace(" ", ""))
    if match:
        return Target(kind="product", product_id=match.group(1).upper())
    if "/" in raw and " " not in raw:
        path = raw.strip("/")
        if path.startswith("vehiculos/"):
            path = path.split("/", 1)[1]
        return Target(kind="category", category_id=path, category_name=path.split("/")[-1])
    return Target(kind="search", query=raw)


def _abs(path: str | None) -> str | None:
    if not path:
        return None
    text = str(path).strip()
    if text.startswith(("http://", "https://")):
        return text.split("?", 1)[0]
    return urljoin(BASE + "/", text.lstrip("/")).split("?", 1)[0]


def _attr(card: dict[str, Any], key: str) -> Any:
    action = card.get("action") if isinstance(card.get("action"), dict) else {}
    tracking = action.get("tracking") if isinstance(action.get("tracking"), dict) else {}
    attrs = tracking.get("additionalAttributes") if isinstance(tracking.get("additionalAttributes"), dict) else {}
    if key in attrs and attrs[key] not in (None, ""):
        return attrs[key]
    meta = ((tracking.get("providers") or {}).get("csnInsights") or {}).get("metaData") or {}
    short = key.rsplit("/", 1)[-1]
    if short in meta and meta[short] not in (None, ""):
        return meta[short]
    return None


def _texts(node: Any) -> list[str]:
    values: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "Text" and isinstance(node.get("value"), str):
            text = node["value"].strip()
            if text:
                values.append(text)
        for value in node.values():
            values.extend(_texts(value))
    elif isinstance(node, list):
        for item in node:
            values.extend(_texts(item))
    return values


def _walk_cards(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        if node.get("type") == "ListingCard":
            yield node
        for value in node.values():
            yield from _walk_cards(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_cards(item)


def listing_item_to_product(card: dict[str, Any], *, source: str | None = None) -> Product:
    action = card.get("action") if isinstance(card.get("action"), dict) else {}
    data = action.get("data") if isinstance(action.get("data"), dict) else {}
    network_id = str(_attr(card, "tracking/item/networkId") or data.get("id") or "").strip()
    make = str(_attr(card, "tracking/item/make") or "").strip() or None
    model = str(_attr(card, "tracking/item/model") or "").strip() or None
    year = str(_attr(card, "tracking/item/year") or "").strip() or None
    price = parse_money(_attr(card, "tracking/item/price"))
    texts = _texts(card)
    name = str(data.get("prefetchTitle") or "").strip()
    if not name and year and make and model:
        name = f"{year} {make} {model}".strip()
    if not name and texts:
        name = texts[0]
    if texts and len(texts) > 1 and texts[1] and texts[1] not in name:
        # Variante / versión (ej. "1.6T ELEMENTAL")
        if not re.search(r"\$|\bCLP\b|\bkm\b", texts[1], re.I):
            name = f"{name} {texts[1]}".strip()
    version = ""
    if name:
        version = re.sub(rf"\b{re.escape(year or '')}\b", " ", name, flags=re.I) if year else name
        for base in (make, model):
            if base:
                version = re.sub(rf"\b{re.escape(base)}\b", " ", version, flags=re.I)
        version = " ".join(version.split())
    url = _abs(str(data.get("url") or "") or None)
    if not url and network_id:
        url = f"{BASE}/vehiculos/detalles/{network_id}"
    image = str(data.get("prefetchImage") or "").strip() or None
    if not image:
        gallery = card.get("gallery") if isinstance(card.get("gallery"), dict) else {}
        for child in gallery.get("children") or []:
            if isinstance(child, dict) and child.get("type") == "Image" and child.get("url"):
                image = str(child["url"])
                break
    seller = str(data.get("prefetchSellerType") or "").strip() or None
    for text in texts:
        if " / " in text or text in {"Particular", "Agencia"}:
            seller = text
            break
    path = str(data.get("url") or "")
    sponsored = any(token in path for token in ("topspot", "showcase", "gtsViewType"))
    ad_type = str(_attr(card, "tracking/item/adtype") or "").strip()
    folded_type = ad_type.lower()
    condition = "used" if "usado" in folded_type else "new" if "nuevo" in folded_type else "unknown"
    mileage = ""
    for text in texts:
        match = re.search(r"([\d.]+)\s*km\b", text, re.I)
        if match:
            mileage = re.sub(r"\D", "", match.group(1))
            break
    return Product(
        product_id=network_id.upper() if network_id else "",
        sku_id=network_id.upper() if network_id else "",
        name=name,
        brand=make,
        url=url,
        seller=seller,
        price_internet=price,
        price_normal=price,
        price=price,
        image_url=image,
        is_sponsored=sponsored,
        category=ad_type or None,
        condition=condition,
        condition_source="Chileautos" if condition != "unknown" else None,
        condition_confidence=1.0 if condition != "unknown" else None,
        availability="available",
        store="chileautos",
        source=source,
        scraped_at=now_iso(),
        specifications={
            key: value
            for key, value in {
                "year": year or "",
                "model": model or "",
                "version": version,
                "vehicle_type": "car",
                "mileage_km": mileage,
                "state": str(_attr(card, "tracking/item/state") or ""),
            }.items()
            if value
        },
    )


def extract_listing_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    cards: list[dict[str, Any]] = []
    for card in _walk_cards(payload):
        ident = str(_attr(card, "tracking/item/networkId") or "").strip().upper()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        cards.append(card)
    return cards


@register(
    StoreSpec(
        id="chileautos",
        title="Chileautos",
        site="www.chileautos.cl",
        sort_map=SORT_MAP,
        category_help="Ruta Carsales, por ejemplo toyota o toyota/yaris",
        platform="carsales",
        group="autos",
    )
)
class ChileautosStore(StoreClient):
    def __init__(self, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        super().__init__(delay=delay, timeout=timeout, retries=retries)
        self.http = HttpSession(timeout=timeout, headers=HEADERS)
        self._last_request = 0.0

    def close(self) -> None:
        self.http.close()

    def parse_target(self, value: str) -> Target:
        return parse_chileautos_target(value)

    def scrape(
        self,
        target: str | Target,
        *,
        max_pages: int | None = 1,
        max_items: int | None = None,
        sort: str | None = None,
        detalle: bool = False,
    ) -> list[Product]:
        del detalle  # listados SSR ya traen precio/nombre/url
        parsed = target if isinstance(target, Target) else self.parse_target(target)
        if parsed.kind == "product":
            product = self._product(parsed)
            if product.price is None:
                raise HttpError(f"Aviso Chileautos sin precio: {parsed.product_id}")
            return [product]
        products: list[Product] = []
        seen: set[str] = set()
        pages = 1 if max_pages is None else max(1, max_pages)
        for page in range(1, pages + 1):
            added = 0
            cards = self._listing_cards(parsed, sort=sort, page=page)
            for card in cards:
                product = listing_item_to_product(card, source=parsed.kind)
                if not product.product_id or product.price is None or product.product_id in seen:
                    continue
                seen.add(product.product_id)
                products.append(product)
                added += 1
                if max_items is not None and len(products) >= max_items:
                    return products
            if not cards or not added:
                break
        return products

    def _product(self, target: Target) -> Product:
        ident = str(target.product_id or "").upper()
        url = target.raw_url or f"{BASE}/vehiculos/detalles/{ident}"
        html = self._get_html(url)
        payload = extract_next_data(html)
        cards = extract_listing_cards(payload)
        if cards:
            return listing_item_to_product(cards[0], source="product")
        price = _find_price(payload)
        title = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
        name = title.group(1).split("|")[0].strip() if title else ident
        name = re.sub(r"\s*[-–]\s*chileautos.*$", "", name, flags=re.I).strip() or ident
        return Product(
            product_id=ident,
            sku_id=ident,
            name=name,
            url=_abs(url),
            price=price,
            price_internet=price,
            price_normal=price,
            store="chileautos",
            source="product",
            scraped_at=now_iso(),
        )

    def _listing_cards(self, target: Target, *, sort: str | None, page: int = 1) -> list[dict[str, Any]]:
        url, params = self._listing_url(target, sort=sort, page=page)
        payload = extract_next_data(self._get_html(url, params=params))
        return extract_listing_cards(payload)

    def _listing_url(
        self, target: Target, *, sort: str | None, page: int = 1
    ) -> tuple[str, dict[str, Any] | None]:
        sort_key = SORT_MAP.get(sort or "recomendados", SORT_MAP["recomendados"])
        params: dict[str, Any] = {"sort": sort_key} if sort_key and sort_key != "topdeal" else {}
        if page > 1:
            params["page"] = page
        if target.raw_url and target.kind in {"url", "category"}:
            parsed = urlparse(target.raw_url)
            existing = parse_qs(parsed.query)
            existing.update({key: [str(value)] for key, value in params.items()})
            clean_url = urlunparse(parsed._replace(query=""))
            flat = {key: values[-1] for key, values in existing.items() if values}
            return clean_url, flat or None
        if target.kind == "category" and target.category_id:
            path = target.category_id.strip("/")
            return f"{BASE}/vehiculos/{path}", params or None
        query = (target.query or "").strip()
        if not query:
            raise ValueError("Búsqueda Chileautos sin término")
        parts = _slug_parts(query)
        if not parts:
            raise ValueError(f"Búsqueda Chileautos inválida: {query}")
        # Path make[/model]: filtra de verdad. ?q= y _keywords- no filtran (y a veces DataDome 403).
        return f"{BASE}/vehiculos/{'/'.join(parts)}", params or None

    def _get_html(self, url: str, params: dict[str, Any] | None = None) -> str:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self.throttle()
            status, _ct, body = self.http.get(url, params=params)
            if status == 200 and body and "__NEXT_DATA__" in body:
                return body
            if status == 403 and body and "captcha-delivery.com" in body:
                last_error = HttpError(
                    "Chileautos bloqueó la solicitud (DataDome/captcha)",
                    status,
                )
            else:
                last_error = HttpError(f"HTTP {status} en {url}", status)
            if status in {403, 429, 500, 502, 503, 504} and attempt < self.retries:
                time.sleep(min(8.0, self.delay * attempt * 2))
                continue
            break
        raise last_error or HttpError(f"Fallo al consultar {url}")


def _find_price(payload: Any) -> int | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"price", "tracking/item/price"} and value not in (None, ""):
                amount = parse_money(value)
                if amount:
                    return amount
            found = _find_price(value)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_price(item)
            if found:
                return found
    return None
