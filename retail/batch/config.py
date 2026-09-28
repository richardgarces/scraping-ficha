from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retail.batch.catalog import PACKAGE_DIR, default_catalog_path, default_rules_path, load_json

CHANNELS_PATH = Path("output/canales.local.json")
SCHEDULE_PATH = PACKAGE_DIR / "programacion.json"
SCHEDULE_SETTING_KEY = "batch_schedule"
MASK = "••••"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_channels() -> dict[str, Any]:
    if CHANNELS_PATH.exists():
        return load_json(CHANNELS_PATH)
    return {
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "alert_email_to": "",
    }


def mask_channels(data: dict[str, Any]) -> dict[str, Any]:
    public = dict(data)
    for key in ("telegram_bot_token", "smtp_password"):
        value = str(public.get(key) or "")
        public[key] = f"{MASK}{value[-4:]}" if len(value) > 4 else (MASK if value else "")
        public[f"{key}_set"] = bool(value)
    return public


def merge_secrets(incoming: dict[str, Any]) -> dict[str, Any]:
    current = load_channels()
    merged = dict(current)
    for key, value in incoming.items():
        if key.endswith("_set"):
            continue
        text = "" if value is None else str(value)
        if text.startswith(MASK):
            continue
        if key == "smtp_port":
            merged[key] = int(value or 587)
        else:
            merged[key] = text
    return merged


RULE_NAMES = {"price_drop_percent", "price_drop_amount", "cross_store_gap", "below_median"}


def save_rules(data: dict[str, Any]) -> dict[str, Any]:
    enabled = [item for item in (data.get("enabled") or []) if item in RULE_NAMES]
    channels = [item for item in (data.get("channels") or []) if item in {"log", "file", "telegram", "email"}]
    payload = {
        "comment": data.get("comment") or "Reglas editables desde la interfaz web.",
        "enabled": enabled,
        "min_price": _int_or_none(data.get("min_price"), 0),
        "max_price": _int_or_none(data.get("max_price")),
        "price_drop_percent": float(data.get("price_drop_percent") or 0),
        "price_drop_amount": int(data.get("price_drop_amount") or 0),
        "cross_store_gap_percent": float(data.get("cross_store_gap_percent") or 0),
        "below_median_percent": float(data.get("below_median_percent") or 0),
        "ignore_fake_discounts": bool(data.get("ignore_fake_discounts", True)),
        # Las alertas push son siempre individuales; se conserva el campo para
        # compatibilidad con configuraciones antiguas, pero ya no se habilita.
        "digest": False,
        "digest_top": max(1, min(100, int(data.get("digest_top") or 25))),
        "channels": channels or ["log", "file"],
    }
    write_json(default_rules_path(), payload)
    return payload


def save_catalog(data: dict[str, Any]) -> dict[str, Any]:
    products = []
    seen: set[str] = set()
    for item in data.get("products") or []:
        ident = str(item.get("id") or "").strip()
        query = str(item.get("query") or "").strip()
        if not ident or not query or ident in seen:
            continue
        seen.add(ident)
        products.append(
            {
                "id": ident,
                "query": query,
                "category": item.get("category") or "otros",
                "brand": item.get("brand") or None,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    if not products:
        raise ValueError("El catálogo debe tener al menos un producto.")
    payload = {
        "title": data.get("title") or "Catálogo",
        "updated": datetime.now(timezone.utc).date().isoformat(),
        "default_stores": [str(item) for item in (data.get("default_stores") or []) if item],
        "products": products,
    }
    write_json(default_catalog_path(), payload)
    return payload


def _schedule_document(repo=None) -> tuple[dict[str, Any], Any]:
    owns_repo = repo is None
    store = repo
    if store is None:
        try:
            from retail.search import connect_repo

            store = connect_repo()
        except Exception:
            store = None
    try:
        if store is not None and hasattr(store, "get_app_setting"):
            found = store.get_app_setting(SCHEDULE_SETTING_KEY)
            if isinstance(found, dict) and found:
                return found, store
        return (load_json(SCHEDULE_PATH) if SCHEDULE_PATH.exists() else {}), store
    finally:
        if owns_repo and store is not None:
            store.close()


def _normalize_schedule(data: dict[str, Any]) -> dict[str, Any]:
    groups = data.get("groups") if isinstance(data.get("groups"), dict) else {}
    return {
        "enabled": bool(data.get("enabled", False)),
        "paused": bool(data.get("paused", False)),
        "hour": max(0, min(23, int(8 if data.get("hour") in (None, "") else data["hour"]))),
        "minute": max(0, min(59, int(0 if data.get("minute") in (None, "") else data["minute"]))),
        "source": data.get("source") if data.get("source") in {"scrape", "db", "both"} else "both",
        "pause": float(data.get("pause") if data.get("pause") is not None else 3),
        "batch_budget_minutes": max(
            10,
            min(360, int(data.get("batch_budget_minutes") or 90)),
        ),
        "groups": {
            "mode": groups.get("mode") if groups.get("mode") in {"per_group", "single"} else "per_group",
            "stagger_minutes": max(
                5,
                min(180, int(groups.get("stagger_minutes") if groups.get("stagger_minutes") is not None else 45)),
            ),
            "enabled": groups.get("enabled"),
        },
    }


def load_schedule(repo=None) -> dict[str, Any]:
    data, _store = _schedule_document(repo)
    return _normalize_schedule(data)


def save_schedule(data: dict[str, Any], repo=None) -> dict[str, Any]:
    current = load_schedule(repo)
    incoming_groups = data.get("groups") if isinstance(data.get("groups"), dict) else None
    groups = dict(current.get("groups") or {})
    if incoming_groups is not None:
        if incoming_groups.get("mode") in {"per_group", "single"}:
            groups["mode"] = incoming_groups["mode"]
        if incoming_groups.get("stagger_minutes") is not None:
            groups["stagger_minutes"] = max(5, min(180, int(incoming_groups["stagger_minutes"])))
        if "enabled" in incoming_groups:
            groups["enabled"] = incoming_groups.get("enabled")
    payload = {
        "enabled": bool(data.get("enabled")),
        "paused": bool(data.get("paused", current.get("paused", False))),
        "hour": max(0, min(23, int(8 if data.get("hour") in (None, "") else data["hour"]))),
        "minute": max(0, min(59, int(0 if data.get("minute") in (None, "") else data["minute"]))),
        "source": data.get("source") if data.get("source") in {"scrape", "db", "both"} else "both",
        "pause": max(0.0, float(3 if data.get("pause") in (None, "") else data["pause"])),
        "batch_budget_minutes": max(
            10,
            min(360, int(data.get("batch_budget_minutes") or current.get("batch_budget_minutes") or 90)),
        ),
        "groups": {
            "mode": groups.get("mode") or "per_group",
            "stagger_minutes": int(groups.get("stagger_minutes") or 45),
            "enabled": groups.get("enabled"),
        },
    }
    owns_repo = repo is None
    store = repo
    if store is None:
        try:
            from retail.search import connect_repo

            store = connect_repo()
        except Exception:
            store = None
    if store is None or not hasattr(store, "save_app_setting"):
        raise RuntimeError("MongoDB no está disponible para guardar la programación.")
    try:
        store.save_app_setting(SCHEDULE_SETTING_KEY, payload)
    finally:
        if owns_repo:
            store.close()
    # Espejo para los scripts del cron que corren en el host de BMAX.
    write_json(SCHEDULE_PATH, payload)
    return payload


def wait_while_paused(repo: Any, run_id: str | None = None, poll_seconds: float = 2.0) -> None:
    """Pausa cooperativa para los lotes activos, controlada desde administración."""
    import time

    waiting = False
    while load_schedule(repo).get("paused"):
        if run_id and not waiting and hasattr(repo, "update_batch_run"):
            repo.update_batch_run(run_id, phase="paused")
        waiting = True
        time.sleep(max(0.5, poll_seconds))
    if waiting and run_id and hasattr(repo, "update_batch_run"):
        repo.update_batch_run(run_id, phase="products")


def _int_or_none(value: Any, minimum: int | None = None) -> int | None:
    if value in (None, ""):
        return None
    number = int(value)
    if minimum is not None and number < minimum:
        return minimum
    return number
