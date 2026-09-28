from __future__ import annotations

from urllib.parse import parse_qs, unquote, urlparse

from retail.models import Target

SITE_PREFIX = "/falabella-cl"


def normalize_host(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.endswith("falabella.cl"):
        path = parsed.path or "/"
        if not path.startswith("/falabella-cl"):
            path = f"{SITE_PREFIX}{path if path != '/' else ''}"
        return parsed._replace(
            scheme="https",
            netloc="www.falabella.com",
            path=path,
        ).geturl()
    return url


def product_url(product_id: str, slug: str | None = None) -> str:
    slug = slug or "producto"
    return f"https://www.falabella.com/falabella-cl/product/{product_id}/{slug}"


def parse_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        return _from_url(normalize_host(raw))

    if raw.lower().startswith(("cat", "catg")) and " " not in raw:
        return Target(kind="category", category_id=raw, category_name="productos")

    if raw.isdigit():
        return Target(kind="product", product_id=raw)

    return Target(kind="search", query=raw)


def _from_url(url: str) -> Target:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if "product" in parts:
        idx = parts.index("product")
        product_id = parts[idx + 1] if idx + 1 < len(parts) else None
        if product_id:
            return Target(kind="product", product_id=product_id, raw_url=url)

    if "category" in parts:
        idx = parts.index("category")
        category_id = parts[idx + 1] if idx + 1 < len(parts) else None
        category_name = parts[idx + 2] if idx + 2 < len(parts) else "productos"
        if category_id:
            return Target(
                kind="category",
                category_id=category_id,
                category_name=category_name,
                raw_url=url,
            )

    ntt = query.get("Ntt") or query.get("ntt")
    if "search" in parts or ntt:
        term = unquote(ntt[0]) if ntt else None
        return Target(kind="search", query=term, raw_url=url)

    return Target(kind="url", raw_url=url)
