"""Sube la prioridad de scrape de Siguiendo y candidatos de oferta del día."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


WATCH_SCORE = 95
OFFER_CANDIDATE_SCORE = 85
WATCH_INTERVAL_HOURS = 6
OFFER_INTERVAL_HOURS = 8


def boost_watched_and_offer_priorities(
    repo: Any,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Marca ``scrape_priorities`` para watches + descuentos del día.

    No reescribe el plan adaptativo completo: solo sube score y adelanta
    ``next_due_at`` de catálogos ligados a productos seguidos o en oferta.
    """
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    boosted_catalogs: dict[str, int] = {}
    watches = 0
    offers = 0

    watch_keys: list[tuple[str, str]] = []
    for watch in repo.watches.find(
        {"active": {"$ne": False}},
        {"store": 1, "product_id": 1, "catalog_id": 1},
    ):
        store = str(watch.get("store") or "").strip()
        product_id = str(watch.get("product_id") or "").strip()
        if store and product_id:
            watch_keys.append((store, product_id))
            watches += 1
        catalog_id = str(watch.get("catalog_id") or "").strip()
        if catalog_id:
            boosted_catalogs[catalog_id] = max(boosted_catalogs.get(catalog_id, 0), WATCH_SCORE)

    if watch_keys:
        for start in range(0, len(watch_keys), 200):
            chunk = watch_keys[start : start + 200]
            for doc in repo.collection.find(
                {"$or": [{"store": s, "product_id": p} for s, p in chunk]},
                {"catalog_id": 1},
            ):
                catalog_id = str(doc.get("catalog_id") or "").strip()
                if catalog_id:
                    boosted_catalogs[catalog_id] = max(
                        boosted_catalogs.get(catalog_id, 0), WATCH_SCORE
                    )

    try:
        from retail.real_offer_worker import chile_day_bounds

        day_start, day_end = chile_day_bounds()
    except Exception:
        day_start, day_end = stamp - timedelta(hours=18), stamp

    for doc in repo.collection.find(
        {
            "updated_at": {"$gte": day_start, "$lt": day_end},
            "price": {"$gt": 0},
            "$expr": {"$gt": ["$price_normal", "$price"]},
            "catalog_id": {"$nin": [None, ""]},
        },
        {"catalog_id": 1},
    ).limit(500):
        offers += 1
        catalog_id = str(doc.get("catalog_id") or "").strip()
        if catalog_id:
            boosted_catalogs[catalog_id] = max(
                boosted_catalogs.get(catalog_id, 0), OFFER_CANDIDATE_SCORE
            )

    for catalog_id, score in boosted_catalogs.items():
        interval = WATCH_INTERVAL_HOURS if score >= WATCH_SCORE else OFFER_INTERVAL_HOURS
        repo.scrape_priorities.update_one(
            {"catalog_id": catalog_id},
            {
                "$set": {
                    "catalog_id": catalog_id,
                    "score": score,
                    "tier": "high",
                    "recommended_interval_hours": interval,
                    "next_due_at": stamp,
                    "updated_at": stamp,
                    "boost_reason": "siguiendo_o_oferta_dia",
                    "reasons": ["Prioridad alta: Siguiendo o candidato de oferta del día."],
                },
            },
            upsert=True,
        )

    return {
        "watches": watches,
        "offer_candidates": offers,
        "catalogs": len(boosted_catalogs),
    }
