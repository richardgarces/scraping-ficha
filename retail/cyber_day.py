"""Modo Cyber Day: loop continuo sobre queries fijas (Tablas Sonic).

Cada ítem es una query de búsqueda. El worker busca/refresca top matches,
notifica Telegram+push si cambia precio/oferta, y al terminar 1→N reinicia.

Estado: `app_settings.cyber_day_run`. Lista: `cyber_day_products`.
Seed: `data/cyber_day_sonic.json` (carga automática si la colección está vacía).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_SETTING = "cyber_day_run"
STATUSES = frozenset({"idle", "running", "paused", "stopped"})
DEFAULT_DELAY = float(os.environ.get("CYBER_DAY_DELAY_SECONDS") or "2.5")
TOP_MATCHES = max(1, int(os.environ.get("CYBER_DAY_TOP_MATCHES") or "6"))
REFRESH_TOP = max(0, int(os.environ.get("CYBER_DAY_REFRESH_TOP") or "3"))
SEARCH_MAX_ITEMS = max(1, int(os.environ.get("CYBER_DAY_SEARCH_MAX_ITEMS") or "4"))
HEARTBEAT_MAX_AGE = 180
SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "cyber_day_sonic.json"
CYBER_SCORE = 92


class CyberDayError(Exception):
    """Error de control (lista vacía, transición inválida)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace("$", "").replace(" ", "")
    if not text:
        return None
    if text.count(".") == 1 and text.count(",") == 0 and len(text.split(".")[-1]) == 3:
        text = text.replace(".", "")
    else:
        text = text.replace(".", "").replace(",", "")
    try:
        return int(text)
    except ValueError:
        return None


def offer_signature(price: Any, price_normal: Any = None, price_card: Any = None) -> str:
    return f"{int(price or 0)}:{int(price_normal or 0)}:{int(price_card or 0)}"


def match_key(store: str, product_id: str) -> str:
    return f"{store}:{product_id}"


def default_run() -> dict[str, Any]:
    return {
        "status": "idle",
        "cursor": 0,
        "lap": 0,
        "processed": 0,
        "total": 0,
        "started_at": None,
        "lap_started_at": None,
        "last_lap_elapsed_seconds": None,
        "last_lap_finished_at": None,
        "last_error": None,
        "last_change": None,
        "notified_count": 0,
        "heartbeat_at": None,
        "worker": None,
        "source_note": "Seed oficial Cyber Day (100 queries Sonic).",
    }


def load_run(repo: Any) -> dict[str, Any]:
    found = repo.get_app_setting(RUN_SETTING) if hasattr(repo, "get_app_setting") else None
    if not found:
        return default_run()
    base = default_run()
    base.update({k: v for k, v in found.items() if k != "updated_at"})
    if base.get("status") not in STATUSES:
        base["status"] = "idle"
    return base


def save_run(repo: Any, data: dict[str, Any]) -> dict[str, Any]:
    payload = {**default_run(), **data}
    payload["status"] = payload.get("status") if payload.get("status") in STATUSES else "idle"
    return repo.save_app_setting(RUN_SETTING, payload)


def products_collection(repo: Any):
    coll = getattr(repo, "cyber_day_products", None)
    if coll is not None:
        return coll
    return repo.db["cyber_day_products"]


def list_products(repo: Any) -> list[dict[str, Any]]:
    rows = list(products_collection(repo).find().sort([("order", 1), ("_id", 1)]))
    for row in rows:
        row["id"] = str(row.get("_id"))
        row.pop("_id", None)
    return rows


def products_count(repo: Any) -> int:
    return int(products_collection(repo).count_documents({}))


def clear_products(repo: Any) -> None:
    products_collection(repo).delete_many({})


def normalize_import_row(raw: dict[str, Any], order: int) -> dict[str, Any] | None:
    """Normaliza fila a query Cyber Day (name/query + category opcionales)."""
    if not isinstance(raw, dict):
        return None
    lower = {str(k).strip().lower(): v for k, v in raw.items()}

    def pick(*names: str) -> Any:
        for name in names:
            if name in lower and lower[name] not in (None, ""):
                return lower[name]
        return None

    query = str(
        pick("query", "q", "search", "name", "nombre", "producto", "title", "titulo") or ""
    ).strip()
    category = str(pick("category", "categoria", "categoría", "cat") or "").strip()
    n = _as_int(pick("n", "order", "orden", "#"))
    store = str(pick("store", "tienda") or "").strip().lower()
    product_id = str(pick("product_id", "productid", "sku", "sku_id", "id") or "").strip()
    url = str(pick("url", "link") or "").strip()
    reference = _as_int(pick("reference_price", "precio_referencia", "precio", "price", "ref"))
    if not query and not product_id and not url:
        return None
    if not query:
        query = product_id or url or f"item-{order + 1}"
    return {
        "order": int(n - 1) if n and n > 0 else order,
        "n": int(n) if n and n > 0 else order + 1,
        "query": query,
        "name": query,
        "category": category,
        "store": store,
        "product_id": product_id,
        "sku": product_id,
        "url": url,
        "reference_price": reference,
        "last_price": None,
        "last_price_normal": None,
        "last_signature": None,
        "last_matches": {},
        "last_match_count": 0,
        "last_observed_at": None,
        "last_error": None,
        "resolved": False,
    }


def parse_products_payload(text: str, *, filename: str = "") -> list[dict[str, Any]]:
    clean = (text or "").strip()
    if not clean:
        return []
    name = (filename or "").lower()
    rows: list[Any] = []
    if name.endswith(".csv") or ("," in clean.split("\n", 1)[0] and not clean.startswith(("{", "["))):
        reader = csv.DictReader(io.StringIO(clean))
        rows = list(reader)
    else:
        data = json.loads(clean)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("products") or data.get("items") or data.get("rows") or []
        else:
            rows = []
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(rows):
        item = normalize_import_row(raw if isinstance(raw, dict) else {}, index)
        if item:
            out.append(item)
    out.sort(key=lambda row: (int(row.get("order") or 0), int(row.get("n") or 0)))
    for index, item in enumerate(out):
        item["order"] = index
        item["n"] = index + 1
    return out


def load_seed_items(path: Path | None = None) -> list[dict[str, Any]]:
    seed = path or SEED_PATH
    if not seed.is_file():
        return []
    return parse_products_payload(seed.read_text(encoding="utf-8"), filename=seed.name)


def import_products(repo: Any, items: list[dict[str, Any]], *, source: str = "import") -> dict[str, Any]:
    if not items:
        raise CyberDayError("La lista importada está vacía.")
    clear_products(repo)
    now = _now()
    docs = []
    for item in items:
        docs.append({**item, "source": source, "created_at": now, "updated_at": now})
    products_collection(repo).insert_many(docs)
    run = load_run(repo)
    run["total"] = len(docs)
    run["cursor"] = 0
    run["processed"] = 0
    run["lap"] = 0
    if run.get("status") == "running":
        run["status"] = "stopped"
    run["source_note"] = f"Lista Cyber Day: {len(docs)} queries ({source})."
    run["last_error"] = None
    save_run(repo, run)
    return {"ok": True, "imported": len(docs), "total": len(docs), "source": source}


def ensure_seed(repo: Any) -> dict[str, Any]:
    """Si la colección está vacía, carga `data/cyber_day_sonic.json`."""
    total = products_count(repo)
    if total > 0:
        return {"seeded": False, "total": total}
    items = load_seed_items()
    if not items:
        return {"seeded": False, "total": 0, "detail": "Seed JSON ausente o vacío."}
    result = import_products(repo, items, source="seed")
    return {"seeded": True, **result}


def progress_view(run: dict[str, Any], *, product_total: int | None = None) -> dict[str, Any]:
    total = int(product_total if product_total is not None else run.get("total") or 0)
    processed = min(int(run.get("processed") or 0), total) if total else 0
    percent = round((processed / total) * 100, 1) if total else 0.0
    lap_started = run.get("lap_started_at")
    elapsed = None
    eta = None
    if isinstance(lap_started, datetime) and run.get("status") == "running":
        start = lap_started if lap_started.tzinfo else lap_started.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((_now() - start).total_seconds()))
        if processed > 0 and total > processed:
            eta = int((elapsed / processed) * (total - processed))
    heartbeat = run.get("heartbeat_at")
    healthy = False
    if isinstance(heartbeat, datetime):
        hb = heartbeat if heartbeat.tzinfo else heartbeat.replace(tzinfo=timezone.utc)
        healthy = (_now() - hb).total_seconds() <= HEARTBEAT_MAX_AGE
    return {
        "status": run.get("status") or "idle",
        "lap": int(run.get("lap") or 0),
        "cursor": int(run.get("cursor") or 0),
        "processed": processed,
        "total": total,
        "percent": percent,
        "lap_elapsed_seconds": elapsed if elapsed is not None else run.get("last_lap_elapsed_seconds"),
        "lap_eta_seconds": eta,
        "started_at": _iso(run.get("started_at")),
        "lap_started_at": _iso(run.get("lap_started_at")),
        "last_lap_elapsed_seconds": run.get("last_lap_elapsed_seconds"),
        "last_lap_finished_at": _iso(run.get("last_lap_finished_at")),
        "last_error": run.get("last_error"),
        "last_change": run.get("last_change"),
        "notified_count": int(run.get("notified_count") or 0),
        "worker": run.get("worker"),
        "worker_healthy": healthy,
        "heartbeat_at": _iso(heartbeat),
        "source_note": run.get("source_note"),
        "import_required": total <= 0,
    }


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def status_payload(repo: Any) -> dict[str, Any]:
    ensure_seed(repo)
    run = load_run(repo)
    total = products_count(repo)
    run["total"] = total
    progress = progress_view(run, product_total=total)
    preview = list_products(repo)[:40]
    return {
        "ok": True,
        "run": progress,
        "products_preview": preview,
        "products_count": total,
    }


def start_run(repo: Any) -> dict[str, Any]:
    ensure_seed(repo)
    total = products_count(repo)
    if total <= 0:
        raise CyberDayError("No hay queries Cyber Day. Revisá el seed o importá CSV/JSON.")
    run = load_run(repo)
    if run.get("status") == "running":
        raise CyberDayError("Cyber Day ya está en curso.")
    now = _now()
    run.update({
        "status": "running",
        "cursor": 0,
        "processed": 0,
        "total": total,
        "lap": 1,
        "started_at": now,
        "lap_started_at": now,
        "last_error": None,
    })
    save_run(repo, run)
    return status_payload(repo)


def stop_run(repo: Any) -> dict[str, Any]:
    run = load_run(repo)
    if run.get("status") not in {"running", "paused"}:
        raise CyberDayError("Cyber Day no está en curso.")
    run["status"] = "stopped"
    save_run(repo, run)
    return status_payload(repo)


def continue_run(repo: Any) -> dict[str, Any]:
    ensure_seed(repo)
    total = products_count(repo)
    if total <= 0:
        raise CyberDayError("No hay queries Cyber Day. Revisá el seed o importá CSV/JSON.")
    run = load_run(repo)
    if run.get("status") == "running":
        raise CyberDayError("Cyber Day ya está en curso.")
    if run.get("status") not in {"stopped", "paused", "idle"}:
        raise CyberDayError("No se puede continuar desde este estado.")
    now = _now()
    cursor = int(run.get("cursor") or 0)
    if cursor >= total:
        cursor = 0
    lap = int(run.get("lap") or 0) or 1
    run.update({
        "status": "running",
        "cursor": cursor,
        "processed": min(cursor, total),
        "total": total,
        "lap": lap,
        "started_at": run.get("started_at") or now,
        "lap_started_at": run.get("lap_started_at") or now,
        "last_error": None,
    })
    save_run(repo, run)
    return status_payload(repo)


def touch_worker(repo: Any) -> None:
    run = load_run(repo)
    run["heartbeat_at"] = _now()
    run["worker"] = socket.gethostname()
    save_run(repo, run)


def notify_cyber_change(repo: Any, change: dict[str, Any]) -> int:
    """Telegram admin + alertas a quienes siguen el producto (telegram/push)."""
    sent = 0
    store = str(change.get("store") or "")
    product_id = str(change.get("product_id") or "")
    price = int(change.get("price") or 0)
    entity = f"cyber:{store}:{product_id}"
    from retail.price_alerts import notify_price_changes, price_change_message

    try:
        sent += int(notify_price_changes(repo, [change]) or 0)
    except Exception as exc:
        print(f"cyber-day: notify followers falló: {exc}", flush=True)

    try:
        from retail.batch.alerts import _telegram_text

        claimed = True
        if hasattr(repo, "claim_user_notification_send"):
            claimed = repo.claim_user_notification_send("cyber_day", "telegram", entity, price)
        if claimed:
            _, body = price_change_message(change)
            query = str(change.get("query") or "")
            prefix = f"Cyber Day · {query}\n\n" if query else "Cyber Day · cambio de precio\n\n"
            if _telegram_text(prefix + body, image_url=change.get("image_url")):
                sent += 1
    except Exception as exc:
        print(f"cyber-day: telegram admin falló: {exc}", flush=True)

    try:
        from retail.batch.rules import load_rules
        from retail.web_push import send_user_push

        system_channels = set(load_rules().get("channels") or [])
        if "push" not in system_channels:
            return sent
        users = getattr(repo, "users", None)
        if users is None:
            return sent
        for user in users.find({"role": "admin", "status": "approved"}):
            prefs = user.get("notification_preferences") or {}
            if "push" not in (prefs.get("channels") or []) or not user.get("push_subscriptions"):
                continue
            user_id = str(user.get("_id"))
            if hasattr(repo, "claim_user_notification_send"):
                if not repo.claim_user_notification_send(user_id, "push", entity, price):
                    continue
            payload = {
                **change,
                "message": change.get("message")
                or f"Cyber Day: {change.get('name')} → ${price:,}".replace(",", "."),
            }
            if send_user_push(user, payload, repo=repo, tag=entity):
                sent += 1
    except Exception as exc:
        print(f"cyber-day: push admin falló: {exc}", flush=True)
    return sent


def _offer_rows_from_search(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in result.get("groups") or []:
        for offer in group.get("offers") or []:
            if isinstance(offer, dict):
                rows.append(offer)
    if rows:
        return rows
    for offer in result.get("products") or result.get("offers") or []:
        if isinstance(offer, dict):
            rows.append(offer)
        elif hasattr(offer, "to_dict"):
            rows.append(offer.to_dict(flatten_specs=False))
    return rows


def _rank_matches(docs: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    def sort_key(doc: dict[str, Any]) -> tuple:
        price = _as_int(doc.get("price")) or 10**12
        normal = _as_int(doc.get("price_normal")) or 0
        discount = max(0, normal - price) if normal > price else 0
        return (-discount, price, str(doc.get("store") or ""), str(doc.get("product_id") or ""))

    ranked = sorted((d for d in docs if _as_int(d.get("price"))), key=sort_key)
    return ranked[:limit]


def boost_catalog_priority(repo: Any, catalog_id: str, *, reason: str = "cyber_day") -> None:
    catalog_id = str(catalog_id or "").strip()
    if not catalog_id or getattr(repo, "scrape_priorities", None) is None:
        return
    now = _now()
    repo.scrape_priorities.update_one(
        {"catalog_id": catalog_id},
        {
            "$set": {
                "catalog_id": catalog_id,
                "score": CYBER_SCORE,
                "tier": "high",
                "next_due_at": now,
                "updated_at": now,
                "boost_reason": reason,
                "reasons": ["Prioridad Cyber Day: query en loop activo."],
            }
        },
        upsert=True,
    )


def collect_query_matches(repo: Any, query: str) -> list[dict[str, Any]]:
    """Catálogo local + búsqueda scrape ligera; top matches rankeados."""
    seen: dict[str, dict[str, Any]] = {}
    try:
        for doc in repo.find_by_query(query, limit=max(TOP_MATCHES * 3, 20)):
            key = match_key(str(doc.get("store") or ""), str(doc.get("product_id") or ""))
            if key != ":":
                seen[key] = doc
    except Exception as exc:
        print(f"cyber-day: find_by_query falló ({query}): {exc}", flush=True)

    try:
        from retail.search import search_products

        result = search_products(
            query,
            source="both",
            max_items=SEARCH_MAX_ITEMS,
            delay=min(DEFAULT_DELAY, 1.0),
            timeout=10.0,
            persist=True,
            persist_meta={"source": "cyber_day"},
            price_band=True,
            fresh=False,
            background_side_effects=False,
            wait_for_all=False,
            recover_underfilled_db=True,
        )
        for offer in _offer_rows_from_search(result):
            store = str(offer.get("store") or "")
            product_id = str(offer.get("product_id") or "")
            if store and product_id:
                seen[match_key(store, product_id)] = offer
    except Exception as exc:
        print(f"cyber-day: search_products falló ({query}): {exc}", flush=True)

    return _rank_matches(list(seen.values()), TOP_MATCHES)


def refresh_top_matches(repo: Any, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from retail.product_refresh import refresh_product_price

    fresh_rows: list[dict[str, Any]] = []
    for offer in matches[:REFRESH_TOP]:
        store = str(offer.get("store") or "")
        product_id = str(offer.get("product_id") or "")
        if not store or not product_id:
            continue
        try:
            refresh_product_price(repo, store, product_id)
        except Exception as exc:
            print(f"cyber-day: refresh {store}/{product_id}: {exc}", flush=True)
        detail = repo.product_detail(store, product_id) or offer
        fresh_rows.append(detail)
        boost_catalog_priority(repo, str(detail.get("catalog_id") or ""))
    # Matches sin refresh puntual igual entran al seguimiento de firma.
    refreshed_keys = {match_key(str(r.get("store") or ""), str(r.get("product_id") or "")) for r in fresh_rows}
    for offer in matches:
        key = match_key(str(offer.get("store") or ""), str(offer.get("product_id") or ""))
        if key not in refreshed_keys:
            fresh_rows.append(offer)
            boost_catalog_priority(repo, str(offer.get("catalog_id") or ""))
    return fresh_rows


def detect_changes(
    previous: dict[str, Any] | None,
    matches: list[dict[str, Any]],
    *,
    query: str,
) -> tuple[dict[str, str], list[dict[str, Any]], dict[str, Any] | None]:
    """Compara firmas previas vs actuales. Primera observación no notifica."""
    prev = dict(previous or {})
    current: dict[str, str] = {}
    changes: list[dict[str, Any]] = []
    best_price = None
    best_normal = None
    best_sig = None
    for offer in matches:
        store = str(offer.get("store") or "")
        product_id = str(offer.get("product_id") or "")
        if not store or not product_id:
            continue
        price = _as_int(offer.get("price"))
        if price is None:
            continue
        price_normal = _as_int(offer.get("price_normal"))
        price_card = _as_int(offer.get("price_card"))
        sig = offer_signature(price, price_normal, price_card)
        key = match_key(store, product_id)
        current[key] = sig
        if best_price is None or price < best_price:
            best_price = price
            best_normal = price_normal
            best_sig = sig
        old = prev.get(key)
        if not old or old == sig:
            continue
        try:
            old_price = int(str(old).split(":", 1)[0])
        except ValueError:
            old_price = None
        if old_price is None or old_price == price:
            # Cambio solo de oferta (normal/card) también cuenta.
            if old == sig:
                continue
        changes.append({
            "store": store,
            "product_id": product_id,
            "name": offer.get("name") or query,
            "url": offer.get("url") or "",
            "image_url": offer.get("image_url") or "",
            "previous_price": old_price if old_price is not None else price,
            "price": price,
            "price_normal": price_normal,
            "query": query,
            "message": f"Cyber Day ({query}): {old} → {sig}",
        })
    summary = {
        "last_price": best_price,
        "last_price_normal": best_normal,
        "last_signature": best_sig,
    }
    return current, changes, summary


def process_one(repo: Any, *, delay: float = 0.0) -> dict[str, Any]:
    """Procesa la query del cursor si el run está `running`."""
    run = load_run(repo)
    if run.get("status") != "running":
        return {"ok": True, "skipped": True, "reason": "not_running", "status": run.get("status")}

    coll = products_collection(repo)
    total = int(coll.count_documents({}))
    if total <= 0:
        seeded = ensure_seed(repo)
        total = int(seeded.get("total") or products_count(repo))
        if total <= 0:
            run["status"] = "stopped"
            run["last_error"] = "Lista vacía."
            run["total"] = 0
            save_run(repo, run)
            return {"ok": False, "detail": "Lista vacía."}

    cursor = int(run.get("cursor") or 0)
    if cursor >= total:
        return _finish_lap(repo, run, total)

    item = next(coll.find().sort([("order", 1), ("_id", 1)]).skip(cursor).limit(1), None)
    if item is None:
        return _finish_lap(repo, run, total)

    query = str(item.get("query") or item.get("name") or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "query": query,
        "category": item.get("category"),
        "cursor": cursor,
        "lap": run.get("lap"),
        "n": item.get("n"),
    }
    now = _now()
    notified = 0
    changed = 0

    try:
        if not query:
            raise CyberDayError("Query vacía.")
        matches = collect_query_matches(repo, query)
        fresh = refresh_top_matches(repo, matches) if matches else []
        tracked = fresh or matches
        current_sigs, changes, summary = detect_changes(
            item.get("last_matches"), tracked, query=query,
        )
        # Primera vuelta: solo memoriza firmas.
        had_history = bool(item.get("last_matches"))
        if had_history:
            for change in changes:
                sent = notify_cyber_change(repo, change)
                notified += sent
                changed += 1
                run["last_change"] = {
                    "at": _iso(now),
                    "query": query,
                    "store": change["store"],
                    "product_id": change["product_id"],
                    "name": change["name"],
                    "previous_price": change["previous_price"],
                    "price": change["price"],
                    "notified": sent,
                }
        if changed:
            run["notified_count"] = int(run.get("notified_count") or 0) + changed

        coll.update_one(
            {"_id": item["_id"]},
            {
                "$set": {
                    "query": query,
                    "name": query,
                    "resolved": bool(tracked),
                    "last_matches": current_sigs,
                    "last_match_count": len(current_sigs),
                    "last_price": summary.get("last_price") if summary else None,
                    "last_price_normal": summary.get("last_price_normal") if summary else None,
                    "last_signature": summary.get("last_signature") if summary else None,
                    "last_observed_at": now,
                    "last_error": None if tracked else "Sin matches en catálogo/scrape.",
                    "updated_at": now,
                }
            },
        )
        result.update({
            "ok": True,
            "matches": len(current_sigs),
            "changed": changed,
            "notified": notified,
            "price": summary.get("last_price") if summary else None,
        })
        if not tracked:
            run["last_error"] = f"Sin matches: {query}"
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"[:400]
        coll.update_one({"_id": item["_id"]}, {"$set": {"last_error": err, "updated_at": now}})
        run["last_error"] = err
        result["detail"] = err

    current = load_run(repo)
    if current.get("status") != "running":
        result["stopped_during"] = True
        return result

    next_cursor = cursor + 1
    run["cursor"] = next_cursor
    run["processed"] = next_cursor
    run["total"] = total
    run["heartbeat_at"] = now
    run["worker"] = socket.gethostname()
    if next_cursor >= total:
        save_run(repo, run)
        lap_result = _finish_lap(repo, run, total)
        result["lap_finished"] = True
        result.update(lap_result)
    else:
        save_run(repo, run)

    if delay > 0:
        time.sleep(delay)
    return result


def _finish_lap(repo: Any, run: dict[str, Any], total: int) -> dict[str, Any]:
    now = _now()
    started = run.get("lap_started_at")
    elapsed = None
    if isinstance(started, datetime):
        start = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((now - start).total_seconds()))
    current = load_run(repo)
    if current.get("status") != "running":
        return {"ok": True, "lap_finished": True, "status": current.get("status")}
    next_lap = int(run.get("lap") or 1) + 1
    run.update({
        "status": "running",
        "cursor": 0,
        "processed": 0,
        "total": total,
        "lap": next_lap,
        "lap_started_at": now,
        "last_lap_elapsed_seconds": elapsed,
        "last_lap_finished_at": now,
        "heartbeat_at": now,
        "worker": socket.gethostname(),
    })
    save_run(repo, run)
    print(
        f"cyber-day lap {next_lap - 1} done in {elapsed}s; starting lap {next_lap} ({total} queries)",
        flush=True,
    )
    return {
        "ok": True,
        "lap_finished": True,
        "last_lap": next_lap - 1,
        "last_lap_elapsed_seconds": elapsed,
        "lap": next_lap,
    }


def worker_loop(repo: Any, *, delay: float = DEFAULT_DELAY, poll_seconds: float = 2.0) -> None:
    ensure_seed(repo)
    while True:
        touch_worker(repo)
        run = load_run(repo)
        if run.get("status") != "running":
            time.sleep(poll_seconds)
            continue
        metrics = process_one(repo, delay=delay)
        if metrics.get("skipped"):
            time.sleep(poll_seconds)
        elif metrics.get("ok"):
            print(
                f"cyber-day lap={metrics.get('lap')} n={metrics.get('n')} "
                f"query={metrics.get('query')!r} matches={metrics.get('matches')} "
                f"changed={metrics.get('changed')} notified={metrics.get('notified')}",
                flush=True,
            )
        else:
            print(f"cyber-day error: {metrics.get('detail')}", flush=True)
            time.sleep(max(delay, 1.0))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--seed", action="store_true", help="Carga seed si la colección está vacía")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    args = parser.parse_args()

    from retail.mongo import ProductRepository

    repo = ProductRepository()
    if not hasattr(repo, "cyber_day_products"):
        repo.cyber_day_products = repo.db["cyber_day_products"]
    try:
        if args.seed or args.healthcheck or args.once:
            ensure_seed(repo)
        if args.healthcheck:
            run = load_run(repo)
            progress = progress_view(run, product_total=products_count(repo))
            if not progress.get("worker_healthy") and run.get("status") == "running":
                raise SystemExit(1)
            return
        if args.once:
            print(process_one(repo, delay=0), flush=True)
            return
        worker_loop(repo, delay=args.delay)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
