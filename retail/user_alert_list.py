"""Lista Cyber «Alertas usuarios»: sync desde Activar alerta + helpers de fila.

Cada producto seguido vive en ``cyber_day_products`` con ``list_id=alertas_usuarios``.
La identidad de fila es ``compare_code`` (si existe) o ``store:product_id``.
Varios usuarios suman al mismo ítem; al quitar el último se borra la fila.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

USER_ALERTS_LIST_ID = "alertas_usuarios"
USER_ALERTS_TITLE = "Alertas usuarios"
USER_ALERTS_SOURCE = "user_alerts"


def is_user_alerts_list(list_id: str | None) -> bool:
    return str(list_id or "").strip().lower() == USER_ALERTS_LIST_ID


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    if value:
        return str(value)
    return None


def alert_key_for_product(document: dict[str, Any] | None, *, store: str, product_id: str) -> str:
    """Clave estable: compare_code si hay; si no store:product_id."""
    doc = document or {}
    code = str(doc.get("compare_code") or "").strip()
    if code:
        return code
    return f"{store}:{product_id}"


def _anchor_store_product(document: dict[str, Any] | None, *, store: str, product_id: str) -> tuple[str, str]:
    """Evita anclar en Knasta: usa la tienda pública de destino cuando aplica."""
    doc = document or {}
    try:
        from retail.store_display import display_store

        display_id, _title = display_store({**doc, "store": store})
        if display_id and display_id not in {"knasta", "otro", ""}:
            # Si el aviso era knasta#falabella#sku, el product_id de destino suele ir en url/id.
            raw_id = str(product_id or "")
            if "#" in raw_id:
                retail, _, sku = raw_id.partition("#")
                if retail.lower() == display_id.lower() and sku:
                    return display_id, sku
            return display_id, str(product_id)
    except Exception:
        pass
    return str(store), str(product_id)


def _watcher_entry(user: dict[str, Any]) -> dict[str, Any]:
    user_id = str(user.get("id") or user.get("_id") or "").strip()
    email = str(user.get("email") or "").strip()
    name = str(user.get("name") or user.get("display_name") or "").strip()
    return {
        "user_id": user_id,
        "email": email or None,
        "display_name": name or None,
        "added_at": _now(),
    }


def _watcher_label(entry: dict[str, Any] | None) -> str:
    if not entry:
        return ""
    return (
        str(entry.get("display_name") or "").strip()
        or str(entry.get("email") or "").strip()
        or str(entry.get("user_id") or "").strip()
        or "—"
    )


def ensure_user_alerts_list(repo: Any) -> dict[str, Any]:
    """Crea la lista sistema vacía si no existe."""
    from retail.cyber_day import (
        CyberDayError,
        default_run,
        lists_collection,
        products_collection,
        save_run,
    )

    coll = lists_collection(repo)
    now = _now()
    existing = coll.find_one({"slug": USER_ALERTS_LIST_ID})
    if existing:
        # Garantiza flags de sistema.
        coll.update_one(
            {"slug": USER_ALERTS_LIST_ID},
            {"$set": {
                "system": True,
                "source": existing.get("source") or USER_ALERTS_SOURCE,
                "title": existing.get("title") or USER_ALERTS_TITLE,
                "name": existing.get("name") or USER_ALERTS_TITLE,
            }},
        )
        try:
            products_collection(repo).create_index(
                [("list_id", 1), ("alert_key", 1)],
                unique=True,
                name="user_alerts_list_key",
                partialFilterExpression={"list_id": USER_ALERTS_LIST_ID, "alert_key": {"$type": "string"}},
            )
        except Exception:
            pass
        return existing

    coll.insert_one({
        "slug": USER_ALERTS_LIST_ID,
        "name": USER_ALERTS_TITLE,
        "title": USER_ALERTS_TITLE,
        "created_at": now,
        "updated_at": now,
        "source": USER_ALERTS_SOURCE,
        "system": True,
    })
    save_run(repo, default_run(USER_ALERTS_LIST_ID), list_id=USER_ALERTS_LIST_ID)
    try:
        products_collection(repo).create_index(
            [("list_id", 1), ("alert_key", 1)],
            unique=True,
            name="user_alerts_list_key",
            partialFilterExpression={"list_id": USER_ALERTS_LIST_ID, "alert_key": {"$type": "string"}},
        )
    except Exception as exc:
        print(f"user-alerts: index: {exc}", flush=True)
    return coll.find_one({"slug": USER_ALERTS_LIST_ID}) or {
        "slug": USER_ALERTS_LIST_ID,
        "name": USER_ALERTS_TITLE,
        "system": True,
    }


def _next_n(repo: Any) -> int:
    from retail.cyber_day import products_collection

    top = products_collection(repo).find_one(
        {"list_id": USER_ALERTS_LIST_ID},
        sort=[("n", -1)],
        projection={"n": 1},
    ) or {}
    try:
        return max(1, int(top.get("n") or 0) + 1)
    except (TypeError, ValueError):
        return 1


def _boost_catalog(repo: Any, store: str, product_id: str, catalog_id: str | None = None) -> None:
    if not hasattr(repo, "scrape_priorities"):
        return
    now = _now()
    key = str(catalog_id or "").strip()
    try:
        if key:
            repo.scrape_priorities.update_one(
                {"catalog_id": key},
                {
                    "$set": {
                        "score": 94,
                        "tier": "high",
                        "next_due_at": now,
                        "updated_at": now,
                        "boost_reason": "user_alert",
                    }
                },
                upsert=False,
            )
        # También por store/product si el índice lo permite.
        repo.scrape_priorities.update_one(
            {"store": store, "product_id": product_id},
            {
                "$set": {
                    "score": 94,
                    "tier": "high",
                    "next_due_at": now,
                    "updated_at": now,
                    "boost_reason": "user_alert",
                }
            },
            upsert=False,
        )
    except Exception:
        pass


def _auto_start_if_idle(repo: Any) -> None:
    from retail.cyber_day import load_run, save_run

    run = load_run(repo, USER_ALERTS_LIST_ID)
    if run.get("status") in {"running", "paused"}:
        return
    now = _now()
    run.update({
        "status": "running",
        "started_at": run.get("started_at") or now,
        "lap_started_at": run.get("lap_started_at") or now,
        "heartbeat_at": now,
        "last_error": None,
        "list_id": USER_ALERTS_LIST_ID,
        "source_note": "Auto-inicio al agregar alerta de usuario.",
    })
    save_run(repo, run, list_id=USER_ALERTS_LIST_ID)


def add_user_alert(
    repo: Any,
    user: dict[str, Any],
    *,
    store: str,
    product_id: str,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Agrega o suma un watcher a la fila de la lista Alertas usuarios."""
    from retail.cyber_day import lists_collection, products_collection

    ensure_user_alerts_list(repo)
    doc = document if isinstance(document, dict) else {}
    anchor_store, anchor_id = _anchor_store_product(doc, store=store, product_id=product_id)
    key = alert_key_for_product(doc, store=anchor_store, product_id=anchor_id)
    watcher = _watcher_entry(user)
    if not watcher["user_id"]:
        return {"ok": False, "detail": "Usuario inválido."}

    coll = products_collection(repo)
    existing = coll.find_one({"list_id": USER_ALERTS_LIST_ID, "alert_key": key})
    now = _now()
    name = str(doc.get("name") or "").strip() or f"{anchor_store}/{anchor_id}"
    category = str(doc.get("category") or "").strip() or "Alertas"

    if existing:
        watchers = list(existing.get("watchers") or [])
        if any(str(w.get("user_id")) == watcher["user_id"] for w in watchers):
            return {
                "ok": True,
                "created": False,
                "already": True,
                "alert_key": key,
                "watcher_count": int(existing.get("watcher_count") or len(watchers)),
                "n": existing.get("n"),
            }
        watchers.append(watcher)
        first = watchers[0] if watchers else watcher
        coll.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "watchers": watchers,
                    "watcher_count": len(watchers),
                    "first_watcher_user_id": first.get("user_id"),
                    "first_watcher_email": first.get("email"),
                    "first_watcher_label": _watcher_label(first),
                    "updated_at": now,
                }
            },
        )
        lists_collection(repo).update_one(
            {"slug": USER_ALERTS_LIST_ID},
            {"$set": {"updated_at": now}},
        )
        _boost_catalog(repo, anchor_store, anchor_id, doc.get("catalog_id"))
        _auto_start_if_idle(repo)
        return {
            "ok": True,
            "created": False,
            "alert_key": key,
            "watcher_count": len(watchers),
            "n": existing.get("n"),
        }

    n = _next_n(repo)
    row = {
        "list_id": USER_ALERTS_LIST_ID,
        "n": n,
        "order": n - 1,
        "query": name,
        "name": name,
        "category": category,
        "alert_key": key,
        "store": anchor_store,
        "product_id": anchor_id,
        "anchor_store": anchor_store,
        "anchor_product_id": anchor_id,
        "compare_code": str(doc.get("compare_code") or "").strip() or None,
        "url": doc.get("url"),
        "watchers": [watcher],
        "watcher_count": 1,
        "first_watcher_user_id": watcher["user_id"],
        "first_watcher_email": watcher.get("email"),
        "first_watcher_label": _watcher_label(watcher),
        "source": USER_ALERTS_SOURCE,
        "created_at": now,
        "updated_at": now,
    }
    try:
        coll.insert_one(row)
    except Exception as exc:
        # Carrera de índice único: reintentar como update.
        again = coll.find_one({"list_id": USER_ALERTS_LIST_ID, "alert_key": key})
        if again:
            return add_user_alert(repo, user, store=store, product_id=product_id, document=document)
        raise CyberDayErrorFromUserAlerts(str(exc)) from exc

    from retail.cyber_day import load_run, save_run

    run = load_run(repo, USER_ALERTS_LIST_ID)
    run["total"] = int(coll.count_documents({"list_id": USER_ALERTS_LIST_ID}))
    run["list_id"] = USER_ALERTS_LIST_ID
    save_run(repo, run, list_id=USER_ALERTS_LIST_ID)
    lists_collection(repo).update_one(
        {"slug": USER_ALERTS_LIST_ID},
        {"$set": {"updated_at": now, "source": USER_ALERTS_SOURCE}},
    )
    _boost_catalog(repo, anchor_store, anchor_id, doc.get("catalog_id"))
    _auto_start_if_idle(repo)
    return {"ok": True, "created": True, "alert_key": key, "watcher_count": 1, "n": n}


class CyberDayErrorFromUserAlerts(RuntimeError):
    pass


def remove_user_alert(
    repo: Any,
    user: dict[str, Any],
    *,
    store: str,
    product_id: str,
    document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Quita al usuario de la fila; elimina el ítem si no quedan watchers."""
    from retail.cyber_day import delete_item, lists_collection, products_collection

    ensure_user_alerts_list(repo)
    doc = document if isinstance(document, dict) else {}
    anchor_store, anchor_id = _anchor_store_product(doc, store=store, product_id=product_id)
    key = alert_key_for_product(doc, store=anchor_store, product_id=anchor_id)
    user_id = str(user.get("id") or user.get("_id") or "").strip()
    if not user_id:
        return {"ok": False, "detail": "Usuario inválido."}

    coll = products_collection(repo)
    # Puede haber fila por compare_code o por store:id según cuándo se creó.
    candidates = list(coll.find({
        "list_id": USER_ALERTS_LIST_ID,
        "$or": [
            {"alert_key": key},
            {"anchor_store": store, "anchor_product_id": product_id},
            {"store": store, "product_id": product_id},
        ],
    }))
    if not candidates:
        return {"ok": True, "removed": False, "detail": "No estaba en la lista."}

    removed_rows = 0
    for existing in candidates:
        watchers = [
            w for w in (existing.get("watchers") or [])
            if str(w.get("user_id") or "") != user_id
        ]
        n = int(existing.get("n") or 0)
        if not watchers:
            if n >= 1:
                try:
                    delete_item(repo, n, list_id=USER_ALERTS_LIST_ID)
                except Exception:
                    coll.delete_one({"_id": existing["_id"]})
            else:
                coll.delete_one({"_id": existing["_id"]})
            removed_rows += 1
            continue
        first = watchers[0]
        coll.update_one(
            {"_id": existing["_id"]},
            {
                "$set": {
                    "watchers": watchers,
                    "watcher_count": len(watchers),
                    "first_watcher_user_id": first.get("user_id"),
                    "first_watcher_email": first.get("email"),
                    "first_watcher_label": _watcher_label(first),
                    "updated_at": _now(),
                }
            },
        )
    lists_collection(repo).update_one(
        {"slug": USER_ALERTS_LIST_ID},
        {"$set": {"updated_at": _now()}},
    )
    return {"ok": True, "removed": True, "deleted_rows": removed_rows}


def user_can_activate_alert(user: dict[str, Any]) -> tuple[bool, str]:
    """True si hay al menos un canal usable (email, telegram o push)."""
    from retail.notification_preferences import normalize_preferences

    prefs = normalize_preferences(user.get("notification_preferences"))
    channels = set(prefs.get("channels") or [])
    email = str(user.get("email") or "").strip()
    has_telegram = bool(user.get("telegram_chat_id") or user.get("telegram_username"))
    has_push = bool(user.get("push_subscriptions"))
    # Sin prefs explícitas: email basta (comportamiento histórico).
    if not channels:
        if email or has_telegram or has_push:
            return True, ""
        return False, "Configurá un correo, Telegram o push en tu cuenta para recibir alertas."
    if "email" in channels and email:
        return True, ""
    if "telegram" in channels and has_telegram:
        return True, ""
    if "push" in channels and has_push:
        return True, ""
    if "email" in channels and not email:
        return False, "Tu cuenta no tiene correo. Agregá uno o activá push/Telegram."
    if "telegram" in channels and not has_telegram:
        return False, "Vinculá Telegram o elegí otro canal en preferencias."
    if "push" in channels and not has_push:
        return False, "Activá push en este dispositivo o elegí otro canal."
    return False, "Configurá un canal de aviso en tu cuenta."


def backfill_from_price_alerts(repo: Any) -> dict[str, Any]:
    """Sincroniza price_alerts activos hacia la lista Cyber."""
    ensure_user_alerts_list(repo)
    if getattr(repo, "price_alerts", None) is None:
        return {"ok": False, "detail": "Sin colección price_alerts.", "added": 0}
    cursor = repo.price_alerts.find({"active": True})
    added = 0
    skipped = 0
    errors = 0
    for alert in cursor:
        user_id = str(alert.get("user_id") or "")
        store = str(alert.get("store") or "")
        product_id = str(alert.get("product_id") or "")
        if not user_id or not store or not product_id:
            skipped += 1
            continue
        user = {"id": user_id, "email": alert.get("email") or ""}
        if hasattr(repo, "find_user_by_id"):
            try:
                found = repo.find_user_by_id(user_id) or {}
                if found:
                    user = {**found, "id": user_id}
            except Exception:
                pass
        document = {}
        if hasattr(repo, "product_detail"):
            try:
                document = repo.product_detail(store, product_id) or {}
            except Exception:
                document = {}
        if not document.get("name"):
            document = {
                **document,
                "name": alert.get("name") or "",
                "url": alert.get("url") or "",
            }
        try:
            result = add_user_alert(repo, user, store=store, product_id=product_id, document=document)
            if result.get("created") or result.get("ok"):
                added += 1
            else:
                skipped += 1
        except Exception:
            errors += 1
    return {"ok": True, "added": added, "skipped": skipped, "errors": errors}


def collect_user_alert_matches(repo: Any, item: dict[str, Any]) -> list[dict[str, Any]]:
    """Matches para una fila de alertas: ancla + peers por compare_code."""
    from retail.cyber_day import catalog_matches_for_query, match_key

    store = str(item.get("anchor_store") or item.get("store") or "").strip()
    product_id = str(item.get("anchor_product_id") or item.get("product_id") or "").strip()
    compare_code = str(item.get("compare_code") or item.get("alert_key") or "").strip()
    seen: dict[str, dict[str, Any]] = {}

    def add(doc: dict[str, Any] | None) -> None:
        if not doc:
            return
        s = str(doc.get("store") or "").strip()
        p = str(doc.get("product_id") or "").strip()
        if not s or not p:
            return
        key = match_key(s, p)
        if key not in seen:
            seen[key] = doc

    if store and product_id and hasattr(repo, "product_detail"):
        try:
            add(repo.product_detail(store, product_id))
        except Exception:
            pass

    if compare_code and not compare_code.startswith(("store:",)) and hasattr(repo, "by_compare_code"):
        try:
            for peer in repo.by_compare_code(compare_code, limit=24) or []:
                add(peer)
        except Exception:
            pass
    elif compare_code.count(":") == 1 and hasattr(repo, "product_detail"):
        # alert_key era store:product_id
        s, _, p = compare_code.partition(":")
        if s and p:
            try:
                add(repo.product_detail(s, p))
            except Exception:
                pass

    if not seen:
        query = str(item.get("query") or item.get("name") or "").strip()
        if query:
            for match in catalog_matches_for_query(repo, query):
                add(match)

    return list(seen.values())


def enrich_user_alert_row_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Campos extra para product_row_view / API admin."""
    watchers = row.get("watchers") if isinstance(row.get("watchers"), list) else []
    first_label = str(row.get("first_watcher_label") or "").strip()
    if not first_label and watchers:
        first_label = _watcher_label(watchers[0])
    return {
        "alert_key": row.get("alert_key"),
        "watcher_count": int(row.get("watcher_count") or len(watchers) or 0),
        "first_watcher_label": first_label or None,
        "first_watcher_user_id": row.get("first_watcher_user_id"),
        "first_watcher_email": row.get("first_watcher_email"),
        "watchers": [
            {
                "user_id": w.get("user_id"),
                "email": w.get("email"),
                "display_name": w.get("display_name"),
                "added_at": _iso(w.get("added_at")),
                "label": _watcher_label(w),
            }
            for w in watchers
            if isinstance(w, dict)
        ],
        "anchor_store": row.get("anchor_store") or row.get("store"),
        "anchor_product_id": row.get("anchor_product_id") or row.get("product_id"),
        "is_user_alert": True,
    }
