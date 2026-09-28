from __future__ import annotations

import json
import re
from typing import Any

from retail.models import Product, first_image_url
from retail.parsers import now_iso, parse_float, parse_int, strip_html
from retail.sources.ripley.urls import product_url

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA.search(html)
    if not match:
        raise ValueError("No se encontró __NEXT_DATA__ en el HTML de Ripley")
    return json.loads(match.group(1))


def listing_from_next_data(payload: dict[str, Any]) -> dict[str, Any]:
    page = payload.get("props", {}).get("pageProps", {})
    findability = page.get("findabilityProps") or {}
    data = findability.get("data") or {}
    limit = int(data.get("limit") or 48) or 48
    offset = int(data.get("offset") or 0)
    total = int(data.get("total") or 0)
    current_page = (offset // limit) + 1 if limit else 1
    return {
        "results": data.get("products") or [],
        "pagination": {
            "count": total,
            "perPage": limit,
            "currentPage": current_page,
        },
        "pageType": findability.get("pageType"),
        "queryParams": findability.get("queryParams") or {},
    }


def _attr_map(attributes: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    if not isinstance(attributes, list):
        return specs
    for item in attributes:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("identifier")
        values = item.get("Values") or item.get("values") or []
        text = None
        if isinstance(values, list) and values:
            first = values[0]
            if isinstance(first, dict):
                text = first.get("values") or first.get("value")
            else:
                text = first
        elif isinstance(values, str):
            text = values
        if name and text not in (None, ""):
            specs[str(name)] = str(text)
    return specs


def _shop_name(item: dict[str, Any]) -> tuple[str | None, str | None]:
    seller = item.get("seller")
    shop = item.get("shop") or {}
    seller_name = seller if isinstance(seller, str) else None
    if isinstance(seller, dict):
        seller_name = seller.get("shopName") or seller.get("legalName") or seller.get("name")
    if isinstance(shop, dict):
        seller_name = seller_name or shop.get("shopName") or shop.get("legalName")
        seller_id = shop.get("sellerId") or shop.get("id")
    else:
        seller_id = None
    return seller_name, str(seller_id) if seller_id is not None else None


def listing_item_to_product(item: dict[str, Any], *, source: str | None = None) -> Product:
    parent_id = str(item.get("parentProductID") or "").rstrip("Pp")
    sku = str(item.get("sku") or parent_id or "").rstrip("Pp")
    name = str(item.get("name") or item.get("description") or "").strip()
    price = parse_int(item.get("priceNumber") or item.get("price"))
    normal = parse_int(item.get("masterPriceNumber") or item.get("oldPrice"))
    reviews = item.get("rating_reviews") or {}
    seller, seller_id = _shop_name(item)
    sponsored = item.get("sponsored") or {}
    return Product(
        product_id=parent_id or sku,
        sku_id=sku,
        name=name,
        brand=item.get("brand") or None,
        url=product_url(sku, parent_id=parent_id) if sku or parent_id else None,
        seller=seller,
        seller_id=seller_id,
        price_cmr=None,
        price_internet=price,
        price_normal=normal,
        price=price,
        discount_percent=parse_int(item.get("discount") or item.get("discountSalePrice")),
        currency=str(item.get("currency") or "CLP"),
        rating=parse_float((reviews or {}).get("score")) if isinstance(reviews, dict) else None,
        reviews=parse_int((reviews or {}).get("count")) if isinstance(reviews, dict) else None,
        image_url=item.get("primaryImage") or None,
        image_urls=item.get("images") or ([item.get("primaryImage")] if item.get("primaryImage") else []),
        is_sponsored=bool(isinstance(sponsored, dict) and sponsored.get("is_sponsored")),
        category_id=item.get("categoryCode") or None,
        description=item.get("description") or None,
        store="ripley",
        source=source,
        scraped_at=now_iso(),
    )


def product_detail_to_product(payload: dict[str, Any]) -> Product:
    page = payload.get("props", {}).get("pageProps", payload)
    detail = page.get("detailProps", page)
    data = detail.get("data") if isinstance(detail, dict) else {}
    product = (data or {}).get("product") or payload.get("product") or payload
    variants = product.get("variants") or []
    variant = variants[0] if isinstance(variants, list) and variants else {}
    prices = (variant.get("price") or (product.get("parentpricestock") or {}).get("price") or {})
    sale = prices.get("sale") or {}
    master = prices.get("master") or {}
    ripley = prices.get("ripley") or {}
    current = parse_int(sale.get("valueNumber") or sale.get("value"))
    normal = parse_int(master.get("valueNumber") or master.get("value"))
    card = parse_int(ripley.get("valueNumber") or ripley.get("value"))
    if card == 0:
        card = None
    seller, seller_id = _shop_name(variant or product)
    crumbs = product.get("breadcrumbs") or []
    category = category_id = None
    if isinstance(crumbs, list) and crumbs:
        last = crumbs[-1] if isinstance(crumbs[-1], dict) else {}
        category = last.get("label")
        category_id = last.get("code") or product.get("categoryCode")
    parent_id = str(product.get("parentProductID") or "")
    sku = str(product.get("sku") or variant.get("sku") or parent_id).rstrip("Pp")
    gallery = product.get("images") or variant.get("images") or product.get("fullImage") or []
    image = first_image_url(gallery)
    reviews = product.get("ratingReviews") or product.get("rating_reviews") or {}
    slug = product.get("canonicalSlug")
    return Product(
        product_id=parent_id or sku,
        sku_id=sku,
        name=str(product.get("name") or product.get("title") or "").strip(),
        brand=product.get("brand") or None,
        url=product_url(sku, slug, parent_id=parent_id) if sku or parent_id else None,
        seller=seller,
        seller_id=seller_id,
        price_cmr=card,
        price_internet=current,
        price_normal=normal,
        price=card or current,
        discount_percent=parse_int(sale.get("discountPercentage") or (prices.get("discount") or {}).get("percentage")),
        currency=str(sale.get("currency") or master.get("currency") or "CLP"),
        rating=parse_float(reviews.get("score") if isinstance(reviews, dict) else None),
        reviews=parse_int(reviews.get("count") if isinstance(reviews, dict) else None),
        image_url=image,
        image_urls=gallery,
        category=category,
        category_id=category_id or product.get("categoryCode"),
        description=strip_html(product.get("longDescription") or product.get("shortDescription")),
        specifications=_attr_map(variant.get("attributes")),
        store="ripley",
        source="product",
        scraped_at=now_iso(),
    )
