#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from retail import thumbs
from retail.mongo import ProductRepository
from retail.models import normalize_image_url


def main() -> None:
    limit = max(1, min(5000, int(os.environ.get("THUMB_BACKFILL_LIMIT", "1000"))))
    repo = ProductRepository(
        uri=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        database=os.environ.get("MONGODB_DB", "scraping"),
    )
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        rows = list(
            repo.collection.find(
                {
                    "image_url": {"$nin": [None, ""]},
                    "thumbnail.data": {"$exists": False},
                    "$or": [
                        {"thumbnail_attempted_at": {"$exists": False}},
                        {"thumbnail_attempted_at": {"$lt": cutoff}},
                    ],
                },
                {"_id": 0, "store": 1, "product_id": 1, "image_url": 1, "image_urls": 1},
            ).sort("updated_at", -1).limit(limit)
        )
        targets = []
        for item in rows:
            urls: list[str] = []
            for value in [item.get("image_url"), *(item.get("image_urls") or [])]:
                text = normalize_image_url(item.get("store"), str(value or "").strip()) or ""
                if text and text not in urls:
                    urls.append(text)
            key = (str(item.get("store") or ""), str(item.get("product_id") or ""))
            if all(key) and urls:
                targets.append((key, urls))
        built = thumbs.build_many_candidates(targets)
        repo.mark_thumbnail_attempted([key for key, _urls in targets])
        saved = repo.save_thumbnails(built) if built else 0
        print(json.dumps({
            "attempted": len(targets), "built": len(built), "saved": saved,
            "failed": len(targets) - len(built),
        }, ensure_ascii=False))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
