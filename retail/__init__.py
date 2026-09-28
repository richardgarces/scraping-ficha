"""Núcleo para scrapers de retail: registro de tiendas + modelo común."""

from retail.models import Product, Target
from retail.registry import get_client, list_stores, register

__all__ = ["Product", "Target", "get_client", "list_stores", "register"]
