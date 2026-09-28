#!/usr/bin/env python3
"""Reindexa en Qdrant los productos Mongo que tienen una categoría asociada."""

from __future__ import annotations

import argparse
import sys

from retail.models import Product
from retail.mongo import ProductRepository
from retail.qdrant_index import connect_qdrant


def backfill(*, batch_size: int = 500, limit: int = 0, dry_run: bool = False) -> dict[str, int]:
    repo = ProductRepository()
    qdrant = None if dry_run else connect_qdrant()
    if not dry_run and qdrant is None:
        repo.close()
        raise RuntimeError("Qdrant no está disponible.")

    query = {
        "$or": [
            {"catalog_category": {"$nin": [None, ""]}},
            {"category": {"$nin": [None, ""]}},
        ]
    }
    projection = {"_id": 0}
    cursor = repo.collection.find(query, projection).sort("updated_at", -1)
    if limit > 0:
        cursor = cursor.limit(limit)

    scanned = indexed = skipped = 0
    batch: list[Product] = []
    try:
        for document in cursor:
            scanned += 1
            product = Product.from_dict(document)
            if not product.product_id or not product.store:
                skipped += 1
                continue
            batch.append(product)
            if len(batch) < max(1, batch_size):
                continue
            if not dry_run:
                indexed += qdrant.upsert_products(batch)
            batch.clear()
            print(f"Procesados: {scanned} · indexados: {indexed}", flush=True)
        if batch and not dry_run:
            indexed += qdrant.upsert_products(batch)
        if dry_run:
            indexed = scanned - skipped
        return {"scanned": scanned, "indexed": indexed, "skipped": skipped}
    finally:
        repo.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--limit", type=int, default=0, help="0 procesa todos los documentos")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = backfill(
            batch_size=max(1, args.batch_size),
            limit=max(0, args.limit),
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        "Backfill terminado: "
        f"{result['scanned']} revisados, {result['indexed']} indexados, "
        f"{result['skipped']} omitidos."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
