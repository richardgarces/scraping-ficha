"""Importar un JSON de pronósticos a la colección `forecasts` de Mongo.

Uso:
  MONGODB_URI="mongodb://user:pass@host:27017/scraping" python3 scripts/import_forecasts.py path/to/file.json

Si `MONGODB_URI` no está definida, usa `mongodb://localhost:27017/scraping`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pymongo import MongoClient


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"Expected a JSON array in {path}")
    return data


def redact_uri(uri: str) -> str:
    parts = urlsplit(uri)
    if "@" not in parts.netloc:
        return uri
    return urlunsplit((parts.scheme, f"***@{parts.netloc.rsplit('@', 1)[1]}", parts.path, parts.query, parts.fragment))


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/import_forecasts.py path/to/file.json", file=sys.stderr)
        raise SystemExit(2)
    src = Path(sys.argv[1])
    if not src.exists():
        raise SystemExit(f"File not found: {src}")
    uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
    dbname = os.environ.get("MONGODB_DB", "scraping")
    print(f"Connecting to Mongo: {redact_uri(uri)} DB: {dbname}")
    client = MongoClient(uri)
    db = client[dbname]
    coll = db.get_collection("forecasts")
    rows = load_json(src)
    for r in rows:
        if r.get("generated_at") and not r.get("created_at"):
            r["created_at"] = r.get("generated_at")
    if not rows:
        print("No rows to insert")
        return
    # Optional upsert behavior: if product_id exists, replace; else insert.
    upsert = os.environ.get("IMPORT_UPSERT", "0") in ("1", "true", "True")
    if upsert:
        inserted = 0
        updated = 0
        for r in rows:
            doc = dict(r)
            forecast_key = r.get("forecast_key")
            pid = r.get("product_id")
            doc.pop("_id", None)
            if not forecast_key and not pid:
                # fallback: insert if no product_id
                res = coll.insert_one(doc)
                inserted += 1
            else:
                identity = {"forecast_key": forecast_key} if forecast_key else {"product_id": pid}
                if r.get("horizon") is not None:
                    identity["horizon"] = r["horizon"]
                if r.get("model"):
                    identity["model"] = r["model"]
                res = coll.replace_one(identity, doc, upsert=True)
                if res.matched_count:
                    updated += 1
                else:
                    inserted += 1
        print(f"Upsert completed. Inserted: {inserted}, Updated: {updated}")
    else:
        res = coll.insert_many(rows)
        print(f"Inserted {len(res.inserted_ids)} documents into {dbname}.forecasts")


if __name__ == "__main__":
    main()
