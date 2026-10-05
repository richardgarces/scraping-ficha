"""Funnel búsqueda → ficha → seguimiento → alerta → clic lnk (sin PII)."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.mongo import DEFAULT_DB, DEFAULT_URI
from retail.request_stats import TZ, santiago_now

FUNNEL_STEPS = (
    "search",
    "product_view",
    "follow",
    "alert_sent",
    "link_click",
)
_STEP_SET = frozenset(FUNNEL_STEPS)
FUNNEL_COLLECTION = "funnel_events"

_client = None
_indexed = False
_down_until = 0.0
_lock = threading.Lock()


def record_funnel_event(
    step: str,
    *,
    source: str = "web",
    when: datetime | None = None,
    collection=None,
) -> dict[str, Any] | None:
    """Registra un paso del funnel. Sin email, IP, query ni user_id."""
    key = str(step or "").strip().lower()
    if key not in _STEP_SET:
        return None
    local = santiago_now(when)
    document = {
        "step": key,
        "source": str(source or "web").strip().lower()[:40] or "web",
        "created_at": local.astimezone(timezone.utc),
        "day": local.date().isoformat(),
    }
    target = collection if collection is not None else _live_collection()
    if target is not None:
        try:
            if isinstance(target, list):
                target.append(document)
            else:
                target.insert_one(document)
        except Exception:
            _mark_down()
    return document


def summarize_funnel_rows(
    rows: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    local = santiago_now(now)
    today = local.date().isoformat()
    week_start = (local.date() - timedelta(days=6)).isoformat()
    counts = {
        step: {"today": 0, "days_7": 0, "days_30": 0}
        for step in FUNNEL_STEPS
    }
    for row in rows:
        step = str(row.get("step") or "").strip().lower()
        if step not in _STEP_SET:
            continue
        day = str(row.get("day") or "")
        if not day:
            created = row.get("created_at")
            if isinstance(created, datetime):
                stamp = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
                day = stamp.astimezone(TZ).date().isoformat()
        if not day:
            continue
        bucket = counts[step]
        bucket["days_30"] += 1
        if day >= week_start:
            bucket["days_7"] += 1
        if day == today:
            bucket["today"] += 1
    return {
        "timezone": "America/Santiago",
        "steps": [
            {
                "step": step,
                "today": counts[step]["today"],
                "days_7": counts[step]["days_7"],
                "days_30": counts[step]["days_30"],
            }
            for step in FUNNEL_STEPS
        ],
    }


def load_funnel_stats(*, now: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(now)
    coll = _live_collection()
    if coll is None:
        return summarize_funnel_rows([], now=local)
    start = (local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=29)).astimezone(
        timezone.utc
    )
    try:
        rows = list(
            coll.find(
                {"created_at": {"$gte": start}},
                {"_id": 0, "step": 1, "day": 1, "created_at": 1},
            )
        )
    except Exception:
        _mark_down()
        return summarize_funnel_rows([], now=local)
    return summarize_funnel_rows(rows, now=local)


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
            return database[FUNNEL_COLLECTION]
        except Exception:
            _down_until = time.monotonic() + 30
            return None


def _ensure_indexes(database) -> None:
    try:
        from pymongo import ASCENDING, DESCENDING

        database[FUNNEL_COLLECTION].create_index(
            [("created_at", DESCENDING)],
            name="funnel_created",
        )
        database[FUNNEL_COLLECTION].create_index(
            [("step", ASCENDING), ("created_at", DESCENDING)],
            name="funnel_step",
        )
    except Exception:
        return


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 30
