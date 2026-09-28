"""Clics de la web (menú, fecha, enlaces a tiendas). No son visitas."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from retail.mongo import APP_CLICKS_COLLECTION, DEFAULT_DB, DEFAULT_URI
from retail.request_stats import DAY_WINDOW, TZ, WEEK_WINDOW, santiago_now

# Páginas de administración. Un clic ahí no es uso público (el cron tampoco llama esto).
_ADMIN_PAGES = {"/cron", "/estadisticas", "/usuarios", "/ofertas"}
CLICK_KINDS = (
    ("catalogo", "Catálogo"),
    ("hoy", "Ofertas de hoy"),
    ("reales", "Ofertas reales"),
    ("super", "Super ofertas"),
    ("tiendas", "Tiendas"),
    ("fecha", "La fecha"),
    ("externo", "Enlaces externos"),
)
_KIND_LABELS = dict(CLICK_KINDS)
_KIND_KEYS = frozenset(_KIND_LABELS)

_client = None
_indexed = False
_down_until = 0.0
_lock = threading.Lock()


def parse_click_kind(raw: bytes) -> str:
    text = raw.decode("utf-8", "replace").strip()
    if not text or len(text) > 200:
        return ""
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("kind") or "")
    return str((parse_qs(text).get("kind") or [""])[0])


def click_origin(headers) -> str:
    getter = getattr(headers, "get", None)
    raw = str(getter("referer") or "") if callable(getter) else ""
    return sanitize_origin(raw)


def sanitize_origin(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("/") and not text.startswith("//"):
        path = text
    else:
        path = urlparse(text).path or ""
    path = path.split("?", 1)[0].split("#", 1)[0][:80]
    if not path.startswith("/") or any(ch.isspace() for ch in path):
        return ""
    return path.rstrip("/") or "/"


def is_admin_origin(path: str) -> bool:
    clean = sanitize_origin(path) or str(path or "").rstrip("/") or "/"
    return clean in _ADMIN_PAGES or clean.startswith("/api/admin")


def record_click(
    kind: str,
    ip: str = "",
    country: str = "",
    *,
    origin: str = "",
    when: datetime | None = None,
    collection=None,
) -> dict[str, Any] | None:
    key = str(kind or "").strip().lower()
    if key not in _KIND_KEYS:
        return None
    page = sanitize_origin(origin)
    if page and is_admin_origin(page):
        return None
    local = santiago_now(when)
    country_code = country.strip().upper()
    if not (len(country_code) == 2 and country_code.isalpha()):
        country_code = ""
    document = {
        "kind": key,
        "created_at": local.astimezone(timezone.utc),
        "day": local.date().isoformat(),
        "ip": (ip or "desconocido")[:64],
        "country": country_code,
        "origin": page,
    }
    target = collection if collection is not None else _live_collection()
    if target is not None:
        try:
            target.insert_one(document)
        except Exception:
            _mark_down()
    return document


def load_click_stats(*, now: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(now)
    coll = _live_collection()
    if coll is None:
        return summarize_click_rows([], now=local, mongo=False)
    try:
        rows = list(
            coll.find(
                {"created_at": {"$gte": _window_start(local)}},
                {"_id": 0, "kind": 1, "created_at": 1},
            )
        )
    except Exception:
        _mark_down()
        return summarize_click_rows([], now=local, mongo=False)
    return summarize_click_rows(rows, now=local, mongo=True)


def summarize_click_rows(
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
    counts = {key: {"today": 0, "days_7": 0, "days_30": 0} for key, _label in CLICK_KINDS}

    for row in rows:
        key = str(row.get("kind") or "").strip().lower()
        if key not in _KIND_KEYS:
            continue
        created = _as_utc(row.get("created_at"))
        if created is None:
            continue
        day = created.astimezone(TZ).date().isoformat()
        if day not in day_set:
            continue
        by_day[day] += 1
        bucket = counts[key]
        bucket["days_30"] += 1
        if day >= week_start:
            bucket["days_7"] += 1
        if day == today_key:
            bucket["today"] += 1

    week_keys = [key for key in day_keys if key >= week_start]
    return {
        "mongo": mongo,
        "timezone": "America/Santiago",
        "totals": {
            "today": by_day[today_key],
            "days_7": sum(by_day[key] for key in week_keys),
            "days_30": sum(by_day.values()),
        },
        "by_day": [{"day": key, "count": by_day[key]} for key in day_keys],
        "items": [
            {
                "kind": key,
                "label": label,
                "today": counts[key]["today"],
                "days_7": counts[key]["days_7"],
                "days_30": counts[key]["days_30"],
            }
            for key, label in CLICK_KINDS
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
            return database[APP_CLICKS_COLLECTION]
        except Exception:
            _down_until = time.monotonic() + 30
            return None


def _ensure_indexes(database) -> None:
    try:
        from pymongo import ASCENDING, DESCENDING

        database[APP_CLICKS_COLLECTION].create_index(
            [("created_at", DESCENDING)],
            name="app_click_created",
        )
        database[APP_CLICKS_COLLECTION].create_index(
            [("kind", ASCENDING), ("created_at", DESCENDING)],
            name="app_click_kind",
        )
    except Exception:
        return


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 30
