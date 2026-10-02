"""Productos consultados y actualizados por el scraping (día Santiago)."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.mongo import DEFAULT_DB, DEFAULT_URI
from retail.request_stats import DAY_WINDOW, WEEK_WINDOW, santiago_now

SCRAPE_STATS_COLLECTION = "scrape_stats"

_client = None
_indexed = False
_down_until = 0.0
_lock = threading.Lock()


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_write(
    previous: tuple[Any, ...] | None,
    price: Any,
    price_normal: Any = None,
) -> dict[str, bool]:
    """Qué cambió al guardar un producto ya consultado.

    El primer avistamiento cuenta como consultado, no como actualización de
    precio ni de descuento: no hay valor anterior con el que comparar.
    """
    flags = {"scraped": True, "price_updated": False, "discount_updated": False}
    if previous is None:
        return flags
    old_price = _as_int(previous[0] if previous else None)
    old_normal = _as_int(previous[2] if previous and len(previous) > 2 else None)
    new_price = _as_int(price)
    new_normal = _as_int(price_normal)
    if old_price is not None and new_price is not None and old_price != new_price:
        flags["price_updated"] = True
    # Precio lista distinto (apareció, desapareció o cambió el descuento publicado).
    if old_normal != new_normal:
        flags["discount_updated"] = True
    return flags


def record_product_writes(
    previous: dict[tuple[str, str], tuple[Any, ...]],
    products: list[Any],
    *,
    when: datetime | None = None,
    collection=None,
) -> dict[str, int]:
    """Suma consultados / precio / descuento del lote de upsert."""
    scraped = 0
    price_updated = 0
    discount_updated = 0
    for product in products:
        store = getattr(product, "store", None) or ""
        product_id = getattr(product, "product_id", None) or ""
        if not store or not product_id:
            continue
        flags = classify_write(
            previous.get((store, product_id)),
            getattr(product, "price", None),
            getattr(product, "price_normal", None),
        )
        scraped += 1
        if flags["price_updated"]:
            price_updated += 1
        if flags["discount_updated"]:
            discount_updated += 1
    if scraped or price_updated or discount_updated:
        apply_scrape_hit(
            scraped=scraped,
            price_updated=price_updated,
            discount_updated=discount_updated,
            when=when,
            collection=collection,
        )
    return {
        "scraped": scraped,
        "price_updated": price_updated,
        "discount_updated": discount_updated,
    }


def apply_scrape_hit(
    *,
    scraped: int = 0,
    price_updated: int = 0,
    discount_updated: int = 0,
    when: datetime | None = None,
    collection=None,
) -> dict[str, Any] | None:
    scraped = max(0, int(scraped or 0))
    price_updated = max(0, int(price_updated or 0))
    discount_updated = max(0, int(discount_updated or 0))
    if not (scraped or price_updated or discount_updated):
        return None
    local = santiago_now(when)
    day = local.date().isoformat()
    document = {
        "day": day,
        "scraped": scraped,
        "price_updated": price_updated,
        "discount_updated": discount_updated,
    }
    target = collection if collection is not None else _live_collection()
    if target is not None:
        try:
            target.update_one(
                {"day": day},
                {
                    "$inc": {
                        "scraped": scraped,
                        "price_updated": price_updated,
                        "discount_updated": discount_updated,
                    },
                    "$set": {"updated_at": local.astimezone(timezone.utc)},
                },
                upsert=True,
            )
        except Exception:
            _mark_down()
    return document


def load_scrape_stats(*, now: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(now)
    since = (local.date() - timedelta(days=DAY_WINDOW - 1)).isoformat()
    coll = _live_collection()
    if coll is None:
        return summarize_scrape_rows([], now=local, mongo=False)
    try:
        rows = list(
            coll.find(
                {"day": {"$gte": since}},
                {"_id": 0, "day": 1, "scraped": 1, "price_updated": 1, "discount_updated": 1},
            )
        )
    except Exception:
        _mark_down()
        return summarize_scrape_rows([], now=local, mongo=False)
    return summarize_scrape_rows(rows, now=local, mongo=True)


def summarize_scrape_rows(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    mongo: bool = True,
) -> dict[str, Any]:
    local = santiago_now(now)
    today = local.date()
    days = [today - timedelta(days=offset) for offset in range(DAY_WINDOW - 1, -1, -1)]
    day_keys = [day.isoformat() for day in days]
    day_set = set(day_keys)
    week_start = (today - timedelta(days=WEEK_WINDOW - 1)).isoformat()
    today_key = today.isoformat()

    by_day = {
        key: {"day": key, "scraped": 0, "price_updated": 0, "discount_updated": 0}
        for key in day_keys
    }
    for row in rows:
        day = str(row.get("day") or "")
        if day not in day_set:
            continue
        bucket = by_day[day]
        bucket["scraped"] += int(row.get("scraped") or 0)
        bucket["price_updated"] += int(row.get("price_updated") or 0)
        bucket["discount_updated"] += int(row.get("discount_updated") or 0)

    week_keys = [key for key in day_keys if key >= week_start]

    def _sum(field: str, keys: list[str]) -> int:
        return sum(by_day[key][field] for key in keys)

    return {
        "mongo": mongo,
        "timezone": "America/Santiago",
        "totals": {
            "scraped": {
                "today": by_day[today_key]["scraped"],
                "days_7": _sum("scraped", week_keys),
                "days_30": _sum("scraped", day_keys),
            },
            "price_updated": {
                "today": by_day[today_key]["price_updated"],
                "days_7": _sum("price_updated", week_keys),
                "days_30": _sum("price_updated", day_keys),
            },
            "discount_updated": {
                "today": by_day[today_key]["discount_updated"],
                "days_7": _sum("discount_updated", week_keys),
                "days_30": _sum("discount_updated", day_keys),
            },
        },
        "by_day": [by_day[key] for key in day_keys],
    }


def _live_collection():
    global _client, _indexed, _down_until
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    with _lock:
        if time.monotonic() < _down_until:
            return None
        try:
            if _client is None:
                from pymongo import MongoClient

                _client = MongoClient(
                    DEFAULT_URI,
                    serverSelectionTimeoutMS=800,
                    connectTimeoutMS=800,
                )
            database = _client[DEFAULT_DB]
            if not _indexed:
                _ensure_indexes(database)
                _indexed = True
            return database[SCRAPE_STATS_COLLECTION]
        except Exception:
            _down_until = time.monotonic() + 30
            return None


def _ensure_indexes(database) -> None:
    try:
        from pymongo import ASCENDING

        database[SCRAPE_STATS_COLLECTION].create_index(
            [("day", ASCENDING)],
            name="scrape_stats_day",
            unique=True,
        )
    except Exception:
        return


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 30
