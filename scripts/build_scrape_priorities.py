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

from retail.batch.adaptive import PRIORITY_SETTING_KEY, aggregate_catalog_priorities, assess_product
from retail.mongo import ProductRepository
from retail.predictive_alerts import predictive_validation_status


def main() -> None:
    from pymongo import ReplaceOne

    repo = ProductRepository(
        uri=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        database=os.environ.get("MONGODB_DB", "scraping"),
    )
    now = datetime.now(timezone.utc)
    try:
        if not repo.ping():
            raise SystemExit("MongoDB no está disponible.")
        validation = predictive_validation_status(repo)
        forecasts: dict[str, dict] = {}
        cursor = repo.forecasts.find(
            {"model": "timesfm", "generated_at": {"$gte": now - timedelta(hours=48)}},
            {"_id": 0},
        ).sort("generated_at", -1)
        for item in cursor:
            key = str(item.get("forecast_key") or "")
            if key and key not in forecasts:
                forecasts[key] = item

        assessments = []
        products = repo.collection.find(
            {
                "catalog_id": {"$nin": [None, ""]},
                "store": {"$nin": [None, ""]},
                "product_id": {"$nin": [None, ""]},
                "price_history.1": {"$exists": True},
            },
            {
                "_id": 0, "store": 1, "product_id": 1, "name": 1, "price": 1,
                "catalog_id": 1, "catalog_category": 1, "category": 1,
                "price_history": {"$slice": -400},
            },
        ).batch_size(500)
        for product in products:
            key = f"{str(product.get('store') or '').lower()}:{str(product.get('product_id') or '')}"
            assessments.append(
                assess_product(
                    product,
                    forecasts.get(key),
                    timesfm_validated=validation["enabled"],
                    now=now,
                )
            )

        priorities = aggregate_catalog_priorities(assessments, now=now)
        priority_ops = [
            ReplaceOne({"catalog_id": item["catalog_id"]}, item, upsert=True)
            for item in priorities
        ]
        if priority_ops:
            repo.scrape_priorities.bulk_write(priority_ops, ordered=False)

        pattern_ops = []
        expiry = now + timedelta(days=3)
        for item in assessments:
            if not item.get("patterns"):
                continue
            document = {
                "product_key": item["product_key"], "store": item.get("store"),
                "product_id": item.get("product_id"), "name": item.get("name"),
                "patterns": item["patterns"], "profile": item["profile"],
                "updated_at": now, "expires_at": expiry,
            }
            pattern_ops.append(ReplaceOne({"product_key": item["product_key"]}, document, upsert=True))
        if pattern_ops:
            repo.price_patterns.bulk_write(pattern_ops, ordered=False)

        status = {
            "enabled": bool(priorities),
            "timesfm_enabled": validation["enabled"],
            "reason": (
                "Plan adaptativo calculado con TimesFM validado."
                if validation["enabled"]
                else "Plan adaptativo calculado con el historial real; TimesFM aún no interviene."
            ),
            "products_analyzed": len(assessments), "catalog_queries": len(priorities),
            "patterns_detected": sum(len(item.get("patterns") or []) for item in assessments),
            "high_priority_queries": sum(item.get("tier") == "high" for item in priorities),
            "deferred_queries": sum(item.get("tier") in {"low", "dormant"} for item in priorities),
            "generated_at": now.isoformat(),
        }
        repo.save_app_setting(PRIORITY_SETTING_KEY, status)
        try:
            from retail.scrape_priority_boost import boost_watched_and_offer_priorities

            boost = boost_watched_and_offer_priorities(repo, now=now)
            status["watch_offer_boost"] = boost
            status["following_boosted"] = boost.get("following_boosted", 0)
            status["following_products"] = boost.get("following_products", 0)
            print(json.dumps({"watch_offer_boost": boost}, ensure_ascii=False, default=str))
        except Exception as exc:
            status["watch_offer_boost_error"] = str(exc)
        print(json.dumps(status, ensure_ascii=False, default=str))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
