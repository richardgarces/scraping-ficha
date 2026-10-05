"""Benchmark seguro de find_by_query (sin imprimir secretos/PII)."""
from __future__ import annotations

import os
import re
import time

from pymongo import MongoClient


def stages(plan, out=None):
    out = out or []
    if not isinstance(plan, dict):
        return out
    if "stage" in plan:
        out.append(plan["stage"])
    for key in ("inputStage", "queryPlan", "winningPlan"):
        if isinstance(plan.get(key), dict):
            stages(plan[key], out)
    for item in plan.get("inputStages") or []:
        stages(item, out)
    return out


def main() -> None:
    uri = os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URI")
    dbn = os.environ.get("MONGODB_DB") or os.environ.get("MONGO_DB") or "scraping"
    if not uri:
        raise SystemExit("missing mongo uri")
    db = MongoClient(uri, serverSelectionTimeoutMS=4000)[dbn]
    from retail.mongo import ProductRepository

    repo = ProductRepository(uri, database=dbn)
    try:
        for q in ["leche", "smart tv 55"]:
            escaped = re.escape(q)
            filt = {
                "$or": [
                    {"last_search_query": {"$regex": escaped, "$options": "i"}},
                    {"name": {"$regex": escaped, "$options": "i"}},
                    {"brand": {"$regex": escaped, "$options": "i"}},
                    {"sku_id": {"$regex": escaped, "$options": "i"}},
                    {"product_id": {"$regex": escaped, "$options": "i"}},
                ]
            }
            t0 = time.perf_counter()
            rows = list(db.products.find(filt).sort("updated_at", -1).limit(200))
            print("LEGACY_REGEX", q, "ms", round((time.perf_counter() - t0) * 1000, 1), "n", len(rows))

            t0 = time.perf_counter()
            rows = repo.find_by_query(q, limit=200)
            print("OPTIMIZED", q, "ms", round((time.perf_counter() - t0) * 1000, 1), "n", len(rows))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
