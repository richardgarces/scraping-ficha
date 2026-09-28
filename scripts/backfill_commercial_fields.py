#!/usr/bin/env python3
"""Prepara documentos existentes para los cinco pilares comerciales.

Por seguridad solo informa cambios salvo que se use ``--apply``. No modifica el
historial antiguo: el historial limpio de precio para todo medio comienza con el
siguiente scraping.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pymongo import MongoClient, UpdateOne

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retail.models import Product


FIELDS = (
    "condition", "condition_source", "condition_confidence",
    "price", "price_all_payment", "price_card", "payment_card_name",
    "installment_count", "installment_total", "financial_cae", "payment_conditions",
    "shipping_cost", "shipping_free_threshold", "shipping_region",
    "pickup_available", "shipping_source", "variants", "stock", "low_stock",
    "only_extreme_sizes",
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Guardar cambios; sin esto solo simula.")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("COMMERCIAL_BACKFILL_LIMIT", "50000")))
    args = parser.parse_args()
    client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=5000)
    collection = client[os.environ.get("MONGODB_DB", "scraping")]["products"]
    scanned = changed = 0
    operations: list[UpdateOne] = []
    try:
        cursor = collection.find({}).sort("updated_at", -1).limit(max(1, min(args.limit, 500000)))
        for document in cursor:
            scanned += 1
            normalized = Product.from_dict(document).to_dict(flatten_specs=False)
            update = {
                field: normalized[field]
                for field in FIELDS
                if field in normalized and normalized[field] is not None and document.get(field) != normalized[field]
            }
            if not update:
                continue
            changed += 1
            if args.apply:
                operations.append(UpdateOne({"_id": document["_id"]}, {"$set": update}))
                if len(operations) >= 500:
                    collection.bulk_write(operations, ordered=False)
                    operations.clear()
        if operations:
            collection.bulk_write(operations, ordered=False)
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "scanned": scanned, "changed": changed}))
    finally:
        client.close()


if __name__ == "__main__":
    main()

