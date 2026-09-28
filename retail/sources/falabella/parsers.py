from __future__ import annotations

from typing import Any

from retail.models import Product, first_image_url
from retail.parsers import now_iso, parse_clp, parse_float, parse_int, strip_html
from retail.sources.falabella.urls import product_url


def _prices_by_type(prices: Any) -> dict[str, int | None]:
    mapped: dict[str, int | None] = {}
    if not isinstance(prices, list):
        return mapped
    for item in prices:
        if not isinstance(item, dict):
            continue
        mapped[str(item.get("type") or "")] = parse_clp(item.get("price"))
    return mapped


def _discount_percent(badge: Any, normal: int | None, current: int | None) -> int | None:
    if isinstance(badge, dict):
        parsed = parse_int(badge.get("label"))
        if parsed is not None:
            return abs(parsed)
    if normal and current and normal > current:
        return round((normal - current) * 100 / normal)
    return None


def _spec_map(raw: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    items: list[Any] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("specifications") or raw.get("topSpecifications") or []
        if not items and all(isinstance(v, (str, int, float)) for v in raw.values()):
            return {str(k): str(v) for k, v in raw.items()}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("id")
        value = item.get("value")
        if name and value not in (None, ""):
            specs[str(name)] = str(value)
    return specs


def listing_item_to_product(
    item: dict[str, Any],
    *,
    source: str | None = None,
    store: str = "falabella",
    rewrite_url=None,
) -> Product:
    prices = _prices_by_type(item.get("prices"))
    current = prices.get("cmrPrice") or prices.get("internetPrice") or prices.get("normalPrice")
    normal = prices.get("normalPrice")
    slug_url = item.get("url")
    product_id = str(item.get("productId") or item.get("skuId") or "")
    gallery = item.get("mediaUrls")
    image = first_image_url(gallery)
    raw_stock = item.get("availableQuantity")
    if raw_stock is None:
        raw_stock = item.get("stock")
    if raw_stock is None:
        raw_stock = item.get("quantity")
    return Product(
        product_id=product_id,
        sku_id=str(item.get("skuId") or product_id),
        name=str(item.get("displayName") or item.get("name") or "").strip(),
        brand=item.get("brand") or None,
        url=_maybe_rewrite(slug_url or (product_url(product_id) if product_id else None), rewrite_url),
        seller=item.get("sellerName") or None,
        seller_id=item.get("sellerId") or None,
        price_cmr=prices.get("cmrPrice"),
        price_internet=prices.get("internetPrice"),
        price_normal=normal,
        price=current,
        discount_percent=_discount_percent(item.get("discountBadge"), normal, current),
        rating=parse_float(item.get("rating")),
        reviews=parse_int(item.get("totalReviews")),
        image_url=image,
        image_urls=gallery or [],
        is_sponsored=bool(item.get("isSponsored")),
        is_bestseller=bool(item.get("isBestSeller")),
        specifications=_spec_map(item.get("topSpecifications")),
        store=store,
        source=source,
        scraped_at=now_iso(),
        stock=parse_int(raw_stock),
        availability=(item.get("availabilityMessage") or item.get("availability") or None),
    )


def product_detail_to_product(
    payload: dict[str, Any],
    *,
    store: str = "falabella",
    rewrite_url=None,
) -> Product:
    data = payload.get("data") if "data" in payload and isinstance(payload.get("data"), dict) else payload
    variants = data.get("variants") or []
    variant = {}
    if isinstance(variants, list) and variants:
        variant = variants[0]
    elif isinstance(variants, dict) and variants:
        variant = next(iter(variants.values()))

    prices = _prices_by_type(variant.get("prices") or data.get("prices"))
    current = prices.get("cmrPrice") or prices.get("internetPrice") or prices.get("normalPrice")
    normal = prices.get("normalPrice")

    offerings = variant.get("offerings") or []
    seller = seller_id = None
    if isinstance(offerings, list) and offerings and isinstance(offerings[0], dict):
        seller = offerings[0].get("sellerName")
        seller_id = offerings[0].get("sellerId")
    first_offering = offerings[0] if isinstance(offerings, list) and offerings and isinstance(offerings[0], dict) else {}
    raw_stock = variant.get("availableQuantity")
    if raw_stock is None:
        raw_stock = first_offering.get("availableQuantity")
    if raw_stock is None:
        raw_stock = data.get("availableQuantity")
    stock = parse_int(raw_stock)
    availability = (
        variant.get("availabilityMessage")
        or first_offering.get("availabilityMessage")
        or data.get("availabilityMessage")
    )
    seller_info = data.get("sellerInfo")
    if isinstance(seller_info, dict):
        seller = seller or seller_info.get("sellerName") or seller_info.get("name")
        seller_id = seller_id or seller_info.get("sellerId") or seller_info.get("id")

    crumbs = data.get("breadCrumb") or []
    category = category_id = None
    if isinstance(crumbs, list) and crumbs:
        first = crumbs[0] if isinstance(crumbs[0], dict) else {}
        category = first.get("label")
        category_id = first.get("id")

    gallery = data.get("mediaList") or data.get("medias") or variant.get("medias") or []
    image = first_image_url(gallery)

    product_id = str(data.get("id") or variant.get("id") or "")
    slug = data.get("slug")
    specs = _spec_map((data.get("attributes") or {}).get("specifications"))
    if not specs:
        specs = _spec_map((variant.get("attributes") or {}).get("specifications"))

    return Product(
        product_id=product_id,
        sku_id=str(variant.get("id") or product_id),
        name=str(data.get("name") or variant.get("name") or "").strip(),
        brand=data.get("brandName") or None,
        url=_maybe_rewrite(product_url(product_id, slug) if product_id else None, rewrite_url),
        seller=seller,
        seller_id=seller_id,
        price_cmr=prices.get("cmrPrice"),
        price_internet=prices.get("internetPrice"),
        price_normal=normal,
        price=current,
        discount_percent=_discount_percent(variant.get("discountBadge"), normal, current),
        image_url=image,
        image_urls=gallery,
        category=category,
        category_id=category_id,
        description=strip_html(data.get("longDescription") or data.get("description")),
        specifications=specs,
        store=store,
        source="product",
        scraped_at=now_iso(),
        stock=stock,
        availability=availability or (("En stock" if stock > 0 else "Sin stock") if stock is not None else None),
        variants=[
            {
                "id": raw.get("id"),
                "sku": raw.get("sku") or raw.get("id"),
                "name": raw.get("name"),
                "stock": raw.get("availableQuantity"),
                "available": raw.get("available"),
            }
            for raw in (variants if isinstance(variants, list) else variants.values())
            if isinstance(raw, dict)
        ],
    )


def _maybe_rewrite(url: str | None, rewrite_url) -> str | None:
    if url and callable(rewrite_url):
        return rewrite_url(url)
    return url


def listing_from_next_data(payload: dict[str, Any]) -> dict[str, Any]:
    page = payload.get("props", {}).get("pageProps", {})
    return {
        "results": page.get("results") or [],
        "pagination": page.get("pagination") or {},
        "searchTerm": page.get("searchTerm"),
        "currentUrl": page.get("currentUrl"),
    }
