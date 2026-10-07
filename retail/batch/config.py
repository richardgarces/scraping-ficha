from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retail.batch.catalog import PACKAGE_DIR, default_catalog_path, default_rules_path, load_json

CHANNELS_PATH = Path("output/canales.local.json")
CHANNELS_SETTING_KEY = "notification_channels"
SCHEDULE_PATH = PACKAGE_DIR / "programacion.json"
SCHEDULE_SETTING_KEY = "batch_schedule"
MASK = "••••"

_CHANNEL_KEYS = (
    "telegram_bot_token",
    "telegram_chat_id",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "smtp_from",
    "alert_email_to",
)

# Env names that fill/override channel fields (first nonempty wins per field).
_CHANNEL_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "telegram_bot_token": ("TELEGRAM_BOT_TOKEN",),
    "telegram_chat_id": ("TELEGRAM_CHAT_ID",),
    "smtp_host": ("SMTP_HOST",),
    "smtp_port": ("SMTP_PORT",),
    "smtp_user": ("SMTP_USER",),
    "smtp_password": ("SMTP_PASSWORD", "SMTP_PASS"),
    "smtp_from": ("SMTP_FROM",),
    "alert_email_to": ("ALERT_EMAIL_TO", "SMTP_TO"),
}

_SECRET_CHANNEL_KEYS = frozenset({"telegram_bot_token", "smtp_password"})


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _default_channels() -> dict[str, Any]:
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


def _channels_payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = _default_channels()
    for key in _CHANNEL_KEYS:
        if key not in data:
            continue
        if key == "smtp_port":
            payload[key] = int(data.get(key) or 587)
        else:
            payload[key] = "" if data.get(key) is None else str(data.get(key))
    return payload


def _env_value(*names: str) -> str:
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def channels_from_env() -> dict[str, Any]:
    """Valores de canales presentes en el entorno (solo claves con valor)."""
    found: dict[str, Any] = {}
    for key, names in _CHANNEL_ENV_NAMES.items():
        text = _env_value(*names)
        if not text:
            continue
        if key == "smtp_port":
            try:
                found[key] = int(text)
            except ValueError:
                found[key] = 587
        else:
            found[key] = text
    return found


def _apply_env_overlay(data: dict[str, Any]) -> dict[str, Any]:
    """Env gana cuando está definido; rellena huecos del archivo/Mongo."""
    payload = _channels_payload(data)
    for key, value in channels_from_env().items():
        payload[key] = value
    return _channels_payload(payload)


def _channels_from_mongo(repo: Any | None = None) -> dict[str, Any] | None:
    owns = repo is None
    store = repo
    if store is None:
        try:
            from retail.search import connect_repo

            store = connect_repo()
        except Exception:
            return None
    if store is None or not hasattr(store, "get_app_setting"):
        return None
    try:
        found = store.get_app_setting(CHANNELS_SETTING_KEY)
        if isinstance(found, dict) and found:
            return _channels_payload(found)
        return None
    finally:
        if owns and store is not None:
            store.close()


def load_channels(repo: Any | None = None) -> dict[str, Any]:
    """Lee canales: archivo → Mongo (si falta token) → overlay de env (env gana)."""
    data = _default_channels()
    if CHANNELS_PATH.exists():
        try:
            data = _channels_payload({**data, **load_json(CHANNELS_PATH)})
        except Exception:
            data = _default_channels()
    if not str(data.get("telegram_bot_token") or "").strip():
        stored = _channels_from_mongo(repo)
        if stored:
            data = _channels_payload({**data, **stored})
    data = _apply_env_overlay(data)
    # Repara archivo/Mongo cuando env (o Mongo) aportó el token y el archivo estaba vacío.
    if str(data.get("telegram_bot_token") or "").strip():
        try:
            on_disk = (
                _channels_payload(load_json(CHANNELS_PATH))
                if CHANNELS_PATH.exists()
                else _default_channels()
            )
        except Exception:
            on_disk = _default_channels()
        if not str(on_disk.get("telegram_bot_token") or "").strip():
            try:
                write_json(CHANNELS_PATH, data)
            except Exception:
                pass
            owns = repo is None
            store = repo
            if store is None:
                try:
                    from retail.search import connect_repo

                    store = connect_repo()
                except Exception:
                    store = None
            if store is not None and hasattr(store, "save_app_setting"):
                try:
                    store.save_app_setting(CHANNELS_SETTING_KEY, data)
                finally:
                    if owns:
                        store.close()
            elif owns and store is not None:
                store.close()
    return data


def save_channels(data: dict[str, Any], repo: Any | None = None) -> dict[str, Any]:
    """Guarda en archivo y en Mongo. El overlay de env sigue aplicando al leer."""
    payload = _apply_env_overlay(_channels_payload(data))
    write_json(CHANNELS_PATH, payload)
    owns = repo is None
    store = repo
    if store is None:
        try:
            from retail.search import connect_repo

            store = connect_repo()
        except Exception:
            store = None
    if store is not None and hasattr(store, "save_app_setting"):
        try:
            store.save_app_setting(CHANNELS_SETTING_KEY, payload)
        finally:
            if owns:
                store.close()
    elif owns and store is not None:
        store.close()
    return payload


def mask_channels(data: dict[str, Any]) -> dict[str, Any]:
    public = dict(data)
    env = channels_from_env()
    for key in ("telegram_bot_token", "smtp_password"):
        value = str(public.get(key) or "")
        public[key] = f"{MASK}{value[-4:]}" if len(value) > 4 else (MASK if value else "")
        public[f"{key}_set"] = bool(value)
        public[f"{key}_from_env"] = key in env
    for key in _CHANNEL_KEYS:
        if key in _SECRET_CHANNEL_KEYS:
            continue
        public[f"{key}_from_env"] = key in env
    return public


def merge_secrets(incoming: dict[str, Any]) -> dict[str, Any]:
    """Fusiona el formulario con lo guardado. Vacío no pisa env ni secretos actuales."""
    current = load_channels()
    env = channels_from_env()
    merged = dict(current)
    for key, value in incoming.items():
        if key.endswith("_set") or key.endswith("_from_env"):
            continue
        if key not in _CHANNEL_KEYS and key != "smtp_port":
            continue
        text = "" if value is None else str(value)
        if text.startswith(MASK):
            continue
        if key == "smtp_port":
            if text.strip() == "":
                continue
            merged[key] = int(value or 587)
            continue
        if not text.strip():
            # Vacío: no borrar si viene de env o (secretos) si ya hay valor.
            if key in env:
                continue
            if key in _SECRET_CHANNEL_KEYS and str(current.get(key) or "").strip():
                continue
            merged[key] = ""
            continue
        merged[key] = text
    return _apply_env_overlay(merged)


RULE_NAMES = {"price_drop_percent", "price_drop_amount", "cross_store_gap", "below_median"}


def save_rules(data: dict[str, Any]) -> dict[str, Any]:
    enabled = [item for item in (data.get("enabled") or []) if item in RULE_NAMES]
    channels = [
        item for item in (data.get("channels") or [])
        if item in {"log", "file", "telegram", "email", "push"}
    ]
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

    from retail.batch.group_scope import raise_if_group_stopped

    raise_if_group_stopped(repo, run_id)
    waiting = False
    while load_schedule(repo).get("paused"):
        raise_if_group_stopped(repo, run_id)
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
