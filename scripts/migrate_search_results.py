#!/usr/bin/env python3
"""Normaliza búsquedas históricas en lotes reanudables.

Dry-run (no escribe):
  python scripts/migrate_search_results.py --dry-run

Migración:
  python scripts/migrate_search_results.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo import MongoClient, UpdateOne

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retail.models import Product
from retail.mongo import stable_product_id
from retail.relevance import fold

MIGRATION_ID = "normalize_search_results_v2"


def emit(event: str, **values: Any) -> None:
    print(json.dumps({"event": event, **values}, default=str), flush=True)


def collection_metrics(db: Any) -> dict[str, Any]:
    output = {}
    for name in ("products", "searches", "search_results", "product_index_queries"):
        stats = db.command("collStats", name) if name in db.list_collection_names() else {}
        output[name] = {
            "count": int(stats.get("count") or 0),
            "size": int(stats.get("size") or 0),
            "storage_size": int(stats.get("storageSize") or 0),
        }
    return output


def offer_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    position = 0
    seen: set[tuple[str, str]] = set()
    for group_position, group in enumerate(document.get("groups") or []):
        for offer_position, offer in enumerate(group.get("offers") or []):
            store = str(offer.get("store") or "").strip()
            external_id = stable_product_id(offer)
            if not store or not external_id:
                rows.append({"invalid": True})
                continue
            key = (store, external_id)
            if key in seen:
                rows.append({"duplicate": True})
                continue
            seen.add(key)
            rows.append({
                "key": key,
                "offer": offer,
                "position": position,
                "group_position": group_position,
                "offer_position": offer_position,
                "group_key": group.get("compare_code") or offer.get("compare_code"),
            })
            position += 1
    return rows


def load_products(products: Any, keys: set[tuple[str, str]]) -> dict[tuple[str, str], ObjectId]:
    found: dict[tuple[str, str], ObjectId] = {}
    wanted = list(keys)
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        for row in products.find(
            {"$or": [{"store": store, "product_id": product_id} for store, product_id in chunk]},
            {"store": 1, "product_id": 1},
        ):
            found[(str(row.get("store") or ""), str(row.get("product_id") or ""))] = row["_id"]
    return found


def insert_missing_products(
    products: Any,
    rows: list[dict[str, Any]],
    canonical: dict[tuple[str, str], ObjectId],
    now: datetime,
) -> int:
    operations = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = row.get("key")
        if not key or key in canonical or key in seen:
            continue
        seen.add(key)
        payload = dict(row["offer"])
        payload["store"], payload["product_id"] = key
        document = Product.from_dict(payload).to_dict(flatten_specs=False)
        document.update({"created_at": now, "updated_at": now})
        operations.append(
            UpdateOne(
                {"store": key[0], "product_id": key[1]},
                {"$setOnInsert": document},
                upsert=True,
            )
        )
    if operations:
        products.bulk_write(operations, ordered=False)
    return len(operations)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--reset-checkpoint", action="store_true")
    parser.add_argument("--keep-payload", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = MongoClient(os.environ.get("MONGODB_URI", "mongodb://localhost:27017"))
    db = client[os.environ.get("MONGODB_DB", "scraping")]
    searches = db.searches
    products = db.products
    results = db.search_results
    migrations = db.schema_migrations

    if not args.dry_run:
        results.create_index(
            [("search_id", 1), ("product_id", 1)],
            unique=True,
            name="search_product_unique",
        )
        results.create_index([("search_id", 1), ("position", 1)], name="search_result_order")
        results.create_index([("product_id", 1), ("created_at", -1)], name="product_search_history")

    if args.reset_checkpoint and not args.dry_run:
        migrations.delete_one({"_id": MIGRATION_ID})
    checkpoint = migrations.find_one({"_id": MIGRATION_ID}) or {}
    last_id = checkpoint.get("last_id") if not args.dry_run else None
    query: dict[str, Any] = {"groups": {"$exists": True}}
    if last_id is not None:
        query["_id"] = {"$gt": last_id}

    totals = {
        "scanned": 0,
        "relations": 0,
        "invalid": 0,
        "duplicates": 0,
        "missing_products_inserted": 0,
    }
    emit("start", dry_run=args.dry_run, checkpoint=last_id, before=collection_metrics(db))

    while True:
        remaining = args.limit - totals["scanned"] if args.limit else args.batch_size
        if args.limit and remaining <= 0:
            break
        size = min(args.batch_size, remaining) if args.limit else args.batch_size
        documents = list(searches.find(query).sort("_id", 1).limit(size))
        if not documents:
            break

        expanded = [(document, offer_rows(document)) for document in documents]
        all_rows = [row for _document, rows in expanded for row in rows]
        keys = {row["key"] for row in all_rows if row.get("key")}
        canonical = load_products(products, keys)

        if not args.dry_run:
            inserted = insert_missing_products(products, all_rows, canonical, datetime.now(timezone.utc))
            totals["missing_products_inserted"] += inserted
            if inserted:
                canonical = load_products(products, keys)

        relation_ops = []
        search_ops = []
        for document, rows in expanded:
            relation_count = 0
            for row in rows:
                if row.get("invalid"):
                    totals["invalid"] += 1
                    continue
                if row.get("duplicate"):
                    totals["duplicates"] += 1
                    continue
                product_id = canonical.get(row["key"])
                if product_id is None:
                    totals["invalid"] += 1
                    continue
                relation = {
                    "search_id": document["_id"],
                    "product_id": product_id,
                    "product_key": f"{row['key'][0]}:{row['key'][1]}",
                    "position": row["position"],
                    "group_position": row["group_position"],
                    "offer_position": row["offer_position"],
                    "created_at": document.get("created_at") or datetime.now(timezone.utc),
                }
                if row.get("group_key"):
                    relation["group_key"] = str(row["group_key"])
                relation_ops.append(
                    UpdateOne(
                        {"search_id": document["_id"], "product_id": product_id},
                        {"$set": relation},
                        upsert=True,
                    )
                )
                relation_count += 1
            totals["relations"] += relation_count
            update: dict[str, Any] = {
                "$set": {
                    "query_normalized": fold(str(document.get("query") or "")),
                    "schema_version": 2,
                    "relation_status": "complete",
                    "result_count": relation_count,
                    "normalized_at": datetime.now(timezone.utc),
                }
            }
            if not args.keep_payload:
                update["$unset"] = {"groups": "", "cheapest": ""}
            search_ops.append(UpdateOne({"_id": document["_id"]}, update))

        if not args.dry_run:
            if relation_ops:
                results.bulk_write(relation_ops, ordered=False)
            searches.bulk_write(search_ops, ordered=False)
            migrations.update_one(
                {"_id": MIGRATION_ID},
                {
                    "$set": {
                        "last_id": documents[-1]["_id"],
                        "updated_at": datetime.now(timezone.utc),
                        "metrics": totals,
                    },
                    "$setOnInsert": {"started_at": datetime.now(timezone.utc)},
                },
                upsert=True,
            )

        totals["scanned"] += len(documents)
        last_id = documents[-1]["_id"]
        query["_id"] = {"$gt": last_id}
        if totals["scanned"] % 10000 < len(documents):
            emit("progress", **totals, last_id=last_id)

    orphan_count = 0
    if not args.dry_run:
        orphan = list(results.aggregate([
            {"$lookup": {"from": "products", "localField": "product_id", "foreignField": "_id", "as": "product"}},
            {"$match": {"product": {"$eq": []}}},
            {"$count": "n"},
        ]))
        orphan_count = int(orphan[0]["n"]) if orphan else 0
        migrations.update_one(
            {"_id": MIGRATION_ID},
            {"$set": {"completed_at": datetime.now(timezone.utc), "orphans": orphan_count, "metrics": totals}},
            upsert=True,
        )
    emit("complete", **totals, orphans=orphan_count, after=collection_metrics(db))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
