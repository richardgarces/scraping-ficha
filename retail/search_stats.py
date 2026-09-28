"""Búsquedas de la web (no el cron) y agregados para /estadisticas."""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.mongo import DEFAULT_DB, DEFAULT_URI
from retail.request_stats import DAY_WINDOW, TZ, WEEK_WINDOW, santiago_now

APP_SEARCHES_COLLECTION = "app_searches"
LEGACY_SEARCHES_COLLECTION = "searches"
TOP_QUERIES = 15
QUERY_LIMIT = 160
_BATCH_MARKERS = ("last_batch_run", "batch_grupo", "batch_tienda", "catalog_id", "watch_query", "basic_scrape")

_client = None
_indexed = False
_down_until = 0.0
_lock = threading.Lock()


def fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("+", " ").replace("-", " ").replace("/", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def is_legacy_user_search(document: dict[str, Any]) -> bool:
    """La colección `searches` también guarda el cron. Esas filas no son ingresos de gente."""
    if document.get("background"):
        return False
    for key in _BATCH_MARKERS:
        if document.get(key):
            return False
    return bool(str(document.get("query") or "").strip())


def record_app_search(
    query: str,
    ip: str = "",
    country: str = "",
    *,
    when: datetime | None = None,
    collection=None,
) -> dict[str, Any] | None:
    """Log liviano al abrir una búsqueda en la web. No lo usa el batch."""
    text = str(query or "").strip()
    if not text:
        return None
    local = santiago_now(when)
    country_code = country.strip().upper()
    if not (len(country_code) == 2 and country_code.isalpha()):
        country_code = ""
    document = {
        "query": text[:QUERY_LIMIT],
        "folded": fold(text)[:QUERY_LIMIT],
        "created_at": local.astimezone(timezone.utc),
        "day": local.date().isoformat(),
        "ip": (ip or "desconocido")[:64],
        "country": country_code,
        "origin": "web",
    }
    target = collection if collection is not None else _live_collection(APP_SEARCHES_COLLECTION)
    if target is not None:
        try:
            target.insert_one(document)
        except Exception:
            _mark_down()
    return document


def load_search_stats(*, now: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(now)
    since = _window_start(local)
    app = _live_collection(APP_SEARCHES_COLLECTION)
    legacy = _live_collection(LEGACY_SEARCHES_COLLECTION)
    if app is None and legacy is None:
        return summarize_search_rows([], now=local, mongo=False)
    web_rows: list[dict[str, Any]] = []
    legacy_rows: list[dict[str, Any]] = []
    try:
        if app is not None:
            web_rows = list(
                app.find(
                    {"created_at": {"$gte": since}},
                    {"_id": 0, "query": 1, "folded": 1, "created_at": 1},
                )
            )
        if legacy is not None:
            legacy_rows = [
                row
                for row in legacy.find(
                    {"created_at": {"$gte": since}},
                    {
                        "_id": 0,
                        "query": 1,
                        "created_at": 1,
                        "background": 1,
                        **{key: 1 for key in _BATCH_MARKERS},
                    },
                )
                if is_legacy_user_search(row)
            ]
    except Exception:
        _mark_down()
        return summarize_search_rows([], now=local, mongo=False)
    return summarize_search_rows(merge_search_rows(legacy_rows, web_rows), now=local, mongo=True)


def merge_search_rows(legacy: list[dict[str, Any]], web: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """El log nuevo cuenta desde que existe; el histórico no se duplica después de ese corte."""
    cutoff = None
    for row in web:
        created = _as_utc(row.get("created_at"))
        if created is None:
            continue
        if cutoff is None or created < cutoff:
            cutoff = created
    kept = [row for row in web if str(row.get("query") or "").strip()]
    for row in legacy:
        if not is_legacy_user_search(row):
            continue
        created = _as_utc(row.get("created_at"))
        if created is None:
            continue
        if cutoff is not None and created >= cutoff:
            continue
        kept.append(row)
    return kept


def summarize_search_rows(
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
    by_day = {key: 0 for key in day_keys}
    queries: dict[str, dict[str, Any]] = {}

    for row in rows:
        if row.get("background") or any(row.get(key) for key in _BATCH_MARKERS):
            continue
        created = _as_utc(row.get("created_at"))
        if created is None:
            continue
        day = created.astimezone(TZ).date().isoformat()
        if day not in day_set:
            continue
        text = str(row.get("query") or "").strip()
        if not text:
            continue
        by_day[day] += 1
        folded = str(row.get("folded") or "").strip() or fold(text)
        bucket = queries.setdefault(folded, {"query": text, "count": 0, "last_at": None})
        bucket["count"] += 1
        if bucket["last_at"] is None or created >= bucket["last_at"]:
            bucket["query"] = text
            bucket["last_at"] = created

    week_keys = [key for key in day_keys if key >= week_start]
    top = sorted(queries.values(), key=lambda item: (-item["count"], item["query"].casefold()))
    return {
        "mongo": mongo,
        "timezone": "America/Santiago",
        "totals": {
            "today": by_day[today_key],
            "days_7": sum(by_day[key] for key in week_keys),
            "days_30": sum(by_day.values()),
        },
        "by_day": [{"day": key, "count": by_day[key]} for key in day_keys],
        "top": [
            {
                "query": item["query"],
                "count": item["count"],
                "last_at": item["last_at"].isoformat(timespec="seconds") if item["last_at"] else None,
            }
            for item in top[:TOP_QUERIES]
        ],
    }


def _window_start(local: datetime) -> datetime:
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=DAY_WINDOW - 1)
    return start.astimezone(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _live_collection(name: str):
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
            return database[name]
        except Exception:
            _down_until = time.monotonic() + 30
            return None


def _ensure_indexes(database) -> None:
    try:
        from pymongo import ASCENDING, DESCENDING

        database[APP_SEARCHES_COLLECTION].create_index(
            [("created_at", DESCENDING)],
            name="app_search_created",
        )
        database[APP_SEARCHES_COLLECTION].create_index(
            [("folded", ASCENDING), ("created_at", DESCENDING)],
            name="app_search_folded",
        )
    except Exception:
        return


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 30
