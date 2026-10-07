"""Suscripciones y entregas Web Push asociadas a una cuenta."""

from __future__ import annotations

import base64
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

VAPID_SETTING = "web_push_vapid"
MAX_SUBSCRIPTIONS = 10
_CHALLENGE_MARKERS = (
    "/cdn-cgi/challenge",
    "cf-browser-verification",
    "cf-challenge",
    "challenges.cloudflare.com",
)
_public_lock = threading.Lock()
_public_known = False
_public_value = False


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


def vapid_for_webpush(private_key: str) -> Any:
    """Adapta la clave privada al formato que pywebpush 2 sí acepta.

    ``webpush()`` pasa el string a ``Vapid.from_string``. Esa función solo
    entiende 32 bytes crudos o DER en base64url. Un PEM PKCS8 (el formato que
    guardamos) se decodifica mal y cryptography responde
    «ASN.1 parsing error: invalid length», así que el aviso nunca sale.
    Un objeto ``Vapid`` ya cargado sí lo acepta.
    """
    text = (private_key or "").strip().replace("\\n", "\n")
    if "BEGIN" not in text:
        return text
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    key = serialization.load_pem_private_key(text.encode("ascii"), password=None)
    return Vapid(key)


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


def public_site_origin() -> str:
    """Origen HTTPS del sitio. El celular baja la foto desde aquí, no desde un path local."""
    raw = os.environ.get("PUBLIC_SITE_URL", "https://precios.meincart.cl").strip()
    parsed = urlparse(raw)
    if parsed.scheme == "https" and parsed.hostname:
        host = parsed.hostname
        if parsed.port and parsed.port != 443:
            host = f"{host}:{parsed.port}"
        return f"https://{host}"
    return "https://precios.meincart.cl"


def is_challenge_image_url(value: Any) -> bool:
    """True si la URL es una intersticial de comprobación, no una foto de producto."""
    text = str(value or "").strip().lower()
    if not text:
        return False
    return any(marker in text for marker in _CHALLENGE_MARKERS)


def _https_image(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > 2000 or is_challenge_image_url(text):
        return None
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    return text


def clear_screenshot_public_cache() -> None:
    global _public_known, _public_value
    with _public_lock:
        _public_known = False
        _public_value = False


def _local_web_serves_push() -> bool:
    """True solo si en este host responde el service worker de Precios.

    Un puerto 8080 de otra app (soyo tiene uno) no cuenta: la captura de ese
    disco no está en precios.meincart.cl.
    """
    from urllib.request import Request, urlopen

    try:
        request = Request(
            "http://127.0.0.1:8080/push-sw-v3.js",
            headers={"User-Agent": "precios-push"},
        )
        with urlopen(request, timeout=0.8) as response:
            if getattr(response, "status", 200) != 200:
                return False
            chunk = response.read(4096)
    except Exception:
        return False
    return b"notificationImage" in chunk and b"showNotification" in chunk


def screenshots_are_public() -> bool:
    """La captura local se publica solo si este host sirve el push de Precios.

    En soyo el PNG queda en disco y el celular no puede bajarlo: el push usa
    la foto del producto. `OFFER_SCREENSHOT_PUBLIC=1` fuerza la URL pública; `0` la apaga.
    """
    flag = os.environ.get("OFFER_SCREENSHOT_PUBLIC", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    global _public_known, _public_value
    with _public_lock:
        if not _public_known:
            _public_value = _local_web_serves_push()
            _public_known = True
        return _public_value


def push_image_url(payload: dict[str, Any]) -> str | None:
    """URL HTTPS de la misma foto de la oferta, o None si no hay una usable.

    Captura válida y servible por el sitio → `https://precios.meincart.cl/offer-shots/…`.
    Archivo solo local, o pantalla de comprobación → `image_url` del producto.
    """
    from retail.offer_screenshot import OFFER_SHOT_PREFIX, offer_shot_path

    chosen = payload.get("image_url")
    product = _https_image(payload.get("product_image_url"))
    if is_challenge_image_url(chosen):
        return product
    text = str(chosen or "").strip()
    if text and not text.startswith(("http://", "https://", "cid:", "data:")):
        served = offer_shot_path(Path(text).name) if screenshots_are_public() else None
        try:
            same_file = served is not None and served == Path(text).resolve()
        except OSError:
            same_file = False
        if same_file and served is not None:
            return f"{public_site_origin()}{OFFER_SHOT_PREFIX}/{served.name}"
        return product
    return _https_image(text) or product


def push_click_url(payload: dict[str, Any]) -> str:
    """URL que abre el clic del push: ficha in-app o short link, nunca solo /siguiendo si hay oferta.

    El service worker solo navega mismo origen o lnk.meincart.cl; por eso preferimos
    short_url / ruta /producto, no la URL cruda de la tienda.
    """
    short = str(payload.get("short_url") or "").strip()
    if short:
        return short
    raw = str(payload.get("url") or "").strip()
    if raw.startswith("/"):
        return raw
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    store = str(extra.get("store") or payload.get("store") or "").strip()
    product_id = str(extra.get("product_id") or payload.get("product_id") or "").strip()
    if store and product_id and store != "cyber" and product_id != "best":
        from retail.short_links import public_product_url

        ficha = public_product_url(store, product_id)
        if ficha:
            return ficha
    if raw:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if parsed.scheme == "https" and host in {"lnk.meincart.cl", "precios.meincart.cl"}:
            return raw
    return "/siguiendo"


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
    notice = str(payload.get("message") or "Cambio de precio detectado").strip()
    body = f"{detail} — {notice}" if detail else notice
    url = push_click_url(payload)
    message = {
        "title": name[:90],
        "body": body[:220],
        "url": url,
        "tag": f"precio-{tag}"[:120] if tag else "precio-alerta",
        "icon": "/static/brand/icon-192.png",
        "badge": "/static/brand/icon-192.png",
    }
    image = push_image_url(payload)
    if image:
        message["image"] = image
    return message


def send_user_push(
    user: dict[str, Any], payload: dict[str, Any], *, repo: Any, tag: str = "",
) -> bool:
    """Envía a los dispositivos de la cuenta y limpia endpoints expirados."""
    subscriptions = user.get("push_subscriptions") or []
    if not subscriptions or repo is None:
        return False
    try:
        from pywebpush import WebPushException, webpush

        private_key = vapid_for_webpush(vapid_keys(repo)["private_key"])
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
            print("Web Push enviado.")
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
