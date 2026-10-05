"""Sube la prioridad de scrape de Siguiendo y candidatos de oferta del día.

Los productos con seguimiento activo (`watches` o `price_alerts`) de cualquier
usuario *approved* adelantan ``next_due_at`` y score en ``scrape_priorities``,
por encima del catálogo genérico. El plan adaptativo del batch (`plan_catalog_products`)
los toma primero sin duplicar scrapes: solo reordena / adelanta lo ya planificado.
Respeta presupuesto de corrida y «Continuar» (no fuerza un scrape aparte).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


WATCH_SCORE = 95
OFFER_CANDIDATE_SCORE = 85
WATCH_INTERVAL_HOURS = 6
OFFER_INTERVAL_HOURS = 8

FOLLOWING_BOOST_SETTING_PREFIX = "scrape_following_boost"


def following_boost_setting_key(day: datetime | None = None) -> str:
    stamp = day or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return f"{FOLLOWING_BOOST_SETTING_PREFIX}:{stamp.date().isoformat()}"


def _approved_user_ids(repo: Any) -> set[str] | None:
    """IDs de usuarios approved. ``None`` = no se pudo filtrar (aceptar todos)."""
    users = getattr(repo, "users", None)
    if users is None:
        return None
    try:
        found = users.find({"status": "approved"}, {"_id": 1})
    except Exception:
        return None
    ids: set[str] = set()
    for item in found:
        uid = str(item.get("_id") or item.get("id") or "").strip()
        if uid:
            ids.add(uid)
    return ids


def _user_allowed(user_id: Any, approved: set[str] | None) -> bool:
    uid = str(user_id or "").strip()
    if not uid:
        # Suscripción sin dueño: no cuenta como seguimiento de usuario approved.
        return False
    if approved is None:
        return True
    return uid in approved


def _collect_following_product_keys(repo: Any, approved: set[str] | None) -> tuple[list[tuple[str, str]], dict[str, int], int, int]:
    """Productos (store, id) y catalog_ids ya conocidos desde watches/alerts."""
    product_keys: list[tuple[str, str]] = []
    seen_products: set[tuple[str, str]] = set()
    boosted_catalogs: dict[str, int] = {}
    watches = 0
    price_alerts = 0

    watches_col = getattr(repo, "watches", None)
    if watches_col is not None:
        for watch in watches_col.find(
            {"active": {"$ne": False}},
            {"store": 1, "product_id": 1, "catalog_id": 1, "user_id": 1},
        ):
            if not _user_allowed(watch.get("user_id"), approved):
                continue
            watches += 1
            store = str(watch.get("store") or "").strip().lower()
            product_id = str(watch.get("product_id") or "").strip()
            if store and product_id:
                key = (store, product_id)
                if key not in seen_products:
                    seen_products.add(key)
                    product_keys.append(key)
            catalog_id = str(watch.get("catalog_id") or "").strip()
            if catalog_id:
                boosted_catalogs[catalog_id] = max(
                    boosted_catalogs.get(catalog_id, 0), WATCH_SCORE
                )

    alerts_col = getattr(repo, "price_alerts", None)
    if alerts_col is not None:
        for alert in alerts_col.find(
            {"active": True},
            {"store": 1, "product_id": 1, "user_id": 1},
        ):
            if not _user_allowed(alert.get("user_id"), approved):
                continue
            price_alerts += 1
            store = str(alert.get("store") or "").strip().lower()
            product_id = str(alert.get("product_id") or "").strip()
            if not store or not product_id:
                continue
            key = (store, product_id)
            if key not in seen_products:
                seen_products.add(key)
                product_keys.append(key)

    return product_keys, boosted_catalogs, watches, price_alerts


def _resolve_catalogs_for_products(
    repo: Any,
    product_keys: list[tuple[str, str]],
    boosted_catalogs: dict[str, int],
) -> int:
    """Completa catalog_id desde productos Mongo. Devuelve cuántos productos tenían catálogo."""
    resolved = 0
    if not product_keys or getattr(repo, "collection", None) is None:
        return resolved
    for start in range(0, len(product_keys), 200):
        chunk = product_keys[start : start + 200]
        for doc in repo.collection.find(
            {"$or": [{"store": s, "product_id": p} for s, p in chunk]},
            {"catalog_id": 1, "store": 1, "product_id": 1},
        ):
            catalog_id = str(doc.get("catalog_id") or "").strip()
            if not catalog_id:
                continue
            resolved += 1
            boosted_catalogs[catalog_id] = max(
                boosted_catalogs.get(catalog_id, 0), WATCH_SCORE
            )
    return resolved


def boost_watched_and_offer_priorities(
    repo: Any,
    *,
    now: datetime | None = None,
    persist_metrics: bool = True,
) -> dict[str, int | str]:
    """Marca ``scrape_priorities`` para Siguiendo + descuentos del día.

    No reescribe el plan adaptativo completo: solo sube score y adelanta
    ``next_due_at`` de catálogos ligados a productos seguidos o en oferta.
    Idempotente: el mismo ``catalog_id`` se upserta una vez por corrida.
    """
    stamp = now or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)

    approved = _approved_user_ids(repo)
    product_keys, boosted_catalogs, watches, price_alerts = _collect_following_product_keys(
        repo, approved
    )
    following_products = len(product_keys)
    resolved = _resolve_catalogs_for_products(repo, product_keys, boosted_catalogs)
    following_catalogs_before_offers = {
        cid for cid, score in boosted_catalogs.items() if score >= WATCH_SCORE
    }

    offers = 0
    try:
        from retail.real_offer_worker import chile_day_bounds

        day_start, day_end = chile_day_bounds()
    except Exception:
        day_start, day_end = stamp - timedelta(hours=18), stamp

    collection = getattr(repo, "collection", None)
    if collection is not None:
        for doc in collection.find(
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

    following_boosted = 0
    offer_boosted = 0
    priorities = getattr(repo, "scrape_priorities", None)
    if priorities is not None:
        for catalog_id, score in boosted_catalogs.items():
            is_following = catalog_id in following_catalogs_before_offers or score >= WATCH_SCORE
            interval = WATCH_INTERVAL_HOURS if is_following else OFFER_INTERVAL_HOURS
            reason = (
                "Prioridad alta: producto seguido (Siguiendo) por usuario approved."
                if is_following
                else "Prioridad alta: candidato de oferta del día."
            )
            boost_reason = "siguiendo" if is_following else "oferta_dia"
            priorities.update_one(
                {"catalog_id": catalog_id},
                {
                    "$set": {
                        "catalog_id": catalog_id,
                        "score": score,
                        "tier": "high",
                        "recommended_interval_hours": interval,
                        "next_due_at": stamp,
                        "updated_at": stamp,
                        "boost_reason": boost_reason,
                        "reasons": [reason],
                    },
                },
                upsert=True,
            )
            if is_following:
                following_boosted += 1
            else:
                offer_boosted += 1

    metrics: dict[str, int | str] = {
        "watches": watches,
        "price_alerts": price_alerts,
        "following_products": following_products,
        "following_products_with_catalog": resolved,
        "following_boosted": following_boosted,
        "offer_candidates": offers,
        "offer_boosted": offer_boosted,
        "catalogs": len(boosted_catalogs),
        "approved_users": len(approved) if approved is not None else -1,
        "day": stamp.date().isoformat(),
    }

    if persist_metrics and hasattr(repo, "save_app_setting"):
        try:
            repo.save_app_setting(
                following_boost_setting_key(stamp),
                {
                    **metrics,
                    "generated_at": stamp.isoformat(),
                    "note": (
                        "Catálogos de productos seguidos (watches + price_alerts de "
                        "usuarios approved) adelantados en scrape_priorities."
                    ),
                },
            )
        except Exception as exc:
            metrics["metrics_persist_error"] = str(exc)

    print(
        f"Siguiendo boost: {following_boosted} catálogos "
        f"({following_products} productos únicos; watches={watches}, "
        f"price_alerts={price_alerts})"
    )
    return metrics
