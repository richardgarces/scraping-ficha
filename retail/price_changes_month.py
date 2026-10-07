"""Productos con cambios de valor de precio en una ventana reciente (admin / Cyber).

Unifica catálogo (`price_history`), Cyber (`cyber_day_price_history` / `last_change_at`)
y alertas seguidas (`price_alert_sends`) en una lista exportable a formato Cyber Day
(`n`, `query`, `category`).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from retail.pricing import parse_moment, santiago_day

SANTIAGO = ZoneInfo("America/Santiago")
DEFAULT_DAYS = 30
CATALOG_SCAN_LIMIT = 8000
EXPORT_FIELDS = ("n", "query", "category")
EXPORT_OPTIONAL = (
    "store",
    "previous_price",
    "price",
    "last_change_at",
    "source",
    "sources",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def window_bounds(days: int = DEFAULT_DAYS, *, now: datetime | None = None) -> dict[str, Any]:
    """Ventana de ~N días calendario America/Santiago (desde medianoche de hace N días)."""
    moment = now or _now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    today = santiago_day(moment)
    start_day = today - timedelta(days=max(1, int(days)))
    since_local = datetime(
        start_day.year, start_day.month, start_day.day, tzinfo=SANTIAGO
    )
    since_utc = since_local.astimezone(timezone.utc)
    return {
        "days": max(1, int(days)),
        "timezone": "America/Santiago",
        "from_day": start_day.isoformat(),
        "to_day": today.isoformat(),
        "since": since_utc,
        "since_iso": since_utc.isoformat(),
    }


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()
    parsed = parse_moment(value)
    return parsed.isoformat() if parsed else str(value)


def _query_key(query: str) -> str:
    return " ".join(str(query or "").casefold().split())


def catalog_price_value_change(
    history: list[dict[str, Any]] | None,
    since: datetime,
) -> dict[str, Any] | None:
    """Primer (último en el tiempo) cambio de valor `price` con punto en la ventana."""
    rows: list[tuple[datetime, int, dict[str, Any]]] = []
    for entry in history or []:
        if not isinstance(entry, dict):
            continue
        price = _as_int(entry.get("price"))
        if price is None or price <= 0:
            continue
        moment = parse_moment(entry.get("scraped_at"))
        if moment is None:
            continue
        rows.append((moment, price, entry))
    rows.sort(key=lambda item: item[0])
    last_change: dict[str, Any] | None = None
    for index in range(1, len(rows)):
        moment, price, entry = rows[index]
        prev_price = rows[index - 1][1]
        if moment < since:
            continue
        if price == prev_price:
            continue
        last_change = {
            "at": moment,
            "previous_price": prev_price,
            "price": price,
            "price_normal": _as_int(entry.get("price_normal")),
        }
    return last_change


def _store_label(store: str) -> str:
    try:
        from retail.store_display import public_store_label

        return public_store_label(store) or store
    except Exception:
        return store


def _merge_row(
    by_query: dict[str, dict[str, Any]],
    *,
    query: str,
    category: str = "",
    store: str = "",
    previous_price: int | None = None,
    price: int | None = None,
    last_change_at: datetime | str | None = None,
    source: str,
    product_id: str = "",
    url: str = "",
    name: str = "",
) -> None:
    clean_query = " ".join(str(query or name or "").split()).strip()
    if not clean_query:
        return
    key = _query_key(clean_query)
    at = parse_moment(last_change_at) if not isinstance(last_change_at, datetime) else last_change_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    existing = by_query.get(key)
    sources = {source}
    if existing:
        sources.update(str(s) for s in (existing.get("sources") or []) if s)
        existing_at = parse_moment(existing.get("last_change_at"))
        keep_existing = existing_at is not None and (at is None or existing_at >= at)
        if keep_existing:
            existing["sources"] = sorted(sources)
            if category and not existing.get("category"):
                existing["category"] = category
            return
        previous_price = previous_price if previous_price is not None else existing.get("previous_price")
        price = price if price is not None else existing.get("price")
        store = store or str(existing.get("store") or "")
        category = category or str(existing.get("category") or "")
        product_id = product_id or str(existing.get("product_id") or "")
        url = url or str(existing.get("url") or "")
    by_query[key] = {
        "id": key,
        "query": clean_query,
        "name": clean_query,
        "category": str(category or "").strip(),
        "store": str(store or "").strip(),
        "store_title": _store_label(store) if store else "",
        "previous_price": previous_price,
        "price": price,
        "last_change_at": _iso(at),
        "source": source,
        "sources": sorted(sources),
        "product_id": str(product_id or "").strip(),
        "url": str(url or "").strip(),
    }


def _collect_catalog(repo: Any, since: datetime, by_query: dict[str, dict[str, Any]]) -> int:
    coll = getattr(repo, "collection", None)
    if coll is None:
        return 0
    # Multikey: productos con algún punto reciente; el filtro de valor es en Python.
    cursor = coll.find(
        {"price_history.scraped_at": {"$gte": since}},
        {
            "name": 1,
            "store": 1,
            "product_id": 1,
            "category": 1,
            "catalog_category": 1,
            "url": 1,
            "price": 1,
            "price_history": 1,
        },
    ).limit(CATALOG_SCAN_LIMIT)
    count = 0
    for doc in cursor:
        change = catalog_price_value_change(doc.get("price_history"), since)
        if not change:
            continue
        category = str(doc.get("catalog_category") or doc.get("category") or "").strip()
        _merge_row(
            by_query,
            query=str(doc.get("name") or doc.get("product_id") or "").strip(),
            category=category,
            store=str(doc.get("store") or "").strip(),
            previous_price=change.get("previous_price"),
            price=change.get("price"),
            last_change_at=change.get("at"),
            source="catalog",
            product_id=str(doc.get("product_id") or "").strip(),
            url=str(doc.get("url") or "").strip(),
        )
        count += 1
    return count


def _cyber_history_coll(repo: Any) -> Any | None:
    coll = getattr(repo, "cyber_day_price_history", None)
    if coll is not None:
        return coll
    db = getattr(repo, "db", None)
    if db is None:
        return None
    try:
        return db["cyber_day_price_history"]
    except Exception:
        return None


def _cyber_products_coll(repo: Any) -> Any | None:
    coll = getattr(repo, "cyber_day_products", None)
    if coll is not None:
        return coll
    db = getattr(repo, "db", None)
    if db is None:
        return None
    try:
        return db["cyber_day_products"]
    except Exception:
        return None


def _collect_cyber_history(repo: Any, since: datetime, by_query: dict[str, dict[str, Any]]) -> int:
    coll = _cyber_history_coll(repo)
    products_coll = _cyber_products_coll(repo)
    category_by_qn: dict[tuple[str, int], str] = {}
    if products_coll is not None:
        try:
            for prod in products_coll.find(
                {},
                {"list_id": 1, "n": 1, "query": 1, "category": 1, "last_change_at": 1},
            ):
                lid = str(prod.get("list_id") or "")
                try:
                    n = int(prod.get("n") or 0)
                except (TypeError, ValueError):
                    n = 0
                cat = str(prod.get("category") or "").strip()
                if lid and n and cat:
                    category_by_qn[(lid, n)] = cat
                change_at = parse_moment(prod.get("last_change_at"))
                if change_at is not None and change_at >= since:
                    _merge_row(
                        by_query,
                        query=str(prod.get("query") or "").strip(),
                        category=cat,
                        last_change_at=change_at,
                        source="cyber_day",
                    )
        except Exception:
            pass

    if coll is None:
        return 0

    rows = list(coll.find({"at": {"$gte": since}}).sort("at", -1).limit(5000))
    seen: set[str] = set()
    count = 0
    for row in rows:
        query = str(row.get("query") or row.get("name") or "").strip()
        key = _query_key(query)
        if not key or key in seen:
            continue
        seen.add(key)
        lid = str(row.get("list_id") or "")
        try:
            n = int(row.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        _merge_row(
            by_query,
            query=query,
            category=category_by_qn.get((lid, n), ""),
            store=str(row.get("store") or "").strip(),
            price=_as_int(row.get("price")),
            last_change_at=row.get("at"),
            source="cyber_day",
            product_id=str(row.get("product_id") or "").strip(),
            url=str(row.get("url") or "").strip(),
            name=str(row.get("name") or "").strip(),
        )
        count += 1
    return count


def _collect_followed_alerts(repo: Any, since: datetime, by_query: dict[str, dict[str, Any]]) -> int:
    coll = getattr(repo, "price_alert_sends", None)
    if coll is None:
        return 0
    count = 0
    try:
        cursor = coll.find(
            {"created_at": {"$gte": since}},
            {"store": 1, "product_id": 1, "price": 1, "previous_price": 1, "created_at": 1, "name": 1},
        ).sort("created_at", -1).limit(3000)
    except Exception:
        return 0
    products = getattr(repo, "collection", None)
    for send in cursor:
        store = str(send.get("store") or "").strip()
        product_id = str(send.get("product_id") or "").strip()
        name = str(send.get("name") or "").strip()
        category = ""
        url = ""
        if products is not None and store and product_id:
            try:
                doc = products.find_one(
                    {"store": store, "product_id": product_id},
                    {"name": 1, "category": 1, "catalog_category": 1, "url": 1},
                )
            except Exception:
                doc = None
            if doc:
                name = name or str(doc.get("name") or "").strip()
                category = str(doc.get("catalog_category") or doc.get("category") or "").strip()
                url = str(doc.get("url") or "").strip()
        if not name:
            name = product_id or f"{store}:{product_id}"
        _merge_row(
            by_query,
            query=name,
            category=category,
            store=store,
            previous_price=_as_int(send.get("previous_price")),
            price=_as_int(send.get("price")),
            last_change_at=send.get("created_at"),
            source="following",
            product_id=product_id,
            url=url,
        )
        count += 1
    return count


def list_price_changes(
    repo: Any,
    *,
    days: int = DEFAULT_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Lista unificada de productos/queries con al menos un cambio de valor en la ventana."""
    bounds = window_bounds(days, now=now)
    since = bounds["since"]
    by_query: dict[str, dict[str, Any]] = {}
    stats = {
        "catalog": _collect_catalog(repo, since, by_query),
        "cyber_day": _collect_cyber_history(repo, since, by_query),
        "following": _collect_followed_alerts(repo, since, by_query),
    }
    items = sorted(
        by_query.values(),
        key=lambda row: (
            parse_moment(row.get("last_change_at")) or datetime.min.replace(tzinfo=timezone.utc),
            str(row.get("query") or ""),
        ),
        reverse=True,
    )
    for index, item in enumerate(items, start=1):
        item["n"] = index
    return {
        "ok": True,
        "timezone": bounds["timezone"],
        "days": bounds["days"],
        "from_day": bounds["from_day"],
        "to_day": bounds["to_day"],
        "since": bounds["since_iso"],
        "total": len(items),
        "stats": stats,
        "items": items,
    }


def export_selected(
    items: list[dict[str, Any]],
    *,
    selected_ids: list[str] | None = None,
    selected_queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Filtra filas seleccionadas y numera n=1.. para import Cyber."""
    id_set = {_query_key(x) for x in (selected_ids or []) if str(x).strip()}
    query_set = {_query_key(x) for x in (selected_queries or []) if str(x).strip()}
    use_filter = bool(id_set or query_set)
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        key = _query_key(str(row.get("id") or row.get("query") or ""))
        qkey = _query_key(str(row.get("query") or ""))
        if use_filter and key not in id_set and qkey not in query_set and qkey not in id_set:
            continue
        query = " ".join(str(row.get("query") or row.get("name") or "").split()).strip()
        if not query:
            continue
        out.append({
            "n": len(out) + 1,
            "query": query,
            "category": str(row.get("category") or "").strip(),
            "store": str(row.get("store") or "").strip() or None,
            "previous_price": row.get("previous_price"),
            "price": row.get("price"),
            "last_change_at": row.get("last_change_at"),
            "source": row.get("source"),
            "sources": row.get("sources"),
        })
    return out


def export_csv_text(rows: list[dict[str, Any]], *, include_optional: bool = True) -> str:
    fields = list(EXPORT_FIELDS)
    if include_optional:
        fields.extend(f for f in EXPORT_OPTIONAL if f not in fields)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        payload = dict(row)
        if isinstance(payload.get("sources"), list):
            payload["sources"] = "|".join(str(s) for s in payload["sources"])
        writer.writerow({key: payload.get(key) for key in fields})
    return buf.getvalue()


def export_json_payload(rows: list[dict[str, Any]], *, title: str = "Cambios de precio") -> dict[str, Any]:
    items = [
        {
            "n": row.get("n"),
            "query": row.get("query"),
            "category": row.get("category") or "",
        }
        for row in rows
    ]
    return {
        "id": "price_changes_month",
        "title": title,
        "items": items,
    }
