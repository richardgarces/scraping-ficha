from urllib.parse import parse_qs, unquote, urlparse

from retail.base import StoreClient
from retail.models import Target
from retail.registry import StoreSpec, register
from retail.sources.falabella import FalabellaClient, SORT_MAP


def parse_tottus_target(value: str) -> Target:
    raw = value.strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)
        if "articulo" in parts or "product" in parts:
            key = "articulo" if "articulo" in parts else "product"
            idx = parts.index(key)
            product_id = parts[idx + 1] if idx + 1 < len(parts) else None
            if product_id:
                return Target(kind="product", product_id=product_id, raw_url=raw)
        if "category" in parts:
            idx = parts.index("category")
            category_id = parts[idx + 1] if idx + 1 < len(parts) else None
            category_name = parts[idx + 2] if idx + 2 < len(parts) else "productos"
            if category_id:
                return Target(
                    kind="category",
                    category_id=category_id,
                    category_name=category_name,
                    raw_url=raw,
                )
        ntt = query.get("Ntt") or query.get("ntt")
        if "search" in parts or "buscar" in parts or ntt:
            return Target(kind="search", query=unquote(ntt[0]) if ntt else None, raw_url=raw)
        return Target(kind="url", raw_url=raw)
    if raw.lower().startswith(("cat", "catg")) and " " not in raw:
        return Target(kind="category", category_id=raw, category_name="productos")
    if raw.isdigit():
        return Target(kind="product", product_id=raw)
    return Target(kind="search", query=raw)


@register(
    StoreSpec(
        id="tottus",
        title="Tottus Chile",
        site="www.tottus.cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría Falabella/Tottus, por ejemplo CATGxxxx",
        extra_category=True,
        platform="falabella",
    )
)
class TottusStore(FalabellaClient, StoreClient):
    store_id = "tottus"
    base = "https://www.tottus.cl"
    site = "tottus-cl"
    headers = {
        "Origin": "https://www.tottus.cl",
        "Referer": "https://www.tottus.cl/tottus-cl/",
    }

    def rewrite_url(self, url: str) -> str:
        return url.replace(
            "https://www.falabella.com/falabella-cl",
            "https://www.tottus.cl/tottus-cl",
        )

    def parse_target(self, value: str) -> Target:
        return parse_tottus_target(value)

    def category_target(self, args) -> Target:
        return Target(
            kind="category",
            category_id=args.category_id,
            category_name=getattr(args, "nombre", None) or "productos",
        )
