#!/usr/bin/env python3
"""Backfill the separated identity model without changing legacy products.

Preview:
  python scripts/migrate_product_identity.py

Apply/resume:
  python scripts/migrate_product_identity.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any

from pymongo import MongoClient

from retail.product_identity import (
    COLLECTIONS,
    build_product_identity_records,
    ensure_product_identity_indexes,
    sync_product_identity_batch,
)

MIGRATION_ID = "product_identity_model_v1"


def emit(event: str, **values: Any) -> None:
    print(json.dumps({"event": event, **values}, default=str), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the new model; default is read-only preview")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0, help="maximum legacy products to scan; 0 means all")
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.reset_checkpoint and not args.apply:
        parser.error("--reset-checkpoint requires --apply")
    return args


def collection_counts(db: Any) -> dict[str, int]:
    return {
        name: int(db[name].count_documents({}))
        for name in ("products", *COLLECTIONS)
    }


def main() -> int:
    args = parse_args()
    client = MongoClient(
        os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        serverSelectionTimeoutMS=4000,
    )
    db = client[os.environ.get("MONGODB_DB", "scraping")]
    legacy = db["products"]
    migrations = db["schema_migrations"]

    if args.apply:
        if args.reset_checkpoint:
            migrations.delete_one({"_id": MIGRATION_ID})
        ensure_product_identity_indexes(db)

    checkpoint = migrations.find_one({"_id": MIGRATION_ID}) if args.apply else None
    if checkpoint and checkpoint.get("status") == "complete":
        emit("already_complete", checkpoint=checkpoint.get("last_id"), counts=collection_counts(db))
        client.close()
        return 0

    last_id = checkpoint.get("last_id") if checkpoint else None
    query: dict[str, Any] = {}
    if args.apply and last_id is not None:
        query["_id"] = {"$gt": last_id}

    before = collection_counts(db)
    scanned = 0
    totals = {name: 0 for name in COLLECTIONS}
    emit(
        "start",
        apply=args.apply,
        checkpoint=last_id,
        batch_size=args.batch_size,
        limit=args.limit,
        before=before,
    )

    while True:
        remaining = args.limit - scanned if args.limit else args.batch_size
        if args.limit and remaining <= 0:
            break
        size = min(args.batch_size, remaining) if args.limit else args.batch_size
        batch = list(legacy.find(query).sort("_id", 1).limit(size))
        if not batch:
            break

        if args.apply:
            batch_totals = sync_product_identity_batch(
                db,
                batch,
                now=datetime.now(timezone.utc),
                include_history=True,
            )
        else:
            batch_totals = {name: 0 for name in COLLECTIONS}
            moment = datetime.now(timezone.utc)
            for document in batch:
                records = build_product_identity_records(
                    document,
                    now=moment,
                    include_history=True,
                )
                for name, rows in records.items():
                    batch_totals[name] += len(rows)
        for name, value in batch_totals.items():
            totals[name] += value

        scanned += len(batch)
        last_id = batch[-1]["_id"]
        query["_id"] = {"$gt": last_id}
        if args.apply:
            now = datetime.now(timezone.utc)
            migrations.update_one(
                {"_id": MIGRATION_ID},
                {
                    "$set": {
                        "version": 1,
                        "last_id": last_id,
                        "status": "running",
                        "processed": int((checkpoint or {}).get("processed") or 0) + scanned,
                        "updated_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        emit("batch", scanned=scanned, last_id=last_id, projected=totals)

    complete = not args.limit or scanned < args.limit or legacy.find_one(query, {"_id": 1}) is None
    if args.apply and complete:
        now = datetime.now(timezone.utc)
        migrations.update_one(
            {"_id": MIGRATION_ID},
            {
                "$set": {
                    "version": 1,
                    "last_id": last_id,
                    "status": "complete",
                    "completed_at": now,
                    "updated_at": now,
                    "processed": int((checkpoint or {}).get("processed") or 0) + scanned,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
    emit(
        "finish",
        scanned=scanned,
        checkpoint=last_id,
        complete=complete,
        projected_or_written=totals,
        after=collection_counts(db) if args.apply else None,
    )
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
