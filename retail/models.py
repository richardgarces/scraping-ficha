from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse
import re
import unicodedata

from retail.commercial import (
    CARD_NAMES,
    detects_low_stock,
    extract_financing,
    extract_shipping,
    landed_price,
    normalize_variants,
    resolve_condition,
)


@dataclass(frozen=True, slots=True)
class Target:
    kind: str  # search | category | product | url
    query: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    product_id: str | None = None
    raw_url: str | None = None


MAX_DISCOUNT_GAP = 20


def _url_slug(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _sodimac_path_ids(path: str) -> tuple[str | None, str | None, str | None]:
    """Extrae (product_id, slug, sku_id) de /articulo|product/{id}/{slug?}/{sku?}."""
    parts = [part for part in str(path or "").split("/") if part]
    key = next((part for part in ("articulo", "product") if part in parts), None)
    if not key:
        return None, None, None
    idx = parts.index(key)
    product_id = parts[idx + 1] if idx + 1 < len(parts) else None
    if not product_id:
        return None, None, None
    rest = parts[idx + 2 :]
    if not rest:
        return product_id, None, None
    # Forma pública: /articulo/{productId}/{slug}/{skuId}
    if len(rest) >= 2 and rest[-1].isdigit():
        return product_id, rest[0], rest[-1]
    if len(rest) == 1 and rest[0].isdigit() and rest[0] != product_id:
        return product_id, None, rest[0]
    return product_id, rest[0], None


def normalize_product_url(
    store: str | None,
    url: str | None,
    name: str | None = None,
    *,
    sku_id: str | None = None,
    seller: str | None = None,
) -> str | None:
    """Corrige rutas conocidas de tiendas sin modificar URLs de otras cadenas."""
    if not url:
        return url
    text = str(url).strip()
    store_id = str(store or "").strip().lower()
    parsed = urlparse(text)
    path = parsed.path
    if store_id == "sodimac":
        # La API compartida de Falabella devuelve /product/, ruta que Sodimac
        # redirige a la portada. Su ficha pública vigente usa /articulo/{id}/{slug}/{sku}.
        if parsed.netloc.lower() in {"falabella.com", "www.falabella.com", "tottus.cl", "www.tottus.cl"}:
            path = path.replace("/falabella-cl/", "/sodimac-cl/", 1)
            path = path.replace("/tottus-cl/", "/sodimac-cl/", 1)
        path = path.replace("/sodimac-cl/product/", "/sodimac-cl/articulo/", 1)
        product_id, slug, sku_from_path = _sodimac_path_ids(path)
        sku = str(sku_id or sku_from_path or "").strip() or None
        if sku and product_id and sku == product_id:
            sku = sku_from_path if sku_from_path and sku_from_path != product_id else None
        slug = slug or _url_slug(name) or "producto"
        seller_key = re.sub(r"[^A-Z0-9]+", "", str(seller or "").upper())
        # Listados marketplace (p. ej. Tottus) aparecen en la API con pid SODIMAC
        # pero sodimac.cl responde notFound: abrir la vitrina real del seller.
        if product_id and seller_key.startswith("TOTTUS"):
            tail = f"{product_id}/{slug}"
            if sku and sku != product_id:
                tail = f"{tail}/{sku}"
            return f"https://www.tottus.cl/tottus-cl/product/{tail}"
        if product_id:
            path = f"/sodimac-cl/articulo/{product_id}/{slug}"
            if sku and sku != product_id:
                path = f"{path}/{sku}"
        return urlunparse(parsed._replace(scheme="https", netloc="www.sodimac.cl", path=path, params="", fragment=""))
    if store_id == "cruzverde":
        match = re.fullmatch(r"/(?:product|producto)/([A-Z]+_)?(\d+)/?", path, re.I)
        slug = _url_slug(name)
        if match and slug:
            # Algunos ítems llegan como CLMC_296782. La API acepta ambos IDs,
            # pero el router público solo reconoce el número en esta familia.
            return f"https://www.cruzverde.cl/{slug}/{match.group(2)}.html"
    return text


IMAGE_URL_KEYS = (
    "url", "src", "imageUrl", "image_url", "link", "abs_url",
    "thumbnailUrl", "original", "image", "location",
)

IMAGE_CONTAINER_HINTS = (
    "image", "media", "picture", "photo", "gallery", "size", "rendition",
    "original", "large", "zoom", "desktop", "mobile", "small", "thumb",
)


def normalize_image_url(store: str | None, value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if str(store or "").lower() == "pcfactory":
        text = text.replace(
            "https://www.pcfactory.cl/public/foto/",
            "https://assets.pcfactory.cl/public/foto/",
            1,
        )
    return text


def first_image_url(value: Any, base_url: str | None = None) -> str | None:
    """Primera imagen válida en strings, galerías u objetos anidados.

    Las APIs no usan una forma única: algunas entregan una lista, otras un
    objeto ``original/large/small`` y otras anidan la galería varios niveles.
    Se respeta siempre el orden recibido y se devuelve la primera URL útil.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "undefined"}:
            return None
        if text.startswith("//"):
            return f"https:{text}"
        if text.startswith(("http://", "https://", "data:image/")):
            return text
        if base_url and text.startswith(("/", "./", "../")):
            return urljoin(base_url, text)
        return text
    if isinstance(value, (list, tuple)):
        for item in value:
            found = first_image_url(item, base_url)
            if found:
                return found
        return None
    if isinstance(value, dict):
        visited: set[str] = set()
        for key in IMAGE_URL_KEYS:
            if key in value:
                visited.add(key)
            if key in value and (found := first_image_url(value.get(key), base_url)):
                return found
        # Galerías con claves propias de la tienda (large, zoom, desktop, etc.).
        for key, item in value.items():
            hinted = any(hint in str(key).lower() for hint in IMAGE_CONTAINER_HINTS)
            # En contenedores anidados se puede seguir buscando. Para valores
            # escalares exigimos una clave relacionada con imágenes, evitando
            # confundir productId/sku con una URL.
            if key not in visited and (hinted or isinstance(item, (dict, list, tuple))) and (
                found := first_image_url(item, base_url)
            ):
                return found
    return None


def all_image_urls(value: Any, base_url: str | None = None, limit: int = 12) -> list[str]:
    """URLs de una galería, en orden y sin duplicados."""
    found: list[str] = []

    def add(item: Any) -> None:
        if len(found) >= max(1, int(limit)):
            return
        if isinstance(item, str):
            url = first_image_url(item, base_url)
            if url and url not in found:
                found.append(url)
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                add(child)
            return
        if not isinstance(item, dict):
            return
        visited: set[str] = set()
        for key in IMAGE_URL_KEYS:
            if key in item:
                visited.add(key)
                add(item.get(key))
        for key, child in item.items():
            hinted = any(hint in str(key).lower() for hint in IMAGE_CONTAINER_HINTS)
            if key not in visited and (hinted or isinstance(child, (dict, list, tuple))):
                add(child)

    add(value)
    return found


def sane_discount(declared: Any, normal: int | None, current: int | None) -> int | None:
    """Valida el porcentaje que publica la tienda contra la resta de precios.

    Se prefiere el declarado porque es el que sale en la página de origen: Paris
    anuncia 20% comparando normal contra oferta aunque `price` sea el precio con
    tarjeta, y Mercado Libre trunca 51,99 a 51. Pero Lider mandaba en ese campo
    el ahorro en pesos (10819), así que se descarta lo que esté fuera de rango o
    demasiado lejos de la resta.
    """
    computed = round((normal - current) * 100 / normal) if normal and current and normal > current else None
    try:
        value = abs(int(declared)) if declared is not None else None
    except (TypeError, ValueError):
        value = None
    if value is None or not 0 < value < 100:
        return computed
    if computed is not None and abs(value - computed) > MAX_DISCOUNT_GAP:
        return computed
    return value


@dataclass(slots=True)
class Product:
    product_id: str
    sku_id: str
    name: str
    brand: str | None = None
    url: str | None = None
    seller: str | None = None
    seller_id: str | None = None
    price_cmr: int | None = None
    price_internet: int | None = None
    price_normal: int | None = None
    price: int | None = None
    discount_percent: int | None = None
    currency: str = "CLP"
    rating: float | None = None
    reviews: int | None = None
    image_url: str | None = None
    image_urls: list[str] = field(default_factory=list)
    is_sponsored: bool = False
    is_bestseller: bool = False
    category: str | None = None
    category_id: str | None = None
    # Categoría normalizada del catálogo interno. Se conserva separada de
    # ``category`` porque esta última suele ser el breadcrumb propio de la
    # tienda (y puede variar entre comercios para el mismo producto).
    catalog_category: str | None = None
    description: str | None = None
    specifications: dict[str, str] = field(default_factory=dict)
    store: str = ""
    source: str | None = None
    scraped_at: str | None = None
    stock: int | None = None
    availability: str | None = None
    condition: str = "unknown"
    condition_source: str | None = None
    condition_confidence: float | None = None
    price_all_payment: int | None = None
    price_card: int | None = None
    payment_card_name: str | None = None
    installment_count: int | None = None
    installment_total: int | None = None
    financial_cae: float | None = None
    payment_conditions: str | None = None
    shipping_cost: int | None = None
    shipping_free_threshold: int | None = None
    shipping_region: str | None = None
    pickup_available: bool | None = None
    shipping_source: str | None = None
    variants: list[dict[str, Any]] = field(default_factory=list)
    low_stock: bool = False
    only_extreme_sizes: bool = False
    stock_verified: bool = False
    stock_checked_at: str | None = None
    entity_id: str | None = None
    entity_confidence: float | None = None
    entity_override: str | None = None
    entity_match_method: str | None = None

    def __post_init__(self) -> None:
        original_price = self.price
        self.price_all_payment = self.price_all_payment or self.price_internet
        self.price_card = self.price_card or self.price_cmr
        self.price_internet = self.price_all_payment or self.price_internet
        self.price_cmr = self.price_card or self.price_cmr
        # El precio comparable debe ser accesible sin contratar una tarjeta.
        if self.price_all_payment:
            self.price = self.price_all_payment
        elif original_price:
            self.price = original_price
        if self.price_card and not self.payment_card_name:
            self.payment_card_name = CARD_NAMES.get(str(self.store or "").lower())

        # Texto con uso explícito (reacondicionado, etc.) gana sobre "new" de
        # tienda: si no, se mezclan precios de nuevo y usado en la comparación.
        resolved, confidence, source = resolve_condition(
            self.condition,
            self.name,
            self.description,
            " ".join(f"{key}: {value}" for key, value in (self.specifications or {}).items()),
        )
        self.condition = resolved
        self.condition_confidence = self.condition_confidence or confidence
        self.condition_source = self.condition_source or source

        shipping = extract_shipping(self.description)
        for key, value in shipping.items():
            if getattr(self, key) is None:
                setattr(self, key, value)
        financing_text = " ".join(filter(None, [
            self.description,
            " ".join(f"{key}: {value}" for key, value in (self.specifications or {}).items()),
        ]))
        for key, value in extract_financing(financing_text).items():
            if getattr(self, key) is None:
                setattr(self, key, value)
        self.variants = normalize_variants(self.variants)
        if self.stock is None:
            variant_stocks = [item["stock"] for item in self.variants if item.get("stock") is not None]
            if variant_stocks and len(variant_stocks) == len(self.variants):
                self.stock = sum(variant_stocks)
        self.low_stock = bool(self.low_stock or detects_low_stock(self.name, self.description, self.availability))

        self.url = normalize_product_url(
            self.store,
            self.url,
            self.name,
            sku_id=self.sku_id,
            seller=self.seller,
        )
        candidates = [normalize_image_url(self.store, url) for url in all_image_urls(self.image_url)]
        candidates = [url for url in candidates if url]
        for url in all_image_urls(self.image_urls):
            url = normalize_image_url(self.store, url)
            if url not in candidates:
                candidates.append(url)
        self.image_urls = candidates
        self.image_url = candidates[0] if candidates else None
        self.discount_percent = sane_discount(self.discount_percent, self.price_normal, self.price)

    @property
    def total_price(self) -> int | None:
        return landed_price(self.price, self.shipping_cost)

    def to_dict(self, flatten_specs: bool = True) -> dict[str, Any]:
        data = asdict(self)
        if flatten_specs:
            data["specifications"] = (
                " | ".join(f"{k}: {v}" for k, v in self.specifications.items())
                if self.specifications
                else ""
            )
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Product:
        allowed = {item.name for item in fields(cls)}
        kwargs = {key: value for key, value in data.items() if key in allowed}
        if not isinstance(kwargs.get("specifications"), dict):
            kwargs["specifications"] = {}
        kwargs.setdefault("product_id", "")
        kwargs.setdefault("sku_id", "")
        kwargs.setdefault("name", "")
        return cls(**kwargs)
