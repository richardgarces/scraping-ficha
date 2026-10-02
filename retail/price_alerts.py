"""Alertas de cambio de precio para cuentas con correo.

La suscripción vive en Mongo (`price_alerts`), una por usuario + tienda + id.
El correo usa el email de la cuenta, no una dirección escrita en la ficha.
El aviso sale cuando un upsert guarda un precio distinto al anterior.
"""

from __future__ import annotations

from typing import Any

from retail.batch.alerts import _money, product_email_html, send_email
from retail.offer_screenshot import apply_offer_screenshot, is_local_image
from retail.short_links import attach_short_url, public_product_url

def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def price_deltas(previous: dict[tuple[str, str], tuple[Any, str]], products: list[Any]) -> list[dict[str, Any]]:
    """Cambios reales de precio. El primer avistamiento no cuenta: no hay anterior."""
    changes: list[dict[str, Any]] = []
    for product in products:
        store = getattr(product, "store", None) or ""
        product_id = getattr(product, "product_id", None) or ""
        if not store or not product_id:
            continue
        prior = previous.get((store, product_id))
        old = _as_int(prior[0]) if prior else None
        new = _as_int(getattr(product, "price", None))
        if old is None or new is None or old == new:
            continue
        changes.append(
            {
                "store": store,
                "product_id": product_id,
                "name": getattr(product, "name", None) or product_id,
                "url": getattr(product, "url", None) or "",
                "image_url": getattr(product, "image_url", None) or "",
                "seller": getattr(product, "seller", None) or "",
                "previous_price": old,
                "price": new,
            }
        )
    return changes


def ficha_url(store: str, product_id: str) -> str:
    return public_product_url(store, product_id)


def store_title(store_id: str, row: dict[str, Any] | None = None) -> str:
    from retail.store_display import display_store_title

    return display_store_title({**(row or {}), "store": store_id})


def price_change_message(change: dict[str, Any]) -> tuple[str, str]:
    name = str(change.get("name") or "Producto").strip() or "Producto"
    store = store_title(str(change.get("store") or ""), change)
    old = int(change["previous_price"])
    new = int(change["price"])
    direction = "bajó" if new < old else "subió"
    link = str(change.get("short_url") or ficha_url(
        str(change.get("store") or ""), str(change.get("product_id") or "")
    ))
    subject = f"Cambió el precio: {name}"
    body = "\n".join(
        [
            f"El precio {direction}.",
            "",
            name,
            f"Tienda: {store}",
            f"Precio anterior: {_money(old)}",
            f"Precio nuevo: {_money(new)}",
            "",
            f"Ver ficha: {link}",
        ]
    )
    return subject, body


def _recipient(repo: Any, alert: dict[str, Any]) -> str:
    user_id = str(alert.get("user_id") or "")
    raw: dict[str, Any] = {}
    if user_id and hasattr(repo, "find_user_by_id"):
        try:
            raw = repo.find_user_by_id(user_id) or {}
        except Exception:
            raw = {}
    status = str(raw.get("status") or alert.get("status") or "approved")
    if status and status != "approved":
        return ""
    return str(raw.get("email") or alert.get("email") or "").strip()


def notify_price_changes(repo: Any, changes: list[dict[str, Any]]) -> int:
    """Un cambio, un correo. Si SMTP no está, registra el salto y no tumba el upsert."""
    # PyMongo Collection prohíbe evaluarse como booleano. Comparar con None
    # evita que cada cambio de precio rompa el envío de alertas.
    if not changes or getattr(repo, "price_alerts", None) is None:
        return 0
    if not hasattr(repo, "price_alerts_for") or not hasattr(repo, "claim_price_alert_send"):
        return 0
    try:
        alerts = repo.price_alerts_for([(item["store"], item["product_id"]) for item in changes])
    except Exception as exc:
        print(f"Alerta de precio: no se pudieron leer suscripciones ({exc}).")
        return 0
    if not alerts:
        return 0
    from retail.batch.rules import load_rules

    # Medios de alerta del admin: sin «Correo» no se manda email de precio.
    system_channels = set(load_rules().get("channels") or [])
    email_enabled = "email" in system_channels
    by_product: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for alert in alerts:
        by_product.setdefault((alert.get("store") or "", alert.get("product_id") or ""), []).append(alert)
    sent = 0
    for change in changes:
        watchers = by_product.get((change["store"], change["product_id"])) or []
        if not watchers:
            continue
        from retail.store_display import display_store

        display_store_id, store_name = display_store(change)
        direction = "Bajó de precio" if int(change["price"]) < int(change["previous_price"]) else "Subió de precio"
        payload = {
            **change,
            "saving": max(0, int(change["previous_price"]) - int(change["price"])),
            "message": f"El precio {direction.lower()} de {_money(change['previous_price'])} a {_money(change['price'])}.",
            "extra": {
                "product_id": change.get("product_id"),
                "store_title": store_name,
                "display_store": display_store_id,
            },
        }
        attach_short_url(payload, repo)
        original_image = payload.get("image_url")
        apply_offer_screenshot(payload)
        image_url = payload.get("image_url") or change.get("image_url")
        change_with_link = {**change, "short_url": payload.get("short_url")}
        subject, body = price_change_message(change_with_link)
        send_kwargs = {
            "log_skip": True,
            "image_url": image_url if is_local_image(image_url) else None,
            "html": product_email_html(payload, eyebrow="Producto que sigues", heading=direction),
        }
        for alert in watchers:
            user_id = str(alert.get("user_id") or "")

            def claim(channel: str) -> bool:
                try:
                    return repo.claim_price_alert_send(
                        user_id,
                        change["store"],
                        change["product_id"],
                        int(change["previous_price"]),
                        int(change["price"]),
                        channel=channel,
                    )
                except Exception as exc:
                    print(f"Alerta de precio: no se pudo reservar el aviso ({exc}).")
                    return False

            email = _recipient(repo, alert)
            if not email:
                print("Alerta de precio: la cuenta no tiene correo; no se envía.")
                continue
            # Enviar por email y webhook/Telegram si están configurados.
            try:
                if email_enabled and claim("email") and send_email(email, subject, body, **send_kwargs):
                    sent += 1
                    print(f"Correo de alerta de precio enviado ({change['store']} {change['product_id']}).")
            except Exception:
                pass
            try:
                from retail.batch.alerts import _post_webhook, _webhook_targets

                for w in _webhook_targets():
                    try:
                        if claim(f"webhook:{w}"):
                            _post_webhook(w, {"subject": subject, "body": body, "product": change})
                            sent += 1
                    except Exception:
                        continue
            except Exception:
                pass
            try:
                from retail.batch.alerts import send_to_user

                if claim("telegram") and send_to_user(repo.find_user_by_id(user_id) or {}, body, image_url=image_url):
                    sent += 1
            except Exception:
                pass
            try:
                from retail.web_push import send_user_push

                user = repo.find_user_by_id(user_id) or {}
                prefs = user.get("notification_preferences") or {}
                push_payload = {**payload, "image_url": original_image}
                if (
                    "push" in (prefs.get("channels") or [])
                    and user.get("push_subscriptions")
                    and "push" in system_channels
                    and claim("push")
                    and send_user_push(user, push_payload, repo=repo, tag=f"{change['store']}:{change['product_id']}")
                ):
                    sent += 1
            except Exception:
                pass
    return sent
