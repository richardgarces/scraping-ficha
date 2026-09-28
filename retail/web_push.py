"""Suscripciones y entregas Web Push asociadas a una cuenta."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

VAPID_SETTING = "web_push_vapid"
MAX_SUBSCRIPTIONS = 10


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def vapid_keys(repo: Any) -> dict[str, str]:
    """Obtiene las llaves VAPID o las genera una sola vez y las guarda en Mongo."""
    env_private = os.environ.get("WEB_PUSH_VAPID_PRIVATE_KEY", "").strip()
    env_public = os.environ.get("WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
    if env_private and env_public:
        return {"private_key": env_private, "public_key": env_public}

    saved = repo.get_app_setting(VAPID_SETTING) or {}
    if saved.get("private_key") and saved.get("public_key"):
        return {
            "private_key": str(saved["private_key"]),
            "public_key": str(saved["public_key"]),
        }

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    numbers = private.public_key().public_numbers()
    public_bytes = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    generated = {
        "private_key": private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii"),
        "public_key": _b64url(public_bytes),
    }
    repo.save_app_setting(VAPID_SETTING, generated)
    return generated


def normalize_subscription(raw: Any) -> dict[str, Any]:
    data = raw if isinstance(raw, dict) else {}
    endpoint = str(data.get("endpoint") or "").strip()
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or len(endpoint) > 2048:
        raise ValueError("La suscripción push no contiene un endpoint seguro.")
    if not p256dh or not auth or len(p256dh) > 512 or len(auth) > 256:
        raise ValueError("La suscripción push está incompleta.")
    return {
        "endpoint": endpoint,
        "expirationTime": data.get("expirationTime"),
        "keys": {"p256dh": p256dh, "auth": auth},
        "updated_at": datetime.now(timezone.utc),
    }


def subscription_payload(subscription: dict[str, Any]) -> dict[str, Any]:
    """Quita metadatos internos antes de entregarlos a pywebpush."""
    return {
        "endpoint": subscription.get("endpoint"),
        "expirationTime": subscription.get("expirationTime"),
        "keys": dict(subscription.get("keys") or {}),
    }


def push_message(payload: dict[str, Any], *, tag: str = "") -> dict[str, Any]:
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    name = str(payload.get("name") or payload.get("query") or "Producto")
    store = str(extra.get("store_title") or payload.get("store") or "").strip()
    price = payload.get("price")
    try:
        money = f"${int(float(price)):,}".replace(",", ".") if price not in (None, "") else ""
    except (TypeError, ValueError):
        money = ""
    detail = " · ".join(part for part in (store, money) if part)
    message = str(payload.get("message") or "Cambio de precio detectado").strip()
    body = f"{detail} — {message}" if detail else message
    url = str(payload.get("short_url") or "").strip() or "/siguiendo"
    return {
        "title": name[:90],
        "body": body[:220],
        "url": url,
        "tag": f"precio-{tag}"[:120] if tag else "precio-alerta",
        "icon": "/static/brand/icon-192.png",
        "badge": "/static/brand/icon-192.png",
    }


def send_user_push(
    user: dict[str, Any], payload: dict[str, Any], *, repo: Any, tag: str = "",
) -> bool:
    """Envía a los dispositivos de la cuenta y limpia endpoints expirados."""
    subscriptions = user.get("push_subscriptions") or []
    if not subscriptions or repo is None:
        return False
    try:
        from pywebpush import WebPushException, webpush

        private_key = vapid_keys(repo)["private_key"]
    except Exception as exc:
        print(f"Web Push no disponible: {exc}")
        return False

    sent = False
    active: list[dict[str, Any]] = []
    changed = False
    data = json.dumps(push_message(payload, tag=tag), ensure_ascii=False)
    for subscription in subscriptions[:MAX_SUBSCRIPTIONS]:
        if not isinstance(subscription, dict):
            changed = True
            continue
        try:
            webpush(
                subscription_info=subscription_payload(subscription),
                data=data,
                vapid_private_key=private_key,
                vapid_claims={
                    "sub": os.environ.get("WEB_PUSH_SUBJECT", "mailto:alertas@meincart.cl")
                },
                timeout=10,
            )
            active.append(subscription)
            sent = True
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in {404, 410}:
                changed = True
            else:
                active.append(subscription)
                print(f"Web Push rechazado ({status or 'sin estado'}): {exc}")
        except Exception as exc:
            active.append(subscription)
            print(f"Web Push falló: {exc}")
    if changed:
        repo.update_user_fields(str(user.get("_id") or user.get("id") or ""), {
            "push_subscriptions": active,
        })
    return sent
