"""Conteo agregado de peticiones de la app (día + hora + origen, America/Santiago)."""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retail.mongo import APP_REQUESTS_COLLECTION, DEFAULT_DB, DEFAULT_URI

TZ = ZoneInfo("America/Santiago")
DAY_WINDOW = 30
WEEK_WINDOW = 7
TOP_ORIGINS = 12

# Páginas y las APIs de búsqueda/catálogo. No archivos estáticos, health ni el
# propio endpoint de estadísticas (se refresca solo).
_COUNTED_API = (
    "/api/search",
    "/api/catalog",
    "/api/explore-categories",
    "/api/deals",
    "/api/reales",
    "/api/super",
    "/api/product",
    "/api/categories",
    "/api/stores",
    "/api/watches",
    "/api/price-alert",
)
_SKIP_EXACT = {
    "/api/health",
    "/api/admin/stats",
    "/api/clicks",
    "/favicon.ico",
    "/robots.txt",
}
_GROUP_KEYS = ("buscar", "catalogo", "ofertas", "producto", "tiendas", "siguiendo", "cuenta", "admin", "otro")

_client = None
_indexed = False
_down_until = 0.0
_lock = threading.Lock()


def santiago_now(when: datetime | None = None) -> datetime:
    moment = when or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TZ)


def should_count(path: str, method: str = "GET") -> bool:
    if method and method.upper() not in {"GET", "POST", "PUT", "DELETE"}:
        return False
    clean = _path_only(path)
    if not clean.startswith("/"):
        return False
    lower = clean.lower()
    if lower.startswith("/static/") or lower.startswith("/favicon") or lower.startswith("/api/thumb"):
        return False
    if lower in _SKIP_EXACT:
        return False
    leaf = lower.rsplit("/", 1)[-1]
    if "." in leaf:
        return False
    if lower.startswith("/api/"):
        return _api_counted(lower)
    return True


def path_group(path: str) -> str:
    clean = _path_only(path).rstrip("/") or "/"
    if clean == "/" or clean.startswith("/api/search"):
        return "buscar"
    if clean in {"/catalogo"} or clean.startswith("/api/catalog") or clean.startswith("/api/categories"):
        return "catalogo"
    if clean in {"/hoy", "/reales", "/super", "/ofertas"} or clean.startswith("/api/deals") or clean.startswith("/api/reales") or clean.startswith("/api/super"):
        return "ofertas"
    if clean in {"/producto"} or clean.startswith("/api/product"):
        return "producto"
    if clean in {"/tiendas"} or clean.startswith("/api/stores"):
        return "tiendas"
    if clean in {"/siguiendo"} or clean.startswith("/api/watches") or clean.startswith("/api/price-alert"):
        return "siguiendo"
    if clean in {"/entrar"} or clean.startswith("/api/auth") or clean.startswith("/api/users"):
        return "cuenta"
    if (
        clean in {"/cron", "/estadisticas", "/usuarios", "/analisis-producto"}
        or clean.startswith("/api/admin")
        or clean.startswith("/api/settings")
        or clean.startswith("/api/batch")
        or clean.startswith("/api/alerts")
        or clean.startswith("/api/history")
    ):
        return "admin"
    return "otro"


def client_ip(headers, client_host: str | None = None) -> str:
    """Primera IP de X-Forwarded-For (lo que pone platform-caddy), si no el socket."""
    forwarded = _header(headers, "x-forwarded-for")
    first = forwarded.split(",")[0].strip().strip('"') if forwarded else ""
    token = _clean_token(first) or _clean_token(client_host)
    return token or "desconocido"


def client_country(headers) -> str:
    raw = _header(headers, "cf-ipcountry").strip().upper()
    if len(raw) == 2 and raw.isalpha() and raw != "XX":
        return raw
    return ""


def make_bucket(path: str, ip: str, country: str, *, when: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(when)
    group = path_group(path)
    if group not in _GROUP_KEYS:
        group = "otro"
    return {
        "day": local.date().isoformat(),
        "hour": local.hour,
        "ip": client_ip({"x-forwarded-for": ip}) if ip else "desconocido",
        "country": country.strip().upper() if len(country.strip()) == 2 and country.strip().isalpha() else "",
        "group": group,
    }


def record_request(
    path: str,
    ip: str,
    country: str = "",
    *,
    method: str = "GET",
    when: datetime | None = None,
    collection=None,
) -> dict[str, Any] | None:
    if not should_count(path, method):
        return None
    bucket = make_bucket(path, ip, country, when=when)
    target = collection if collection is not None else _live_collection()
    if target is not None:
        apply_hit(target, visit=_is_page(path), **bucket)
    return bucket


def apply_hit(
    collection,
    *,
    day: str,
    hour: int,
    ip: str,
    country: str,
    group: str,
    visit: bool = False,
    now: datetime | None = None,
) -> None:
    """Incremento atómico de un cubo día/hora/origen. `group` no va en la clave."""
    if group not in _GROUP_KEYS:
        group = "otro"
    moment = now or datetime.now(timezone.utc)
    inc = {"count": 1, f"groups.{group}": 1}
    # Las páginas HTML se cuentan aparte. Las APIs no: si no, una búsqueda
    # inflaría los ingresos. Los cubos viejos no tienen `visits`.
    if visit:
        inc["visits"] = 1
    collection.update_one(
        {"day": day, "hour": int(hour), "ip": ip, "country": country or ""},
        {
            "$inc": inc,
            "$set": {"updated_at": moment},
        },
        upsert=True,
    )


def load_stats(*, now: datetime | None = None) -> dict[str, Any]:
    local = santiago_now(now)
    since = (local.date() - timedelta(days=DAY_WINDOW - 1)).isoformat()
    coll = _live_collection()
    if coll is None:
        return summarize_rows([], now=local, mongo=False)
    try:
        rows = list(
            coll.find(
                {"day": {"$gte": since}},
                {"_id": 0, "day": 1, "hour": 1, "ip": 1, "country": 1, "count": 1, "groups": 1, "visits": 1},
            )
        )
    except Exception:
        _mark_down()
        return summarize_rows([], now=local, mongo=False)
    return summarize_rows(rows, now=local, mongo=True)


def summarize_rows(rows: list[dict[str, Any]], *, now: datetime | None = None, mongo: bool = True) -> dict[str, Any]:
    local = santiago_now(now)
    today = local.date()
    days = [today - timedelta(days=offset) for offset in range(DAY_WINDOW - 1, -1, -1)]
    day_keys = [day.isoformat() for day in days]
    day_set = set(day_keys)
    week_start = (today - timedelta(days=WEEK_WINDOW - 1)).isoformat()
    today_key = today.isoformat()

    by_day = {key: 0 for key in day_keys}
    page_by_day = {key: 0 for key in day_keys}
    visitors_by_day = {key: set() for key in day_keys}
    hour_today = [0] * 24
    hour_sum = [0] * 24
    origins: dict[tuple[str, str], int] = {}
    groups = {key: 0 for key in _GROUP_KEYS}

    for row in rows:
        day = str(row.get("day") or "")
        if day not in day_set:
            continue
        count = int(row.get("count") or 0)
        if count < 0:
            count = 0
        visits = int(row.get("visits") or 0)
        if visits < 0:
            visits = 0
        by_day[day] += count
        page_by_day[day] += visits
        ip = str(row.get("ip") or "")
        if count > 0 and ip and ip != "desconocido":
            visitors_by_day[day].add(ip)
        hour = row.get("hour")
        if isinstance(hour, int) and 0 <= hour <= 23:
            hour_sum[hour] += count
            if day == today_key:
                hour_today[hour] += count
        ip = str(row.get("ip") or "desconocido")
        country = str(row.get("country") or "")
        origins[(ip, country)] = origins.get((ip, country), 0) + count
        for name, value in (row.get("groups") or {}).items():
            key = name if name in groups else "otro"
            groups[key] += int(value or 0)

    top = sorted(origins.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))[:TOP_ORIGINS]
    group_rows = [{"group": key, "count": groups[key]} for key in _GROUP_KEYS if groups[key]]
    group_rows.sort(key=lambda item: (-item["count"], item["group"]))

    def _window(keys: list[str]) -> set[str]:
        found: set[str] = set()
        for key in keys:
            found.update(visitors_by_day[key])
        return found

    week_keys = [key for key in day_keys if key >= week_start]
    return {
        "mongo": mongo,
        "timezone": "America/Santiago",
        "generated_at": local.isoformat(timespec="seconds"),
        "totals": {
            "today": by_day[today_key],
            "days_7": sum(by_day[key] for key in week_keys),
            "days_30": sum(by_day.values()),
        },
        "visitors": {
            "today": len(visitors_by_day[today_key]),
            "days_7": len(_window(week_keys)),
            "days_30": len(_window(day_keys)),
        },
        "page_visits": {
            "today": page_by_day[today_key],
            "days_7": sum(page_by_day[key] for key in week_keys),
            "days_30": sum(page_by_day.values()),
        },
        "by_day": [
            {
                "day": key,
                "count": by_day[key],
                "visitors": len(visitors_by_day[key]),
                "page_visits": page_by_day[key],
            }
            for key in day_keys
        ],
        "by_hour": [
            {
                "hour": hour,
                "today": hour_today[hour],
                "average": round(hour_sum[hour] / DAY_WINDOW, 1),
            }
            for hour in range(24)
        ],
        "origins": [
            {"ip": ip, "country": country, "count": count}
            for (ip, country), count in top
        ],
        "groups": group_rows,
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
                from pymongo import ASCENDING, MongoClient

                _client = MongoClient(
                    DEFAULT_URI,
                    serverSelectionTimeoutMS=800,
                    connectTimeoutMS=800,
                )
            collection = _client[DEFAULT_DB][APP_REQUESTS_COLLECTION]
            if not _indexed:
                collection.create_index(
                    [("day", ASCENDING), ("hour", ASCENDING), ("ip", ASCENDING), ("country", ASCENDING)],
                    unique=True,
                    name="app_request_bucket",
                )
                collection.create_index([("day", ASCENDING)], name="app_request_day")
                _indexed = True
            return collection
        except Exception:
            _down_until = time.monotonic() + 30
            return None


def _mark_down() -> None:
    global _down_until
    _down_until = time.monotonic() + 30


def _api_counted(path: str) -> bool:
    for root in _COUNTED_API:
        if path == root or path.startswith(root + "/") or path.startswith(root + "-"):
            return True
    return False


def _is_page(path: str) -> bool:
    return not _path_only(path).lower().startswith("/api/")


def _path_only(path: str) -> str:
    return str(path or "").split("?", 1)[0].split("#", 1)[0]


def _header(headers, name: str) -> str:
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return str(getter(name) or "")


def _clean_token(value: str | None) -> str:
    raw = str(value or "").strip()
    if not raw or any(ch.isspace() for ch in raw) or len(raw) > 64:
        return ""
    return raw
