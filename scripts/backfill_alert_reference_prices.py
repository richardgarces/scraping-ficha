#!/usr/bin/env python3
"""Completa referencia, ahorro y descuento semánticos en alertas históricas."""

from __future__ import annotations

import argparse
from collections import Counter

from pymongo import UpdateOne

from retail.mongo import ProductRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day", help="Limitar a YYYY-MM-DD; por defecto procesa todo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = ProductRepository()
    query = {"day": args.day} if args.day else {}
    scanned = changed = skipped = 0
    by_rule: Counter[str] = Counter()
    operations: list[UpdateOne] = []
    try:
        alerts = list(repo.alerts.find(query))
        pairs = {
            (str(item.get("store") or ""), str((item.get("extra") or {}).get("product_id") or ""))
            for item in alerts
            if item.get("store") and (item.get("extra") or {}).get("product_id")
        }
        product_normals: dict[tuple[str, str], int] = {}
        pair_list = list(pairs)
        for start in range(0, len(pair_list), 300):
            chunk = pair_list[start : start + 300]
            for product in repo.collection.find(
                {"$or": [{"store": store, "product_id": product_id} for store, product_id in chunk]},
                {"store": 1, "product_id": 1, "price_normal": 1},
            ):
                normal = int(product.get("price_normal") or 0)
                if normal > 0:
                    product_normals[(str(product.get("store") or ""), str(product.get("product_id") or ""))] = normal

        for item in alerts:
            scanned += 1
            rule = str(item.get("rule") or "")
            extra = item.get("extra") or {}
            current = int(item.get("price") or 0)
            analysis_reference = None
            price_normal = item.get("price_normal")
            historical_rule = "below_median" in rule or (
                "watch_target" in rule and extra.get("drop_percent") is not None and extra.get("median")
            )
            if historical_rule:
                key = (str(item.get("store") or ""), str(extra.get("product_id") or ""))
                price_normal = int(price_normal or product_normals.get(key) or 0) or None
                reference = price_normal if price_normal and price_normal > current else None
                analysis_reference = int(extra.get("median") or 0) or None
            elif "watch_target" in rule and extra.get("target_price"):
                reference = int(extra["target_price"])
            else:
                reference, comparison_current = repo._deal_reference(item)
                current = int(comparison_current or 0)
            saving = max(reference - current, 0) if reference and reference > 0 and current > 0 else 0
            discount = round(100 * saving / reference, 1) if reference and saving else 0.0
            desired = {
                "reference_price": reference,
                "analysis_reference_price": analysis_reference,
                "price_normal": price_normal,
                "saving": saving,
                "discount": discount,
            }
            if not reference or reference <= 0 or not current or current <= 0:
                skipped += 1
            if all(item.get(key) == value for key, value in desired.items()):
                continue
            changed += 1
            by_rule[str(item.get("rule") or "unknown")] += 1
            operations.append(UpdateOne({"_id": item["_id"]}, {"$set": desired}))
            if len(operations) >= 500:
                if not args.dry_run:
                    repo.alerts.bulk_write(operations, ordered=False)
                operations.clear()
        if operations and not args.dry_run:
            repo.alerts.bulk_write(operations, ordered=False)
        print({
            "dry_run": args.dry_run,
            "day": args.day or "all",
            "scanned": scanned,
            "changed": changed,
            "skipped_without_reference": skipped,
            "by_rule": dict(sorted(by_rule.items())),
        })
    finally:
        repo.close()


if __name__ == "__main__":
    main()
