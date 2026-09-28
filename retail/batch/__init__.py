"""Batch diario de catálogo, detección de ofertas y alertas."""

from retail.batch.catalog import default_catalog_path, load_catalog
from retail.batch.runner import refresh_product_index, refresh_store_categories, run_batch

__all__ = [
    "default_catalog_path",
    "load_catalog",
    "refresh_product_index",
    "refresh_store_categories",
    "run_batch",
]

