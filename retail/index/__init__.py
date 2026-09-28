"""Índice de productos genéricos para enrutar la búsqueda a tiendas."""

from retail.index.products import (
    ResolvedProduct,
    UNMATCHED_FALLBACK_GROUPS,
    claim_unique_sweep,
    ensure_loaded,
    release_unique_sweep,
    feed_discovered_groups,
    feed_query_aliases,
    feed_search,
    leftover_alias_tokens,
    products_for_letter,
    resolve,
    stores_for,
    unmatched_fallback_groups,
    unmatched_fallback_stores,
    unique_product_id,
)

__all__ = [
    "ResolvedProduct",
    "UNMATCHED_FALLBACK_GROUPS",
    "claim_unique_sweep",
    "ensure_loaded",
    "release_unique_sweep",
    "feed_discovered_groups",
    "feed_query_aliases",
    "feed_search",
    "leftover_alias_tokens",
    "products_for_letter",
    "resolve",
    "stores_for",
    "unmatched_fallback_groups",
    "unmatched_fallback_stores",
    "unique_product_id",
]
