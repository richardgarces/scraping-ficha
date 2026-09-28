from __future__ import annotations

import csv
import json
from pathlib import Path

from retail.models import Product

FIELDS = [
    "product_id",
    "sku_id",
    "name",
    "brand",
    "price",
    "price_all_payment",
    "price_card",
    "price_cmr",
    "price_internet",
    "price_normal",
    "payment_card_name",
    "installment_count",
    "installment_total",
    "financial_cae",
    "payment_conditions",
    "discount_percent",
    "currency",
    "rating",
    "reviews",
    "seller",
    "seller_id",
    "category",
    "category_id",
    "is_sponsored",
    "is_bestseller",
    "url",
    "image_url",
    "condition",
    "condition_source",
    "condition_confidence",
    "shipping_cost",
    "shipping_free_threshold",
    "shipping_region",
    "pickup_available",
    "shipping_source",
    "stock",
    "availability",
    "variants",
    "low_stock",
    "only_extreme_sizes",
    "stock_verified",
    "stock_checked_at",
    "entity_id",
    "entity_confidence",
    "entity_override",
    "entity_match_method",
    "description",
    "specifications",
    "store",
    "source",
    "scraped_at",
]


def save_products(products: list[Product], path: str | Path) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    # Ejecutar hooks opcionales antes de serializar
    try:
        from retail.hooks import apply_hooks

        products = apply_hooks(products)
    except Exception:
        # No fallar si hooks no están presentes o fallan
        pass

    rows = [product.to_dict() for product in products]
    if suffix == ".json":
        output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return output
    if suffix in {".csv", ""}:
        if suffix == "":
            output = output.with_suffix(".csv")
        with output.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return output
    raise ValueError(f"Formato no soportado: {output.suffix}. Usa .csv o .json")
