"""Modo Cyber Day: loop continuo sobre queries fijas (Tablas Sonic).

Cada ítem es una query de búsqueda. El worker busca/refresca top matches,
notifica Telegram+push si cambia precio/oferta, y al terminar 1→N reinicia.

Multi-lista: `cyber_day_lists` (slug/nombre) + productos en `cyber_day_products`
filtrados por `list_id`. Estado por lista: `app_settings.cyber_day_run:{slug}`
(legacy `cyber_day_run` se migra a la lista oficial). Seed oficial:
`data/cyber_junio2026.json` (auto si `cyber_junio2026` está vacía).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_SETTING = "cyber_day_run"  # legacy; migrado a cyber_day_run:{slug}
RUN_SETTING_PREFIX = "cyber_day_run:"
ACTIVE_LIST_SETTING = "cyber_day_active_list"
CYBER_GROUP_ID = "cyber_junio2026"
CYBER_GROUP_TITLE = "Cyber Junio 2026"
CYBER_LIST_ID = "cyber_junio2026"
STATUSES = frozenset({"idle", "running", "paused", "stopped"})
_SLUG_RE = re.compile(r"[^a-z0-9_]+")
DEFAULT_DELAY = float(os.environ.get("CYBER_DAY_DELAY_SECONDS") or "1.0")
TOP_MATCHES = max(1, int(os.environ.get("CYBER_DAY_TOP_MATCHES") or "6"))
REFRESH_TOP = max(0, int(os.environ.get("CYBER_DAY_REFRESH_TOP") or "2"))
SEARCH_MAX_ITEMS = max(1, int(os.environ.get("CYBER_DAY_SEARCH_MAX_ITEMS") or "3"))
# db = rápido (catálogo + refresh). both/scrape = también consulta tiendas (lento).
SEARCH_SOURCE = (os.environ.get("CYBER_DAY_SEARCH_SOURCE") or "db").strip().lower()
SEARCH_TIMEOUT = float(os.environ.get("CYBER_DAY_SEARCH_TIMEOUT") or "6")
# Tiendas prioritarias si hay scrape en vivo (evita Movistar/etc. que cuelgan el loop).
PREFERRED_SCRAPE_STORES = tuple(
    s.strip()
    for s in (os.environ.get("CYBER_DAY_STORES") or "falabella,paris,ripley,hites,lider,abcdin").split(",")
    if s.strip()
)
HEARTBEAT_MAX_AGE = 180
_DATA = Path(__file__).resolve().parents[1] / "data"
SEED_PATH = _DATA / "cyber_junio2026.json"
if not SEED_PATH.is_file():
    SEED_PATH = _DATA / "cyber_day_sonic.json"
CYBER_SCORE = 92
# Tiendas donde tiene sentido scrapear las queries Sonic.
CYBER_STORE_GROUPS = frozenset({
    "retail", "tecnologia", "deporte", "hogar", "belleza", "moda", "ferreteria",
})


def is_cyber_group(group_id: str | None) -> bool:
    key = str(group_id or "").strip().lower()
    return key in {CYBER_GROUP_ID, "cyber_day", "cyber"}


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


def _offer_price(offer: dict[str, Any]) -> int | None:
    """Precio oferta comparable: todo medio de pago si existe, si no price."""
    return _as_int(offer.get("price_all_payment")) or _as_int(offer.get("price"))


def ficha_path(store: str, product_id: str) -> str:
    store = str(store or "").strip()
    product_id = str(product_id or "").strip()
    if not store or not product_id:
        return ""
    from urllib.parse import quote

    return f"/producto?store={quote(store, safe='')}&id={quote(product_id, safe='')}"


def stats_from_signatures(last_matches: dict[str, Any] | None) -> dict[str, Any]:
    """Agrega tiendas/precios desde firmas `store:pid → price:normal:card`."""
    stores: set[str] = set()
    normals: list[int] = []
    offers: list[int] = []
    best_price: int | None = None
    best_normal: int | None = None
    best_sig: str | None = None
    best_store: str | None = None
    best_url = ""
    for key, sig in (last_matches or {}).items():
        text_key = str(key or "")
        if ":" not in text_key:
            continue
        store, product_id = text_key.split(":", 1)
        if not store or not product_id:
            continue
        parts = str(sig or "").split(":")
        try:
            price = int(parts[0]) if parts and parts[0] not in ("", "None") else None
        except ValueError:
            price = None
        if price is None or price <= 0:
            continue
        try:
            normal = int(parts[1]) if len(parts) > 1 and parts[1] not in ("", "None", "0") else None
        except ValueError:
            normal = None
        if normal is not None and normal <= 0:
            normal = None
        stores.add(store)
        offers.append(price)
        if normal is not None:
            normals.append(normal)
        if best_price is None or price < best_price:
            best_price = price
            best_normal = normal
            best_sig = str(sig)
            best_store = store
            best_url = ficha_path(store, product_id)
    return {
        "last_price": best_price,
        "last_price_normal": best_normal,
        "last_signature": best_sig,
        "stores_scraped": len(stores),
        "max_price_normal": max(normals) if normals else None,
        "min_price_normal": min(normals) if normals else None,
        "max_offer_price": max(offers) if offers else None,
        "best_offer_url": best_url or None,
        "best_store": best_store,
    }


def summarize_match_stats(matches: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrega stats de matches vivos (precio oferta = todo medio si aplica)."""
    stores: set[str] = set()
    normals: list[int] = []
    offers: list[int] = []
    best_price: int | None = None
    best_normal: int | None = None
    best_sig: str | None = None
    best_store: str | None = None
    best_url: str | None = None
    for offer in matches:
        store = str(offer.get("store") or "").strip()
        product_id = str(offer.get("product_id") or "").strip()
        if not store or not product_id:
            continue
        price = _offer_price(offer)
        if price is None or price <= 0:
            continue
        price_normal = _as_int(offer.get("price_normal"))
        if price_normal is not None and price_normal <= 0:
            price_normal = None
        price_card = _as_int(offer.get("price_card"))
        sig = offer_signature(price, price_normal, price_card)
        stores.add(store)
        offers.append(price)
        if price_normal is not None:
            normals.append(price_normal)
        if best_price is None or price < best_price:
            best_price = price
            best_normal = price_normal
            best_sig = sig
            best_store = store
            best_url = ficha_path(store, product_id) or (str(offer.get("url") or "").strip() or None)
    return {
        "last_price": best_price,
        "last_price_normal": best_normal,
        "last_signature": best_sig,
        "stores_scraped": len(stores),
        "max_price_normal": max(normals) if normals else None,
        "min_price_normal": min(normals) if normals else None,
        "max_offer_price": max(offers) if offers else None,
        "best_offer_url": best_url,
        "best_store": best_store,
    }


def _summary_patch(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {
            "last_price": None,
            "last_price_normal": None,
            "last_signature": None,
            "stores_scraped": 0,
            "max_price_normal": None,
            "min_price_normal": None,
            "max_offer_price": None,
            "best_offer_url": None,
            "best_store": None,
        }
    best_store = str(summary.get("best_store") or "").strip() or None
    return {
        "last_price": summary.get("last_price"),
        "last_price_normal": summary.get("last_price_normal"),
        "last_signature": summary.get("last_signature"),
        "stores_scraped": int(summary.get("stores_scraped") or 0),
        "max_price_normal": summary.get("max_price_normal"),
        "min_price_normal": summary.get("min_price_normal"),
        "max_offer_price": summary.get("max_offer_price"),
        "best_offer_url": summary.get("best_offer_url"),
        "best_store": best_store,
    }


def _prev_best_price_patch(item: dict[str, Any] | None, new_price: Any) -> dict[str, Any]:
    """Si el mejor precio cambia, guarda el anterior y la racha de dirección.

    Primera observación: sin prev. Si el precio se mantiene, no toca prev
    (el color sigue mientras prev ≠ current).

    last_delta_direction: 'up'|'down' de la última variación.
    delta_streak: 1 = primera en esa dirección; ≥2 = consecutiva (volvió a…).
    """
    old = _as_int((item or {}).get("last_price"))
    new = _as_int(new_price)
    if old is not None and new is not None and old != new:
        direction = "down" if new < old else "up"
        prev_dir = (item or {}).get("last_delta_direction")
        if prev_dir == direction:
            streak = int((item or {}).get("delta_streak") or 1) + 1
        else:
            streak = 1
        return {
            "prev_best_price": old,
            "last_delta_direction": direction,
            "delta_streak": streak,
        }
    if old is None:
        return {
            "prev_best_price": None,
            "last_delta_direction": None,
            "delta_streak": 0,
        }
    return {}


def price_direction(
    last_price: Any,
    prev_best_price: Any,
    *,
    last_delta_direction: Any = None,
    delta_streak: Any = 0,
) -> str | None:
    """Semántica visual del mejor precio.

    - down / up: primera baja o subida vs el previo
    - down_again / up_again: misma dirección otra vez (racha ≥ 2)
    - None: sin previo, sin cambio, o primer precio (blanco en UI)
    """
    current = _as_int(last_price)
    previous = _as_int(prev_best_price)
    if current is None or previous is None or current == previous:
        return None
    actual = "down" if current < previous else "up"
    try:
        streak = int(delta_streak or 1)
    except (TypeError, ValueError):
        streak = 1
    # Solo usar racha guardada si coincide con la dirección real vs prev.
    if last_delta_direction == actual and streak >= 2:
        return f"{actual}_again"
    return actual


def slugify_list(name: str) -> str:
    text = (name or "").strip().lower().replace("-", "_")
    text = _SLUG_RE.sub("_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return (text[:64] or "lista")


def run_setting_key(list_id: str) -> str:
    return f"{RUN_SETTING_PREFIX}{list_id}"


def lists_collection(repo: Any):
    coll = getattr(repo, "cyber_day_lists", None)
    if coll is not None:
        return coll
    return repo.db["cyber_day_lists"]


def products_collection(repo: Any):
    coll = getattr(repo, "cyber_day_products", None)
    if coll is not None:
        return coll
    return repo.db["cyber_day_products"]


def resolve_list_id(repo: Any, list_id: str | None = None) -> str:
    key = str(list_id or "").strip()
    if key:
        return key
    active = None
    if hasattr(repo, "get_app_setting"):
        active = repo.get_app_setting(ACTIVE_LIST_SETTING)
    if isinstance(active, dict):
        key = str(active.get("list_id") or active.get("slug") or "").strip()
    elif isinstance(active, str):
        key = active.strip()
    return key or CYBER_LIST_ID


def set_active_list(repo: Any, list_id: str) -> str:
    slug = resolve_list_id(repo, list_id)
    repo.save_app_setting(ACTIVE_LIST_SETTING, {"list_id": slug, "slug": slug})
    return slug


def default_run(list_id: str | None = None) -> dict[str, Any]:
    lid = list_id or CYBER_LIST_ID
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
        "source_note": f"Lista {lid}.",
        "list_id": lid,
        "group_id": lid if lid != CYBER_LIST_ID else CYBER_GROUP_ID,
    }


def load_run(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id)
    key = run_setting_key(lid)
    found = repo.get_app_setting(key) if hasattr(repo, "get_app_setting") else None
    if not found and lid == CYBER_LIST_ID and hasattr(repo, "get_app_setting"):
        # Migración: app_settings.cyber_day_run → cyber_day_run:cyber_junio2026
        legacy = repo.get_app_setting(RUN_SETTING)
        if legacy:
            found = {k: v for k, v in legacy.items() if k != "updated_at"}
            try:
                repo.save_app_setting(key, {**default_run(lid), **found, "list_id": lid})
            except Exception:
                pass
    if not found:
        return default_run(lid)
    base = default_run(lid)
    base.update({k: v for k, v in found.items() if k != "updated_at"})
    base["list_id"] = lid
    if base.get("status") not in STATUSES:
        base["status"] = "idle"
    return base


def save_run(repo: Any, data: dict[str, Any], list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id or data.get("list_id"))
    payload = {**default_run(lid), **data, "list_id": lid}
    payload["status"] = payload.get("status") if payload.get("status") in STATUSES else "idle"
    saved = repo.save_app_setting(run_setting_key(lid), payload)
    if lid == CYBER_LIST_ID:
        # Compat cron / código viejo que lee cyber_day_run.
        try:
            repo.save_app_setting(RUN_SETTING, payload)
        except Exception:
            pass
    return saved


def ensure_default_list(repo: Any) -> dict[str, Any]:
    """Garantiza al menos una lista + list_id en productos huérfanos.

    Si borraron la oficial pero quedan otras, no la recrea. Solo inserta
    `cyber_junio2026` cuando no hay ninguna meta de lista.
    """
    coll = lists_collection(repo)
    now = _now()
    if coll.count_documents({}) == 0:
        coll.insert_one({
            "slug": CYBER_LIST_ID,
            "name": CYBER_GROUP_TITLE,
            "title": CYBER_GROUP_TITLE,
            "created_at": now,
            "updated_at": now,
            "source": "seed",
        })
    try:
        products_collection(repo).update_many(
            {"$or": [{"list_id": {"$exists": False}}, {"list_id": None}, {"list_id": ""}]},
            {"$set": {"list_id": CYBER_LIST_ID}},
        )
    except Exception as exc:
        print(f"cyber-day: backfill list_id: {exc}", flush=True)
    if hasattr(repo, "get_app_setting") and not repo.get_app_setting(ACTIVE_LIST_SETTING):
        first = coll.find_one({}, sort=[("created_at", 1), ("slug", 1)]) or {}
        set_active_list(repo, str(first.get("slug") or CYBER_LIST_ID))
    active = resolve_list_id(repo)
    return {"ok": True, "list_id": active}


def list_meta_view(doc: dict[str, Any], *, products_count: int = 0, run: dict[str, Any] | None = None) -> dict[str, Any]:
    slug = str(doc.get("slug") or doc.get("list_id") or "")
    progress = progress_view(run or default_run(slug), product_total=products_count) if run is not None else None
    return {
        "slug": slug,
        "list_id": slug,
        "name": doc.get("name") or doc.get("title") or slug,
        "title": doc.get("title") or doc.get("name") or slug,
        "products_count": products_count,
        "source": doc.get("source"),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
        "run": progress,
    }


def list_all_lists(repo: Any) -> list[dict[str, Any]]:
    ensure_default_list(repo)
    rows = list(lists_collection(repo).find().sort([("created_at", 1), ("slug", 1)]))
    if not rows:
        rows = [{"slug": CYBER_LIST_ID, "name": CYBER_GROUP_TITLE, "title": CYBER_GROUP_TITLE}]
    out = []
    for doc in rows:
        slug = str(doc.get("slug") or "")
        if not slug:
            continue
        total = products_count(repo, slug)
        run = load_run(repo, slug)
        out.append(list_meta_view(doc, products_count=total, run=run))
    return out


def get_list_meta(repo: Any, list_id: str | None = None) -> dict[str, Any] | None:
    lid = resolve_list_id(repo, list_id)
    ensure_default_list(repo)
    doc = lists_collection(repo).find_one({"slug": lid})
    if not doc:
        return None
    return list_meta_view(doc, products_count=products_count(repo, lid), run=load_run(repo, lid))


def create_list(
    repo: Any,
    *,
    name: str,
    slug: str | None = None,
    copy_from: str | None = None,
    use_seed: bool = False,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Crea una lista independiente (estado/progreso propios)."""
    ensure_default_list(repo)
    title = (name or "").strip() or (slug or "").strip()
    lid = slugify_list(slug or title)
    if not lid:
        raise CyberDayError("Slug de lista inválido.")
    if lists_collection(repo).find_one({"slug": lid}):
        raise CyberDayError(f"Ya existe la lista «{lid}».")
    now = _now()
    source = "empty"
    lists_collection(repo).insert_one({
        "slug": lid,
        "name": title or lid,
        "title": title or lid,
        "created_at": now,
        "updated_at": now,
        "source": source,
    })
    save_run(repo, default_run(lid), list_id=lid)
    imported = 0
    if items:
        result = import_products(repo, items, source="create-import", list_id=lid)
        imported = int(result.get("imported") or 0)
        source = "import"
    elif copy_from:
        src_id = resolve_list_id(repo, copy_from)
        src_rows = list_products(repo, src_id)
        if not src_rows:
            raise CyberDayError(f"La lista origen «{src_id}» está vacía.")
        payload = [
            normalize_import_row(
                {"n": r.get("n"), "query": r.get("query") or r.get("name"), "category": r.get("category")},
                index,
            )
            for index, r in enumerate(src_rows)
        ]
        payload = [row for row in payload if row]
        result = import_products(repo, payload, source=f"copy:{src_id}", list_id=lid)
        imported = int(result.get("imported") or 0)
        source = f"copy:{src_id}"
    elif use_seed:
        seed_items = load_seed_items()
        if not seed_items:
            raise CyberDayError("Seed JSON ausente o vacío.")
        result = import_products(repo, seed_items, source=f"seed:{lid}", list_id=lid)
        imported = int(result.get("imported") or 0)
        source = f"seed:{lid}"
    lists_collection(repo).update_one({"slug": lid}, {"$set": {"source": source, "updated_at": _now()}})
    set_active_list(repo, lid)
    return {
        "ok": True,
        "list": get_list_meta(repo, lid),
        "imported": imported,
        "lists": list_all_lists(repo),
        **status_payload(repo, list_id=lid, enrich_missing=False),
    }


def delete_list(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    """Elimina meta, queries y estado de una lista. Bloqueado si está en curso."""
    ensure_default_list(repo)
    lid = resolve_list_id(repo, list_id)
    meta = lists_collection(repo).find_one({"slug": lid})
    if not meta:
        raise CyberDayError(f"No existe la lista «{lid}».")
    if lists_collection(repo).count_documents({}) <= 1:
        raise CyberDayError("No podés eliminar la única lista. Creá otra antes.")
    run = load_run(repo, lid)
    if run.get("status") in {"running", "paused"}:
        raise CyberDayError("Pará la lista antes de eliminarla.")
    clear_products(repo, lid)
    lists_collection(repo).delete_one({"slug": lid})
    try:
        if hasattr(repo, "app_settings"):
            repo.app_settings.delete_one({"_id": run_setting_key(lid)})
            if lid == CYBER_LIST_ID:
                repo.app_settings.delete_one({"_id": RUN_SETTING})
    except Exception as exc:
        print(f"cyber-day: delete run setting: {exc}", flush=True)
    remaining = list(
        lists_collection(repo).find().sort([("created_at", 1), ("slug", 1)])
    )
    next_id = str((remaining[0] or {}).get("slug") or CYBER_LIST_ID) if remaining else CYBER_LIST_ID
    active = None
    if hasattr(repo, "get_app_setting"):
        active_doc = repo.get_app_setting(ACTIVE_LIST_SETTING) or {}
        if isinstance(active_doc, dict):
            active = str(active_doc.get("list_id") or active_doc.get("slug") or "").strip()
        elif isinstance(active_doc, str):
            active = active_doc.strip()
    if not active or active == lid:
        set_active_list(repo, next_id)
    else:
        next_id = active
    ensure_default_list(repo)
    payload = status_payload(repo, list_id=next_id, enrich_missing=False)
    payload["deleted"] = lid
    payload["message"] = f"Lista «{lid}» eliminada."
    return payload


def list_products(repo: Any, list_id: str | None = None) -> list[dict[str, Any]]:
    lid = resolve_list_id(repo, list_id)
    rows = list(
        products_collection(repo)
        .find(_products_filter(lid))
        .sort([("order", 1), ("_id", 1)])
    )
    for row in rows:
        row["id"] = str(row.get("_id"))
        row.pop("_id", None)
        if not row.get("list_id"):
            row["list_id"] = lid
    return rows


def product_row_view(row: dict[str, Any]) -> dict[str, Any]:
    """Fila JSON-safe para la tabla admin (sin datetime ni firmas pesadas)."""
    derived = stats_from_signatures(row.get("last_matches") if isinstance(row.get("last_matches"), dict) else {})
    stores = row.get("stores_scraped")
    if stores is None:
        stores = derived.get("stores_scraped") or 0
    max_normal = _as_int(row.get("max_price_normal"))
    if max_normal is None:
        max_normal = derived.get("max_price_normal")
    min_normal = _as_int(row.get("min_price_normal"))
    if min_normal is None:
        min_normal = derived.get("min_price_normal")
    max_offer = _as_int(row.get("max_offer_price"))
    if max_offer is None:
        max_offer = derived.get("max_offer_price")
    best_url = str(row.get("best_offer_url") or "").strip() or derived.get("best_offer_url")
    best_store = str(row.get("best_store") or "").strip() or derived.get("best_store")
    if isinstance(best_store, str):
        best_store = best_store.strip() or None
    else:
        best_store = None
    last_price = _as_int(row.get("last_price"))
    if last_price is None:
        last_price = derived.get("last_price")
    last_normal = _as_int(row.get("last_price_normal"))
    if last_normal is None:
        last_normal = derived.get("last_price_normal")
    prev_best = _as_int(row.get("prev_best_price"))
    last_delta = row.get("last_delta_direction")
    if last_delta not in ("up", "down"):
        last_delta = None
    try:
        delta_streak = int(row.get("delta_streak") or 0)
    except (TypeError, ValueError):
        delta_streak = 0
    best_store_title = None
    if best_store:
        from retail.store_display import public_store_label

        best_store_title = public_store_label(best_store)
    return {
        "id": str(row.get("id") or row.get("_id") or ""),
        "n": row.get("n"),
        "order": row.get("order"),
        "query": row.get("query") or row.get("name") or "",
        "name": row.get("name") or row.get("query") or "",
        "category": row.get("category") or "",
        "last_match_count": int(row.get("last_match_count") or 0),
        "last_price": last_price,
        "prev_best_price": prev_best,
        "last_delta_direction": last_delta,
        "delta_streak": delta_streak,
        "price_direction": price_direction(
            last_price,
            prev_best,
            last_delta_direction=last_delta,
            delta_streak=delta_streak,
        ),
        "last_price_normal": last_normal,
        "stores_scraped": int(stores or 0),
        "max_price_normal": max_normal,
        "min_price_normal": min_normal,
        "max_offer_price": max_offer,
        "best_offer_url": best_url or None,
        "best_store": best_store,
        "best_store_title": best_store_title,
        "last_error": row.get("last_error"),
        "resolved": bool(row.get("resolved")),
        "last_observed_at": _iso(row.get("last_observed_at")),
        "list_id": row.get("list_id") or CYBER_LIST_ID,
    }


def catalog_matches_for_query(repo: Any, query: str) -> list[dict[str, Any]]:
    """Solo catálogo Mongo (rápido). No toca heartbeat ni scrapea tiendas."""
    query = (query or "").strip()
    if not query:
        return []
    seen: dict[str, dict[str, Any]] = {}
    try:
        for doc in repo.find_by_query(query, limit=max(TOP_MATCHES * 3, 20)):
            key = match_key(str(doc.get("store") or ""), str(doc.get("product_id") or ""))
            if key != ":":
                seen[key] = doc
    except Exception as exc:
        print(f"cyber-day: catalog find_by_query falló ({query}): {exc}", flush=True)
    return _rank_matches(list(seen.values()), TOP_MATCHES)


def enrich_row_from_catalog(repo: Any, row: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
    """Rellena matches/precio desde catálogo si la fila aún no tiene observación."""
    if int(row.get("last_match_count") or 0) > 0 and row.get("last_price") is not None:
        return product_row_view(row)
    query = str(row.get("query") or row.get("name") or "").strip()
    matches = catalog_matches_for_query(repo, query)
    if not matches:
        return product_row_view(row)
    sigs, _changes, summary = detect_changes(None, matches, query=query)
    now = _now()
    new_price = summary.get("last_price") if summary else None
    patch = {
        "last_matches": sigs,
        "last_match_count": len(sigs),
        **_summary_patch(summary),
        **_prev_best_price_patch(row, new_price),
        "last_observed_at": now,
        "last_error": None,
        "resolved": True,
        "updated_at": now,
    }
    if persist and row.get("id"):
        try:
            from bson import ObjectId

            products_collection(repo).update_one(
                {"_id": ObjectId(str(row["id"]))},
                {"$set": patch},
            )
        except Exception:
            try:
                products_collection(repo).update_one(
                    {"n": row.get("n"), "query": query},
                    {"$set": patch},
                )
            except Exception as exc:
                print(f"cyber-day: enrich persist falló ({query}): {exc}", flush=True)
    merged = {**row, **patch}
    return product_row_view(merged)


def _products_filter(list_id: str) -> dict[str, Any]:
    """Filtro por lista; la oficial también incluye filas huérfanas sin list_id."""
    if list_id == CYBER_LIST_ID:
        return {
            "$or": [
                {"list_id": list_id},
                {"list_id": {"$exists": False}},
                {"list_id": None},
                {"list_id": ""},
            ]
        }
    return {"list_id": list_id}


def products_count(repo: Any, list_id: str | None = None) -> int:
    lid = resolve_list_id(repo, list_id)
    return int(products_collection(repo).count_documents(_products_filter(lid)))


def clear_products(repo: Any, list_id: str | None = None) -> None:
    lid = resolve_list_id(repo, list_id)
    products_collection(repo).delete_many(_products_filter(lid))


def _find_item_by_n(repo: Any, n: int, list_id: str) -> dict[str, Any] | None:
    """Busca ítem por `n`; si no, por posición (order / índice 1-based)."""
    coll = products_collection(repo)
    filt = _products_filter(list_id)
    item = coll.find_one({**filt, "n": int(n)})
    if item is not None:
        return item
    return next(
        coll.find(filt).sort([("order", 1), ("_id", 1)]).skip(max(0, int(n) - 1)).limit(1),
        None,
    )


def update_item(
    repo: Any,
    n: int,
    *,
    query: str | None = None,
    category: str | None = None,
    list_id: str | None = None,
    enrich: bool = True,
) -> dict[str, Any]:
    """Actualiza query/categoría de una fila. Permite hacerlo con el loop running.

    Al cambiar la query limpia matches/precios; opcionalmente re-enriquece desde
    catálogo. El worker lee la query fresca en la próxima pasada de ese ítem.
    """
    lid = resolve_list_id(repo, list_id)
    try:
        index = int(n)
    except (TypeError, ValueError) as exc:
        raise CyberDayError("n inválido.") from exc
    if index < 1:
        raise CyberDayError("n inválido.")
    item = _find_item_by_n(repo, index, lid)
    if item is None:
        raise CyberDayError(f"No hay ítem #{index} en la lista.")

    patch: dict[str, Any] = {"updated_at": _now(), "list_id": lid}
    query_changed = False
    if query is not None:
        clean = str(query).strip()
        if not clean:
            raise CyberDayError("La query no puede estar vacía.")
        prev = str(item.get("query") or item.get("name") or "").strip()
        if clean != prev:
            query_changed = True
        patch["query"] = clean
        patch["name"] = clean
    if category is not None:
        patch["category"] = str(category).strip()
    if query is None and category is None:
        raise CyberDayError("Indicá query o category para actualizar.")

    if query_changed:
        patch.update({
            "last_matches": {},
            "last_match_count": 0,
            "last_price": None,
            "prev_best_price": None,
            "last_delta_direction": None,
            "delta_streak": 0,
            "last_price_normal": None,
            "last_signature": None,
            "stores_scraped": 0,
            "max_price_normal": None,
            "min_price_normal": None,
            "max_offer_price": None,
            "best_offer_url": None,
            "best_store": None,
            "last_observed_at": None,
            "last_error": None,
            "resolved": False,
        })

    products_collection(repo).update_one({"_id": item["_id"]}, {"$set": patch})
    fresh = products_collection(repo).find_one({"_id": item["_id"]}) or {**item, **patch}
    fresh["id"] = str(fresh.get("_id") or item["_id"])
    fresh.pop("_id", None)
    if query_changed and enrich:
        view = enrich_row_from_catalog(repo, fresh, persist=True)
    else:
        view = product_row_view(fresh)
    payload = status_payload(repo, list_id=lid, enrich_missing=False)
    payload["updated"] = view
    payload["message"] = "Query actualizada" if query is not None else "Ítem actualizado"
    return payload


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


def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deja una fila por query (prioridad: n más bajo, luego con más matches)."""
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        query = str(item.get("query") or item.get("name") or "").strip()
        if not query:
            continue
        key = query.casefold()
        current = best.get(key)
        if current is None:
            best[key] = item
            continue
        cur_n = int(current.get("n") or 10**9)
        new_n = int(item.get("n") or 10**9)
        cur_matches = int(current.get("last_match_count") or 0)
        new_matches = int(item.get("last_match_count") or 0)
        if new_n < cur_n or (new_n == cur_n and new_matches > cur_matches):
            # Conserva firmas/matches del más completo.
            merged = {**item}
            if not merged.get("last_matches") and current.get("last_matches"):
                merged["last_matches"] = current["last_matches"]
                merged["last_match_count"] = current.get("last_match_count")
                merged["last_price"] = current.get("last_price")
                merged["last_signature"] = current.get("last_signature")
            best[key] = merged
        elif current.get("last_matches") is None and item.get("last_matches"):
            best[key] = {**current, **{k: item[k] for k in (
                "last_matches", "last_match_count", "last_price",
                "last_price_normal", "last_signature", "last_observed_at",
            ) if k in item}}
    out = sorted(
        best.values(),
        key=lambda row: (int(row.get("n") or 10**9), str(row.get("query") or "")),
    )
    for index, item in enumerate(out):
        item["order"] = index
        item["n"] = index + 1
        item["name"] = item.get("query") or item.get("name")
    return out


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
    return dedupe_items(out)


def load_seed_items(path: Path | None = None) -> list[dict[str, Any]]:
    seed = path or SEED_PATH
    if not seed.is_file():
        return []
    return parse_products_payload(seed.read_text(encoding="utf-8"), filename=seed.name)


def import_products(
    repo: Any,
    items: list[dict[str, Any]],
    *,
    source: str = "import",
    list_id: str | None = None,
) -> dict[str, Any]:
    """Reemplaza las queries de la lista indicada; conserva slug/nombre."""
    lid = resolve_list_id(repo, list_id)
    ensure_default_list(repo)
    existing_meta = lists_collection(repo).find_one({"slug": lid})
    if not existing_meta:
        lists_collection(repo).insert_one({
            "slug": lid,
            "name": lid,
            "title": lid,
            "created_at": _now(),
            "updated_at": _now(),
            "source": source,
        })
        existing_meta = {"slug": lid, "name": lid, "title": lid}
    unique = dedupe_items(items)
    if not unique:
        raise CyberDayError("La lista importada está vacía.")
    run = load_run(repo, lid)
    if run.get("status") in {"running", "paused"}:
        # Reimport detiene el loop (mismo criterio que reiniciar progreso).
        run["status"] = "stopped"
    clear_products(repo, lid)
    now = _now()
    docs = []
    for item in unique:
        docs.append({**item, "source": source, "list_id": lid, "created_at": now, "updated_at": now})
    products_collection(repo).insert_many(docs)
    run["total"] = len(docs)
    run["cursor"] = 0
    run["processed"] = 0
    run["lap"] = 0
    run["source_note"] = f"Lista {lid}: {len(docs)} queries ({source})."
    run["list_id"] = lid
    run["group_id"] = lid if lid != CYBER_LIST_ID else CYBER_GROUP_ID
    run["last_error"] = None
    save_run(repo, run, list_id=lid)
    # No pisa name/title: reimport actualiza contenido, no identidad.
    lists_collection(repo).update_one(
        {"slug": lid},
        {"$set": {"updated_at": now, "source": source}},
    )
    set_active_list(repo, lid)
    payload = status_payload(repo, list_id=lid, enrich_missing=False)
    payload.update({
        "ok": True,
        "imported": len(docs),
        "total": len(docs),
        "source": source,
        "list_id": lid,
        "list_name": existing_meta.get("name") or existing_meta.get("title") or lid,
        "deduped": max(0, len(items) - len(unique)),
        "message": f"Lista «{existing_meta.get('name') or lid}» actualizada: {len(docs)} queries.",
    })
    return payload


def repair_duplicates(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    """Si hay queries duplicadas (p. ej. seed×2 → 200), deja únicos por lista."""
    lid = resolve_list_id(repo, list_id)
    rows = list_products(repo, lid)
    unique = dedupe_items(rows)
    if len(unique) == len(rows):
        run = load_run(repo, lid)
        if int(run.get("total") or 0) != len(rows):
            run["total"] = len(rows)
            save_run(repo, run, list_id=lid)
        return {"repaired": False, "total": len(rows), "list_id": lid}
    before = len(rows)
    clear_products(repo, lid)
    now = _now()
    docs = [{**item, "list_id": lid, "updated_at": now} for item in unique]
    if docs:
        products_collection(repo).insert_many(docs)
    run = load_run(repo, lid)
    run["total"] = len(docs)
    run["cursor"] = min(int(run.get("cursor") or 0), len(docs))
    run["processed"] = min(int(run.get("processed") or 0), len(docs))
    run["source_note"] = f"Lista {lid}: {len(docs)} queries (dedupe {before}→{len(docs)})."
    save_run(repo, run, list_id=lid)
    return {"repaired": True, "before": before, "total": len(docs), "list_id": lid}


_EXPORT_FIELDS = (
    "n",
    "query",
    "category",
    "last_match_count",
    "last_price",
    "best_store",
    "best_store_title",
    "stores_scraped",
    "max_price_normal",
    "min_price_normal",
    "max_offer_price",
    "best_offer_url",
)


def export_rows(repo: Any, list_id: str | None = None) -> list[dict[str, Any]]:
    lid = resolve_list_id(repo, list_id)
    repair_duplicates(repo, lid)
    rows = []
    for item in list_products(repo, lid):
        view = product_row_view(item)
        rows.append({key: view.get(key) for key in _EXPORT_FIELDS})
    return rows


def export_csv(repo: Any, list_id: str | None = None) -> str:
    rows = export_rows(repo, list_id)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(_EXPORT_FIELDS),
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()


def export_json(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id)
    meta = get_list_meta(repo, lid) or {"name": lid, "title": lid}
    rows = export_rows(repo, lid)
    return {
        "id": lid,
        "title": meta.get("title") or meta.get("name") or lid,
        "items": rows,
    }


def cyber_store_ids() -> list[str]:
    from retail.registry import STORE_GROUP, list_stores

    wanted = {
        store_id
        for store_id, group in STORE_GROUP.items()
        if (group or "").lower() in CYBER_STORE_GROUPS
    }
    return [spec.id for spec in list_stores() if spec.id in wanted]


def ensure_cyber_category(repo: Any) -> dict[str, Any]:
    """Registra el grupo de corridas `cyber_junio2026` en `store_categories`."""
    ensure_seed(repo)
    now = _now()
    stores = cyber_store_ids()
    doc = {
        "id": CYBER_GROUP_ID,
        "title": CYBER_GROUP_TITLE,
        "kind": "query_list",
        "query_list": True,
        "list_id": CYBER_LIST_ID,
        "store_ids": stores,
        "sort_order": 0,
        "updated_at": now,
    }
    coll = getattr(repo, "store_categories", None)
    if coll is None:
        return {"ok": False, "detail": "sin store_categories"}
    coll.update_one({"id": CYBER_GROUP_ID}, {"$set": doc}, upsert=True)
    return {"ok": True, "id": CYBER_GROUP_ID, "store_count": len(stores), "queries": products_count(repo)}


def ensure_seed(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    """Si la lista está vacía, carga el seed (solo default o cuando se pide).

    Si ya hay filas, repara duplicados (seed concurrente → 200).
    """
    ensure_default_list(repo)
    lid = resolve_list_id(repo, list_id)
    total = products_count(repo, lid)
    if total > 0:
        repair = repair_duplicates(repo, lid)
        return {
            "seeded": False,
            "total": int(repair.get("total") or products_count(repo, lid)),
            "list_id": lid,
            "repaired": bool(repair.get("repaired")),
        }
    # Solo auto-siembra la lista oficial; listas nuevas quedan vacías hasta import/seed.
    if lid != CYBER_LIST_ID:
        return {"seeded": False, "total": 0, "list_id": lid, "detail": "Lista vacía (importá o copiá seed)."}
    lock_id = "cyber_day_seed_lock"
    claimed = False
    try:
        repo.app_settings.insert_one({"_id": lock_id, "at": _now(), "host": socket.gethostname()})
        claimed = True
    except Exception:
        time.sleep(0.6)
        total = products_count(repo, lid)
        if total > 0:
            repair = repair_duplicates(repo, lid)
            return {
                "seeded": False,
                "total": int(repair.get("total") or total),
                "list_id": lid,
                "repaired": bool(repair.get("repaired")),
            }
    try:
        if products_count(repo, lid) > 0:
            repair = repair_duplicates(repo, lid)
            return {
                "seeded": False,
                "total": int(repair.get("total") or products_count(repo, lid)),
                "list_id": lid,
                "repaired": bool(repair.get("repaired")),
            }
        items = load_seed_items()
        if not items:
            return {"seeded": False, "total": 0, "list_id": lid, "detail": "Seed JSON ausente o vacío."}
        result = import_products(repo, items, source=f"seed:{lid}", list_id=lid)
        return {"seeded": True, "list_id": lid, **result}
    finally:
        if claimed:
            try:
                repo.app_settings.delete_one({"_id": lock_id})
            except Exception:
                pass


def catalog_products_for_cyber(repo: Any) -> list[dict[str, Any]]:
    """Queries Cyber como ítems de catálogo para `retail batch --grupo cyber_junio2026`."""
    ensure_seed(repo)
    rows = []
    for item in list_products(repo):
        query = str(item.get("query") or item.get("name") or "").strip()
        if not query:
            continue
        n = int(item.get("n") or item.get("order") or 0) or (len(rows) + 1)
        rows.append({
            "id": f"{CYBER_LIST_ID}-{n:03d}",
            "query": query,
            "enabled": True,
            "category": item.get("category") or "",
            "group": CYBER_GROUP_ID,
            "list_id": CYBER_LIST_ID,
        })
    return rows


def restart_run(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    """Reinicia desde la query #1 (igual que Iniciar)."""
    lid = resolve_list_id(repo, list_id)
    run = load_run(repo, lid)
    if run.get("status") == "running":
        run["status"] = "stopped"
        save_run(repo, run, list_id=lid)
    return start_run(repo, list_id=lid)


def as_cron_group(repo: Any) -> dict[str, Any]:
    """Fila de `/cron` para el grupo cyber_junio2026 (progreso del worker)."""
    ensure_cyber_category(repo)
    # Sin enrich: el poll de /cron es cada 3s; el worker ya completa precios.
    payload = status_payload(repo, list_id=CYBER_LIST_ID, enrich_missing=False)
    run = payload.get("run") or {}
    status = str(run.get("status") or "idle")
    if status == "running":
        group_status = "running"
    elif status == "paused":
        group_status = "paused"
    elif status == "stopped":
        group_status = "stopped" if int(run.get("processed") or 0) > 0 else "idle"
    else:
        group_status = "idle"
    processed = int(run.get("processed") or 0)
    total = int(run.get("total") or payload.get("products_count") or products_count(repo, CYBER_LIST_ID) or 0)
    percent = float(run.get("percent") or 0)
    can_continue = group_status in {"stopped", "partial", "failed"} and processed > 0
    # store_count = queries de la lista (no tiendas del catálogo).
    return {
        "id": CYBER_GROUP_ID,
        "title": CYBER_GROUP_TITLE,
        "store_count": total,
        "query_count": total,
        "query_list": True,
        "list_id": CYBER_LIST_ID,
        "kind": "query_list",
        "status": group_status,
        "can_continue": can_continue,
        "progress": {
            "phase": "products" if group_status == "running" else group_status,
            "label": (
                f"Vuelta {run.get('lap') or '—'} · {percent}% "
                f"({processed}/{total})"
                + (
                    f" · {run.get('lap_elapsed_seconds')}s"
                    if run.get("lap_elapsed_seconds") is not None
                    else ""
                )
            ),
            "processed": processed,
            "items": total,
            "percent": percent,
            "lap": run.get("lap"),
            "lap_elapsed_seconds": run.get("lap_elapsed_seconds"),
            "lap_eta_seconds": run.get("lap_eta_seconds"),
            "worker_healthy": run.get("worker_healthy"),
            "heartbeat_at": run.get("heartbeat_at"),
        } if group_status in {"running", "paused", "stopped"} else None,
        "last_run": {
            "status": group_status,
            "processed": processed,
            "items": total,
            "percent": percent,
            "lap": run.get("lap"),
            "last_error": run.get("last_error"),
            "last_change": run.get("last_change"),
            "notified_count": run.get("notified_count"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("last_lap_finished_at"),
            "budget_exhausted": False,
        },
        "schedule": None,
    }


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
        "last_change": _json_safe(run.get("last_change")),
        "notified_count": int(run.get("notified_count") or 0),
        "worker": run.get("worker"),
        "worker_healthy": healthy,
        "heartbeat_at": _iso(heartbeat),
        "source_note": run.get("source_note"),
        "list_id": run.get("list_id"),
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


def _json_safe(value: Any) -> Any:
    """Evita 500 de FastAPI por datetime/ObjectId anidados en last_change."""
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def status_payload(
    repo: Any,
    *,
    list_id: str | None = None,
    enrich_missing: bool = False,
) -> dict[str, Any]:
    """Estado + lista JSON-safe. Rápido por defecto (sin enrich) para no colgar la UI."""
    lid = resolve_list_id(repo, list_id)
    try:
        ensure_seed(repo, lid)
    except Exception as exc:
        print(f"cyber-day: ensure_seed en status: {exc}", flush=True)
    run = load_run(repo, lid)
    total = products_count(repo, lid)
    run["total"] = total
    progress = progress_view(run, product_total=total)
    raw_rows = list_products(repo, lid)
    products: list[dict[str, Any]] = []
    enrich_budget = 12 if enrich_missing else 0
    for row in raw_rows:
        needs = int(row.get("last_match_count") or 0) <= 0 or row.get("last_price") is None
        if needs and enrich_budget > 0:
            products.append(enrich_row_from_catalog(repo, row, persist=True))
            enrich_budget -= 1
        else:
            products.append(product_row_view(row))
    meta = get_list_meta(repo, lid)
    return {
        "ok": True,
        "list_id": lid,
        "list": meta,
        "lists": list_all_lists(repo),
        "run": progress,
        "products": products,
        "products_preview": products,
        "products_count": total or len(products),
    }


def start_run(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id)
    ensure_seed(repo, lid)
    total = products_count(repo, lid)
    if total <= 0:
        raise CyberDayError("No hay queries en esta lista. Importá CSV/JSON o copiá el seed.")
    run = load_run(repo, lid)
    if run.get("status") == "running":
        # Idempotente: /cron «Iniciar ahora» no debe 400 si el worker ya corre.
        set_active_list(repo, lid)
        return status_payload(repo, list_id=lid, enrich_missing=False)
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
        "list_id": lid,
    })
    save_run(repo, run, list_id=lid)
    set_active_list(repo, lid)
    return status_payload(repo, list_id=lid, enrich_missing=False)


def stop_run(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id)
    run = load_run(repo, lid)
    if run.get("status") not in {"running", "paused"}:
        raise CyberDayError("Esta lista no está en curso.")
    run["status"] = "stopped"
    save_run(repo, run, list_id=lid)
    return status_payload(repo, list_id=lid, enrich_missing=False)


def continue_run(repo: Any, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id)
    ensure_seed(repo, lid)
    total = products_count(repo, lid)
    if total <= 0:
        raise CyberDayError("No hay queries en esta lista. Importá CSV/JSON o copiá el seed.")
    run = load_run(repo, lid)
    if run.get("status") == "running":
        raise CyberDayError("Esta lista ya está en curso.")
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
        "list_id": lid,
    })
    save_run(repo, run, list_id=lid)
    set_active_list(repo, lid)
    return status_payload(repo, list_id=lid, enrich_missing=False)


def touch_worker(repo: Any, list_id: str | None = None) -> None:
    lid = resolve_list_id(repo, list_id)
    run = load_run(repo, lid)
    run["heartbeat_at"] = _now()
    run["worker"] = socket.gethostname()
    save_run(repo, run, list_id=lid)


def _money_clp(value: Any) -> str:
    n = _as_int(value)
    if n is None:
        return "—"
    return f"${n:,}".replace(",", ".")


def _price_move_label(previous: Any, current: Any) -> str:
    old = _as_int(previous)
    new = _as_int(current)
    if old is None or new is None or old == new:
        return "cambió"
    return "bajó" if new < old else "subió"


def query_best_price_change(
    item: dict[str, Any] | None,
    matches: list[dict[str, Any]],
    summary: dict[str, Any] | None,
    *,
    query: str,
) -> dict[str, Any] | None:
    """Si el mejor precio de la query subió o bajó, arma el payload de aviso."""
    old_best = _as_int((item or {}).get("last_price"))
    new_best = _as_int((summary or {}).get("last_price"))
    if old_best is None or new_best is None or old_best == new_best:
        return None
    best_offer: dict[str, Any] | None = None
    for offer in matches or []:
        price = _offer_price(offer)
        if price == new_best:
            best_offer = offer
            break
    store = str((best_offer or {}).get("store") or "")
    product_id = str((best_offer or {}).get("product_id") or "")
    name = str((best_offer or {}).get("name") or query or "Producto").strip() or "Producto"
    direction = _price_move_label(old_best, new_best)
    return {
        "store": store or "cyber",
        "product_id": product_id or "best",
        "name": name,
        "url": (best_offer or {}).get("url") or (summary or {}).get("best_offer_url")
        or ficha_path(store, product_id),
        "image_url": (best_offer or {}).get("image_url") or "",
        "previous_price": old_best,
        "price": new_best,
        "price_normal": _as_int((best_offer or {}).get("price_normal")),
        "query": query,
        "kind": "best_price",
        "message": (
            f"Cyber Day ({query}): mejor precio {direction} "
            f"{_money_clp(old_best)} → {_money_clp(new_best)}"
        ),
    }


def _offer_change_covers_best(changes: list[dict[str, Any]], best_change: dict[str, Any]) -> bool:
    """True si ya avisamos el mismo match que es el nuevo mejor precio."""
    store = str(best_change.get("store") or "")
    product_id = str(best_change.get("product_id") or "")
    price = _as_int(best_change.get("price"))
    if not store or not product_id or price is None:
        return False
    for change in changes:
        if (
            str(change.get("store") or "") == store
            and str(change.get("product_id") or "") == product_id
            and _as_int(change.get("price")) == price
        ):
            return True
    return False


def _cyber_product_entity_key(repo: Any, store: str, product_id: str) -> str:
    """Misma clave que price_alerts/claim_price_alert_send para no duplicar envíos."""
    fallback = f"product:{store}:{product_id}" if store and product_id else "cyber:unknown"
    collection = getattr(repo, "collection", None)
    if collection is None or not store or not product_id:
        return fallback
    try:
        product = collection.find_one(
            {"store": store, "product_id": product_id},
            {"compare_code": 1},
        ) or {}
    except Exception:
        return fallback
    return str(product.get("compare_code") or fallback)


def _cyber_notification_users(repo: Any) -> list[dict[str, Any]]:
    """Cuentas aprobadas con canales personales (Telegram/push), no solo admins."""
    if hasattr(repo, "list_notification_users"):
        try:
            return list(repo.list_notification_users() or [])
        except Exception as exc:
            print(f"cyber-day: list_notification_users falló: {exc}", flush=True)
    users = getattr(repo, "users", None)
    if users is None:
        return []
    try:
        return list(users.find({"status": "approved"}))
    except Exception as exc:
        print(f"cyber-day: lectura de usuarios falló: {exc}", flush=True)
        return []


def notify_cyber_change(repo: Any, change: dict[str, Any]) -> int:
    """Telegram admin + Telegram/push a todas las cuentas suscritas (subidas y bajadas)."""
    sent = 0
    store = str(change.get("store") or "")
    product_id = str(change.get("product_id") or "")
    price = int(change.get("price") or 0)
    previous = _as_int(change.get("previous_price"))
    admin_entity = f"cyber:{store}:{product_id}"
    entity_key = _cyber_product_entity_key(repo, store, product_id)
    direction = _price_move_label(previous, price)
    from retail.price_alerts import notify_price_changes, price_change_message

    # Seguidores del producto (email/telegram/push vía price_alerts).
    try:
        sent += int(notify_price_changes(repo, [change]) or 0)
    except Exception as exc:
        print(f"cyber-day: notify followers falló: {exc}", flush=True)

    users = _cyber_notification_users(repo)
    try:
        from retail.batch.alerts import bind_user_chats, _telegram_text, send_to_user

        # Excluye chats personales del broadcast admin (evita doble Telegram).
        bind_user_chats(repo, users)

        claimed = True
        if hasattr(repo, "claim_user_notification_send"):
            claimed = repo.claim_user_notification_send("cyber_day", "telegram", admin_entity, price)
        _, body = price_change_message(change)
        query = str(change.get("query") or "")
        prefix = f"Cyber Day · {query}\n\n" if query else "Cyber Day · cambio de precio\n\n"
        text = prefix + body
        image_url = change.get("image_url")
        if claimed and _telegram_text(text, image_url=image_url):
            sent += 1

        # Telegram personal: toda cuenta aprobada con Telegram vinculado.
        for user in users:
            user_id = str(user.get("_id") or user.get("id") or "")
            if not user_id:
                continue
            prefs = user.get("notification_preferences") or {}
            channels = prefs.get("channels") or []
            # Sin preferencias explícitas: si tiene chat, avisar (igual que “vinculó Telegram”).
            if channels and "telegram" not in channels:
                continue
            if hasattr(repo, "claim_user_notification_send"):
                if not repo.claim_user_notification_send(user_id, "telegram", entity_key, price):
                    continue
            if send_to_user(user, text, image_url=image_url):
                sent += 1
    except Exception as exc:
        print(f"cyber-day: telegram falló: {exc}", flush=True)

    try:
        from retail.batch.rules import load_rules
        from retail.web_push import send_user_push

        system_channels = set(load_rules().get("channels") or [])
        if "push" not in system_channels:
            print("cyber-day: push omitido (canal push desactivado en reglas)", flush=True)
            return sent

        from retail.short_links import attach_short_url

        payload = {
            **change,
            "message": change.get("message")
            or (
                f"Cyber Day: {change.get('name')} {direction} "
                f"{_money_clp(previous)} → {_money_clp(price)}"
            ),
        }
        # short_url / ficha in-app: el SW solo abre mismo origen o lnk.*; sin esto el clic va a /siguiendo.
        if store and product_id and store != "cyber" and product_id != "best":
            attach_short_url(payload, repo)
        elif str(change.get("url") or "").startswith("/"):
            payload["short_url"] = str(change["url"]).strip()
        # Push: toda cuenta aprobada con suscripción activa (no solo admin).
        for user in users:
            prefs = user.get("notification_preferences") or {}
            channels = prefs.get("channels") or []
            if channels and "push" not in channels:
                continue
            if not user.get("push_subscriptions"):
                continue
            user_id = str(user.get("_id") or user.get("id") or "")
            if not user_id:
                continue
            if hasattr(repo, "claim_user_notification_send"):
                if not repo.claim_user_notification_send(user_id, "push", entity_key, price):
                    continue
            if send_user_push(user, payload, repo=repo, tag=entity_key):
                sent += 1
    except Exception as exc:
        print(f"cyber-day: push falló: {exc}", flush=True)
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
        price = _offer_price(doc) or 10**12
        normal = _as_int(doc.get("price_normal")) or 0
        discount = max(0, normal - price) if normal > price else 0
        return (-discount, price, str(doc.get("store") or ""), str(doc.get("product_id") or ""))

    ranked = sorted((d for d in docs if _offer_price(d)), key=sort_key)
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


def collect_query_matches(
    repo: Any,
    query: str,
    *,
    list_id: str | None = None,
) -> list[dict[str, Any]]:
    """Catálogo local (+ scrape acotado opcional); top matches rankeados."""
    lid = resolve_list_id(repo, list_id)
    seen: dict[str, dict[str, Any]] = {}
    touch_worker(repo, lid)
    try:
        for doc in repo.find_by_query(query, limit=max(TOP_MATCHES * 3, 20)):
            key = match_key(str(doc.get("store") or ""), str(doc.get("product_id") or ""))
            if key != ":":
                seen[key] = doc
    except Exception as exc:
        print(f"cyber-day: find_by_query falló ({query}): {exc}", flush=True)

    # Por defecto solo DB: el scrape live de todas las tiendas bloqueaba el loop
    # (timeouts Movistar, etc.) y el heartbeat caducaba → «worker sin heartbeat».
    if SEARCH_SOURCE in {"both", "scrape"}:
        try:
            from retail.search import search_products

            touch_worker(repo, lid)
            result = search_products(
                query,
                source="scrape" if SEARCH_SOURCE == "scrape" else "both",
                stores=list(PREFERRED_SCRAPE_STORES),
                preferred_stores=list(PREFERRED_SCRAPE_STORES),
                max_items=SEARCH_MAX_ITEMS,
                delay=0.3,
                timeout=SEARCH_TIMEOUT,
                persist=True,
                persist_meta={"source": "cyber_day", "list_id": lid},
                price_band=True,
                fresh=False,
                background_side_effects=False,
                wait_for_all=False,
                recover_underfilled_db=False,
            )
            for offer in _offer_rows_from_search(result):
                store = str(offer.get("store") or "")
                product_id = str(offer.get("product_id") or "")
                if store and product_id:
                    seen[match_key(store, product_id)] = offer
        except Exception as exc:
            print(f"cyber-day: search_products falló ({query}): {exc}", flush=True)

    touch_worker(repo, lid)
    return _rank_matches(list(seen.values()), TOP_MATCHES)


def refresh_top_matches(
    repo: Any,
    matches: list[dict[str, Any]],
    *,
    list_id: str | None = None,
) -> list[dict[str, Any]]:
    from retail.product_refresh import refresh_product_price

    lid = resolve_list_id(repo, list_id)
    fresh_rows: list[dict[str, Any]] = []
    for offer in matches[:REFRESH_TOP]:
        store = str(offer.get("store") or "")
        product_id = str(offer.get("product_id") or "")
        if not store or not product_id:
            continue
        touch_worker(repo, lid)
        try:
            refresh_product_price(repo, store, product_id)
        except Exception as exc:
            print(f"cyber-day: refresh {store}/{product_id}: {exc}", flush=True)
        detail = repo.product_detail(store, product_id) or offer
        fresh_rows.append(detail)
        boost_catalog_priority(repo, str(detail.get("catalog_id") or ""))
    refreshed_keys = {match_key(str(r.get("store") or ""), str(r.get("product_id") or "")) for r in fresh_rows}
    for offer in matches:
        key = match_key(str(offer.get("store") or ""), str(offer.get("product_id") or ""))
        if key not in refreshed_keys:
            fresh_rows.append(offer)
            boost_catalog_priority(repo, str(offer.get("catalog_id") or ""))
    touch_worker(repo, lid)
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
    for offer in matches:
        store = str(offer.get("store") or "")
        product_id = str(offer.get("product_id") or "")
        if not store or not product_id:
            continue
        price = _offer_price(offer)
        if price is None:
            continue
        price_normal = _as_int(offer.get("price_normal"))
        if price_normal is not None and price_normal <= 0:
            price_normal = None
        price_card = _as_int(offer.get("price_card"))
        sig = offer_signature(price, price_normal, price_card)
        key = match_key(store, product_id)
        current[key] = sig
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
            "url": offer.get("url") or ficha_path(store, product_id),
            "image_url": offer.get("image_url") or "",
            "previous_price": old_price if old_price is not None else price,
            "price": price,
            "price_normal": price_normal,
            "query": query,
            "message": f"Cyber Day ({query}): {old} → {sig}",
        })
    summary = summarize_match_stats(matches) if current else None
    return current, changes, summary


def process_one(repo: Any, *, delay: float = 0.0, list_id: str | None = None) -> dict[str, Any]:
    """Procesa la query del cursor si el run de esa lista está `running`."""
    lid = resolve_list_id(repo, list_id)
    run = load_run(repo, lid)
    if run.get("status") != "running":
        return {
            "ok": True,
            "skipped": True,
            "reason": "not_running",
            "status": run.get("status"),
            "list_id": lid,
        }

    coll = products_collection(repo)
    total = int(coll.count_documents(_products_filter(lid)))
    if total <= 0:
        seeded = ensure_seed(repo, lid)
        total = int(seeded.get("total") or products_count(repo, lid))
        if total <= 0:
            run["status"] = "stopped"
            run["last_error"] = "Lista vacía."
            run["total"] = 0
            save_run(repo, run, list_id=lid)
            return {"ok": False, "detail": "Lista vacía.", "list_id": lid}

    cursor = int(run.get("cursor") or 0)
    if cursor >= total:
        return _finish_lap(repo, run, total, list_id=lid)

    item = next(
        coll.find(_products_filter(lid)).sort([("order", 1), ("_id", 1)]).skip(cursor).limit(1),
        None,
    )
    if item is None:
        return _finish_lap(repo, run, total, list_id=lid)

    query = str(item.get("query") or item.get("name") or "").strip()
    result: dict[str, Any] = {
        "ok": False,
        "query": query,
        "category": item.get("category"),
        "cursor": cursor,
        "lap": run.get("lap"),
        "n": item.get("n"),
        "list_id": lid,
    }
    now = _now()
    notified = 0
    changed = 0
    touch_worker(repo, lid)

    try:
        if not query:
            raise CyberDayError("Query vacía.")
        matches = collect_query_matches(repo, query, list_id=lid)
        fresh = refresh_top_matches(repo, matches, list_id=lid) if matches else []
        tracked = fresh or matches
        current_sigs, changes, summary = detect_changes(
            item.get("last_matches"), tracked, query=query,
        )
        had_history = bool(item.get("last_matches")) or item.get("last_price") is not None
        notify_queue: list[dict[str, Any]] = []
        if had_history:
            # Avisos por match (subidas y bajadas; price_alerts ya dice bajó/subió).
            notify_queue.extend(changes)
            # Mejor precio de la query: también si cambia por un match nuevo
            # (primera firma de esa oferta) o por cambio de quién es el mínimo.
            best_change = query_best_price_change(item, tracked, summary, query=query)
            if best_change and not _offer_change_covers_best(changes, best_change):
                notify_queue.append(best_change)
            for change in notify_queue:
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
                    "list_id": lid,
                    "direction": _price_move_label(
                        change.get("previous_price"), change.get("price"),
                    ),
                }
        if changed:
            run["notified_count"] = int(run.get("notified_count") or 0) + changed

        new_best = summary.get("last_price") if summary else None
        coll.update_one(
            {"_id": item["_id"]},
            {
                "$set": {
                    "query": query,
                    "name": query,
                    "list_id": lid,
                    "resolved": bool(tracked),
                    "last_matches": current_sigs,
                    "last_match_count": len(current_sigs),
                    **_summary_patch(summary),
                    **_prev_best_price_patch(item, new_best),
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

    current = load_run(repo, lid)
    if current.get("status") != "running":
        result["stopped_during"] = True
        return result

    next_cursor = cursor + 1
    run["cursor"] = next_cursor
    run["processed"] = next_cursor
    run["total"] = total
    run["heartbeat_at"] = now
    run["worker"] = socket.gethostname()
    run["list_id"] = lid
    if next_cursor >= total:
        save_run(repo, run, list_id=lid)
        lap_result = _finish_lap(repo, run, total, list_id=lid)
        result["lap_finished"] = True
        result.update(lap_result)
    else:
        save_run(repo, run, list_id=lid)

    if delay > 0:
        time.sleep(delay)
    return result


def _finish_lap(repo: Any, run: dict[str, Any], total: int, *, list_id: str | None = None) -> dict[str, Any]:
    lid = resolve_list_id(repo, list_id or run.get("list_id"))
    now = _now()
    started = run.get("lap_started_at")
    elapsed = None
    if isinstance(started, datetime):
        start = started if started.tzinfo else started.replace(tzinfo=timezone.utc)
        elapsed = max(0, int((now - start).total_seconds()))
    current = load_run(repo, lid)
    if current.get("status") != "running":
        return {"ok": True, "lap_finished": True, "status": current.get("status"), "list_id": lid}
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
        "list_id": lid,
    })
    save_run(repo, run, list_id=lid)
    print(
        f"cyber-day [{lid}] lap {next_lap - 1} done in {elapsed}s; "
        f"starting lap {next_lap} ({total} queries)",
        flush=True,
    )
    return {
        "ok": True,
        "lap_finished": True,
        "last_lap": next_lap - 1,
        "last_lap_elapsed_seconds": elapsed,
        "lap": next_lap,
        "list_id": lid,
    }


def running_list_ids(repo: Any) -> list[str]:
    ensure_default_list(repo)
    ids = []
    for meta in list_all_lists(repo):
        slug = str(meta.get("slug") or "")
        if not slug:
            continue
        if load_run(repo, slug).get("status") == "running":
            ids.append(slug)
    # Compat: si solo existe el run legacy running
    if not ids:
        legacy = load_run(repo, CYBER_LIST_ID)
        if legacy.get("status") == "running":
            ids.append(CYBER_LIST_ID)
    return ids


def worker_loop(repo: Any, *, delay: float = DEFAULT_DELAY, poll_seconds: float = 2.0) -> None:
    ensure_seed(repo, CYBER_LIST_ID)
    while True:
        active = resolve_list_id(repo)
        running = running_list_ids(repo)
        if not running:
            touch_worker(repo, active)
            time.sleep(poll_seconds)
            continue
        for lid in running:
            touch_worker(repo, lid)
            metrics = process_one(repo, delay=delay, list_id=lid)
            if metrics.get("skipped"):
                continue
            if metrics.get("ok"):
                print(
                    f"cyber-day [{lid}] lap={metrics.get('lap')} n={metrics.get('n')} "
                    f"query={metrics.get('query')!r} matches={metrics.get('matches')} "
                    f"changed={metrics.get('changed')} notified={metrics.get('notified')}",
                    flush=True,
                )
            else:
                print(f"cyber-day [{lid}] error: {metrics.get('detail')}", flush=True)
                time.sleep(max(delay, 1.0))
        if not running:
            time.sleep(poll_seconds)


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
