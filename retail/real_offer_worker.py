"""Cola durable y worker de clasificación diaria de ofertas reales."""

from __future__ import annotations

import argparse
import os
import re
import socket
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retail.compare import cluster_offer_rows
from retail.reales import (
    MIN_ENTITY_CONFIDENCE,
    all_payment_price,
    card_price,
    comparable_selling_price,
    is_agotado,
    is_payment_restricted,
    pick_real_offer,
)

CHILE = ZoneInfo("America/Santiago")
CRITERION_VERSION = "real-offer-v2"
MAX_ATTEMPTS = 4
LEASE_SECONDS = 300
BATCH_SIZE = 10


def chile_day(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(CHILE).date().isoformat()


def chile_day_bounds(day: str | None = None) -> tuple[datetime, datetime]:
    local_day = datetime.fromisoformat(day or chile_day()).date()
    start = datetime.combine(local_day, datetime.min.time(), tzinfo=CHILE)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def valid_discount(item: dict[str, Any]) -> bool:
    try:
        price = int(item.get("price") or 0)
        normal = int(item.get("price_normal") or 0)
    except (TypeError, ValueError):
        return False
    return price > 0 and normal > price


def price_signature(item: dict[str, Any]) -> str:
    return f"{int(item.get('price') or 0)}:{int(item.get('price_normal') or 0)}"


def analysis_projection() -> dict[str, Any]:
    fields = (
        "store", "product_id", "name", "brand", "url", "seller", "price",
        "price_normal", "price_internet", "price_all_payment", "price_card",
        "payment_card_name", "installment_count", "installment_total",
        "financial_cae", "payment_conditions", "condition",
        "condition_confidence", "shipping_cost", "shipping_free_threshold",
        "shipping_region", "pickup_available", "stock", "stock_verified",
        "low_stock", "only_extreme_sizes", "variants", "entity_id",
        "entity_confidence", "entity_override", "entity_match_method",
        "discount_percent", "compare_code", "catalog_category", "category",
        "availability", "status", "stock_status", "updated_at", "image_url",
    )
    projection = {field: 1 for field in fields}
    projection["price_history"] = {"$slice": ["$price_history", -40]}
    return projection


def _key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("store") or ""), str(item.get("product_id") or "")


def _marker_analysis(card: dict[str, Any]) -> dict[str, Any]:
    excluded = {"name", "brand", "category", "url", "has_thumb", "updated_at"}
    return {key: value for key, value in card.items() if key not in excluded}


def classify_claimed(repo: Any, jobs: list[dict[str, Any]]) -> dict[str, int]:
    """Clasifica un lote agrupando una vez sus marcas/nombres relevantes."""
    if not jobs:
        return {"processed": 0, "real": 0, "not_real": 0, "errors": 0}
    wanted = {job["product_id"]: job for job in jobs}
    candidates = list(repo.collection.aggregate([
        {"$match": {"_id": {"$in": list(wanted)}}},
        {"$project": analysis_projection()},
    ]))
    selectors: list[dict[str, Any]] = []
    brands = {
        str(row.get("brand") or "").strip()
        for row in candidates
        if str(row.get("brand") or "").strip()
    }
    names = {
        str(row.get("name") or "").strip()
        for row in candidates
        if str(row.get("name") or "").strip()
    }
    overrides = {
        str(row.get("entity_override") or "").strip()
        for row in candidates
        if str(row.get("entity_override") or "").strip()
    }
    if brands:
        selectors.extend(
            {"brand": {"$regex": f"^{re.escape(brand)}$", "$options": "i"}}
            for brand in brands
        )
    if names:
        selectors.extend(
            {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
            for name in names
        )
    if overrides:
        selectors.append({"entity_override": {"$in": list(overrides)}})
    scope = {"$or": selectors} if selectors else {"_id": {"$in": list(wanted)}}
    docs = list(repo.collection.aggregate([
        {
            "$match": {
                "$and": [
                    {"price": {"$gt": 0}, "name": {"$nin": [None, ""]}},
                    scope,
                ]
            }
        },
        {"$project": analysis_projection()},
    ], allowDiskUse=True))
    results: dict[Any, tuple[bool, dict[str, Any] | None, str]] = {
        product_id: (False, None, "sin_par_comparable")
        for product_id in wanted
    }
    for group in cluster_offer_rows(docs):
        members = {row.get("_id") for row in group.get("offers") or []}
        relevant = members.intersection(wanted)
        if not relevant:
            continue
        card = None
        if (
            int(group.get("store_count") or 0) >= 2
            and float(group.get("entity_confidence") or 0) >= MIN_ENTITY_CONFIDENCE
        ):
            card = pick_real_offer(
                group.get("offers") or [],
                comparacion=True,
                historial=True,
                iguales=False,
            )
            if card and is_agotado(card):
                card = None
        winner = _key(card or {})
        for product_id in relevant:
            candidate = next(
                (row for row in group.get("offers") or [] if row.get("_id") == product_id),
                None,
            )
            is_real = bool(card and _key(candidate or {}) == winner)
            reason = (
                str(card.get("reason") or "criterio_real_cumplido")
                if is_real
                else "otro_aviso_del_grupo_es_mejor"
                if card
                else "criterio_real_no_cumplido"
            )
            results[product_id] = (is_real, card if is_real else None, reason)

    metrics = {"processed": 0, "real": 0, "not_real": 0, "errors": 0}
    now = datetime.now(timezone.utc)
    for job in jobs:
        try:
            product = next((row for row in docs if row.get("_id") == job["product_id"]), None)
            is_real, card, reason = results[job["product_id"]]
            evaluated_price = int(
                comparable_selling_price(product or {})
                or (product or {}).get("price")
                or job.get("price")
                or 0
            )
            marker = {
                "product_id": job["product_id"],
                "day": job["day"],
                "is_real": is_real,
                "evaluated_price": evaluated_price,
                "evaluated_price_normal": int((product or {}).get("price_normal") or job.get("price_normal") or 0),
                "evaluated_price_all_payment": all_payment_price(product or {}),
                "evaluated_price_card": card_price(product or {}),
                "payment_restricted": is_payment_restricted(product or {}),
                "price_signature": job["price_signature"],
                "reason": reason if not is_payment_restricted(product or {}) or is_real else "payment_restricted",
                "criterion_version": CRITERION_VERSION,
                "evaluated_at": now,
                "job_id": job["_id"],
                "analysis": _marker_analysis(card) if card else {},
            }
            repo.daily_real_offers.update_one(
                {"product_id": job["product_id"], "day": job["day"]},
                {"$set": marker, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            repo.real_offer_jobs.update_one(
                {"_id": job["_id"], "status": "processing"},
                {"$set": {"status": "done", "finished_at": now}, "$unset": {"lease_until": ""}},
            )
            metrics["processed"] += 1
            metrics["real" if is_real else "not_real"] += 1
        except Exception as exc:
            _retry_job(repo, job, exc)
            metrics["errors"] += 1
    repo.record_real_offer_stats(metrics)
    return metrics


def _retry_job(repo: Any, job: dict[str, Any], exc: Exception) -> None:
    now = datetime.now(timezone.utc)
    attempts = int(job.get("attempts") or 1)
    failed = attempts >= MAX_ATTEMPTS
    update: dict[str, Any] = {
        "status": "failed" if failed else "retry",
        "last_error": f"{type(exc).__name__}: {exc}"[:500],
        "updated_at": now,
    }
    if not failed:
        update["available_at"] = now + timedelta(seconds=min(900, 30 * (2 ** (attempts - 1))))
    repo.real_offer_jobs.update_one(
        {"_id": job["_id"]},
        {"$set": update, "$unset": {"lease_until": ""}},
    )
    repo.record_real_offer_stats({"errors": 1, "retries": 0 if failed else 1})


def claim_jobs(repo: Any, limit: int = BATCH_SIZE) -> list[dict[str, Any]]:
    from pymongo import ReturnDocument

    now = datetime.now(timezone.utc)
    claimed = []
    for _ in range(max(1, limit)):
        job = repo.real_offer_jobs.find_one_and_update(
            {
                "$or": [
                    {"status": {"$in": ["queued", "retry"]}, "available_at": {"$lte": now}},
                    {"status": "processing", "lease_until": {"$lte": now}},
                ],
                "attempts": {"$lt": MAX_ATTEMPTS},
            },
            {
                "$set": {
                    "status": "processing",
                    "claimed_at": now,
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                    "worker": socket.gethostname(),
                },
                "$inc": {"attempts": 1},
            },
            sort=[("available_at", 1), ("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not job:
            break
        claimed.append(job)
    return claimed


def run_once(repo: Any, limit: int = BATCH_SIZE) -> dict[str, int]:
    jobs = claim_jobs(repo, limit)
    if not jobs:
        return {"processed": 0, "real": 0, "not_real": 0, "errors": 0}
    try:
        return classify_claimed(repo, jobs)
    except Exception as exc:
        for job in jobs:
            _retry_job(repo, job, exc)
        return {"processed": 0, "real": 0, "not_real": 0, "errors": len(jobs)}


def worker_loop(repo: Any, poll_seconds: float = 2.0) -> None:
    while True:
        repo.touch_real_offer_worker()
        metrics = run_once(repo)
        if metrics["processed"] or metrics["errors"]:
            print(f"real-offer-worker {metrics}", flush=True)
        if not metrics["processed"] and not metrics["errors"]:
            time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--backfill-today", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--limit", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    from retail.mongo import ProductRepository

    repo = ProductRepository()
    try:
        if args.healthcheck:
            status = repo.real_offer_worker_status()
            if not status.get("healthy"):
                raise SystemExit(1)
            return
        if args.backfill_today:
            print(f"real-offer-backfill {repo.enqueue_today_real_offer_candidates()}", flush=True)
        if args.once:
            print(f"real-offer-worker {run_once(repo, args.limit)}", flush=True)
            return
        worker_loop(repo)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
