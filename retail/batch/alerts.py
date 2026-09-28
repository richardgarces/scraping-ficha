from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import smtplib
from html import escape
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPSHandler, Request

from retail.batch.config import load_channels
from retail.batch.rules import Alert
from retail.short_links import attach_short_url, public_product_url, short_product_url

DEFAULT_LOG = Path("output/alerts.jsonl")
REALES_STATE = Path("output/telegram_reales.json")
PUBLIC_REALES = "https://precios.meincart.cl/reales"

PUSH_CHANNELS = ("telegram", "email", "webhook")
TELEGRAM_LIMIT = 3800
TELEGRAM_MIN_DISCOUNT = 40.0
# Destinatario prellenado de la prueba de aviso. No es el único permitido.
DEFAULT_NOTICE_TEST_EMAIL = "richardgarces@gmail.com"
# Campos de la cuenta. El chat que hoy está guardado vive en canales
# (telegram_chat_id); estos se suman si el documento de usuario los tiene.
USER_TELEGRAM_FIELDS = ("telegram_chat_id", "telegram_username", "telegram")

_resolved_chats: dict[str, str] = {}
_unresolved_chats: set[str] = set()
_user_chats: list[str] = []


def _money(value: Any) -> str:
    if value in (None, ""):
        return "s/precio"
    return f"${int(value):,}".replace(",", ".")


def digest_text(alerts: list[Alert], *, title: str, top: int = 25) -> str:
    """Un solo mensaje con las mejores ofertas, agrupadas por categoría.

    Con miles de búsquedas por corrida, mandar una alerta por hallazgo termina
    en un canal silenciado. Acá manda el ahorro: primero lo que más ahorra.
    """
    mejores = sorted(alerts, key=lambda alert: -(alert.saving or 0))
    lineas = [f"{title} · {len(alerts)} ofertas"]
    por_categoria: dict[str, list[Alert]] = {}
    for alert in mejores[:top]:
        por_categoria.setdefault(alert.category or "otros", []).append(alert)
    for categoria, grupo in por_categoria.items():
        lineas.append("")
        lineas.append(categoria.upper())
        for alert in grupo:
            ahorro = f"−{_money(alert.saving)} " if alert.saving else ""
            lineas.append(f"• {ahorro}{alert.name[:58]}")
            product_id = (alert.extra or {}).get("product_id")
            ficha = product_page_url(alert.store, product_id)
            lineas.append(f"  {alert.store} {_money(alert.price)}" + (f" · {ficha}" if ficha else ""))
    restantes = len(alerts) - min(len(alerts), top)
    if restantes > 0:
        lineas.append("")
        lineas.append(f"y {restantes} más en /hoy")
    texto = "\n".join(lineas)
    return texto[:TELEGRAM_LIMIT]


def send_digest(alerts: list[Alert], channels: list[str], *, title: str, top: int = 25) -> list[str]:
    """Manda el resumen por los canales de notificación. Sin alertas, no molesta."""
    if not alerts:
        return []
    destinos = [channel for channel in PUSH_CHANNELS if channel in channels]
    if not destinos:
        return []
    texto = digest_text(alerts, title=title, top=top)
    image_url = next((alert.image_url for alert in sorted(alerts, key=lambda item: -(item.saving or 0)) if alert.image_url), None)
    enviados = []
    for destino in destinos:
        if destino == "telegram":
            if _telegram_text(texto, image_url=image_url):
                enviados.append(destino)
        elif destino == "webhook":
            # enviar resumen a webhooks configurados
            for webhook in _webhook_targets():
                try:
                    _post_webhook(webhook, {"title": title, "text": texto})
                    enviados.append(destino)
                except Exception:
                    continue
        else:
            _email_text(title, texto, image_url=image_url)
            enviados.append(destino)
    return enviados


def _webhook_targets() -> list[str]:
    data = load_channels()
    raw = data.get("webhook_urls") or os.environ.get("WEBHOOK_URLS") or ""
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return [x.strip() for x in str(raw or "").split(";") if x.strip()]


def _post_webhook(url: str, payload: dict[str, Any]) -> None:
    # POST JSON to webhook URL, ignore errors upstream
    from urllib.request import Request, urlopen

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=6) as resp:
            # accept 2xx
            if resp.status // 100 != 2:
                raise Exception(f"webhook {url} status {resp.status}")
    except Exception as exc:
        print(f"Webhook error for {url}: {exc}")


def alert_entity_key(alert: Alert) -> str:
    """Identidad estable para no avisar el mismo producto por cada consulta o tienda."""
    if alert.compare_code:
        return str(alert.compare_code)
    product_id = str((alert.extra or {}).get("product_id") or "").strip()
    if product_id:
        return f"product:{alert.store}:{product_id}"
    folded = " ".join(str(alert.name or alert.query or "").casefold().split())
    return f"name:{folded}"


def _alert_discount(alert: Alert) -> float:
    extra = alert.extra or {}
    values = [extra.get("percent"), extra.get("gap_percent")]
    if extra.get("percent_vs_median") is not None:
        try:
            values.append(abs(float(extra["percent_vs_median"])))
        except (TypeError, ValueError):
            pass
    clean: list[float] = []
    for value in values:
        try:
            if value is not None:
                clean.append(float(value))
        except (TypeError, ValueError):
            continue
    return max(clean, default=0.0)


def _telegram_offer_allowed(alert: Alert) -> bool:
    from retail.notification_preferences import alert_kind

    if alert_kind(alert) in {"watch", "predictive"}:
        return True
    return _alert_discount(alert) >= TELEGRAM_MIN_DISCOUNT


def deduplicate_product_alerts(alerts: list[Alert]) -> list[Alert]:
    """Deja la señal más fuerte por producto dentro de una búsqueda."""
    selected: dict[str, Alert] = {}
    for alert in alerts:
        key = alert_entity_key(alert)
        current = selected.get(key)
        score = (_alert_discount(alert), int(alert.saving or 0), -(int(alert.price or 0)))
        current_score = (
            _alert_discount(current), int(current.saving or 0), -(int(current.price or 0))
        ) if current else None
        if current is None or score > current_score:
            selected[key] = alert
    return list(selected.values())


def dispatch_alerts(
    alerts: list[Alert], channels: list[str], *, log_path: Path = DEFAULT_LOG,
    repo: Any | None = None,
) -> list[str]:
    sent: list[str] = []
    for alert in deduplicate_product_alerts(alerts):
        payload = attach_short_url(_payload(alert), repo)
        if "log" in channels:
            print(f"ALERTA [{alert.rule}] {alert.query}: {alert.message}")
            sent.append("log")
        if "file" in channels:
            _append_file(log_path, payload)
            sent.append("file")
        if "telegram" in channels and _telegram_offer_allowed(alert):
            claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                "global", "telegram", alert_entity_key(alert), alert.price,
            )
            if claimed and _telegram(payload):
                sent.append("telegram")
        if "email" in channels:
            claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                "global", "email", alert_entity_key(alert), alert.price,
            )
            if claimed and _email(payload):
                sent.append("email")
        if "webhook" in channels:
            for webhook in _webhook_targets():
                try:
                    claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                        "global", f"webhook:{webhook}", alert_entity_key(alert), alert.price,
                    )
                    if not claimed:
                        continue
                    _post_webhook(webhook, payload)
                    sent.append("webhook")
                except Exception:
                    continue
    return sent


def _payload(alert: Alert) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "catalog_id": alert.catalog_id,
        "query": alert.query,
        "rule": alert.rule,
        "name": alert.name,
        "store": alert.store,
        "price": alert.price,
        "price_normal": alert.price_normal,
        "previous_price": alert.previous_price,
        "message": alert.message,
        "url": alert.url,
        "compare_code": alert.compare_code,
        "saving": alert.saving,
        "category": alert.category,
        "image_url": alert.image_url,
        "extra": alert.extra,
    }


def _append_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _secret(env_name: str, local_name: str) -> str:
    return os.environ.get(env_name) or str(load_channels().get(local_name) or "")


def _telegram(payload: dict[str, Any]) -> bool:
    return _telegram_text(_notification_text(payload), image_url=payload.get("image_url"))


def _discount(payload: dict[str, Any]) -> tuple[float | None, Any]:
    extra = payload.get("extra") or {}
    reference = (payload.get("price_normal") or extra.get("previous_price") or payload.get("previous_price")
                 or extra.get("second_price") or extra.get("median"))
    percent = extra.get("percent") or extra.get("gap_percent")
    if percent is None and extra.get("percent_vs_median") is not None:
        percent = abs(float(extra["percent_vs_median"]))
    if percent is None and reference and payload.get("price") and int(reference) > int(payload["price"]):
        percent = (int(reference) - int(payload["price"])) * 100 / int(reference)
    try:
        percent = float(percent) if percent is not None else None
    except (TypeError, ValueError):
        percent = None
    return percent, reference


def _notification_text(payload: dict[str, Any]) -> str:
    percent, reference = _discount(payload)
    extra = payload.get("extra") or {}
    lines = [f"🔔 {payload.get('name') or payload.get('query') or 'Oferta'}"]
    store = extra.get("store_title") or payload.get("store")
    if store:
        lines.append(f"🏬 {store}")
    lines.append(f"💰 Precio para todo medio de pago: {_money(payload.get('price'))}")
    if extra.get("price_card"):
        card = extra.get("payment_card_name") or "tarjeta de la tienda"
        lines.append(f"💳 Con {card}: {_money(extra['price_card'])}")
    shipping = extra.get("shipping_cost")
    if shipping is not None:
        lines.append("🚚 Despacho: gratis" if int(shipping) == 0 else f"🚚 Despacho: {_money(shipping)}")
        if payload.get("price"):
            lines.append(f"🧮 Costo total: {_money(int(payload['price']) + int(shipping))}")
    elif extra.get("shipping_free_threshold"):
        lines.append(f"🚚 Despacho gratis desde {_money(extra['shipping_free_threshold'])}")
    if extra.get("pickup_available"):
        lines.append("🏪 Retiro en tienda disponible")
    condition_labels = {
        "refurbished": "Reacondicionado", "open_box": "Caja abierta",
        "display": "Exhibición", "used": "Usado",
    }
    if extra.get("condition") in condition_labels:
        lines.append(f"📦 Condición: {condition_labels[extra['condition']]}")
    if extra.get("stock") is not None:
        lines.append(f"📦 Stock informado: {extra['stock']}")
    elif extra.get("low_stock"):
        lines.append("⚠️ La tienda informa poco stock")
    if percent is not None:
        lines.append(f"🏷️ Descuento: {percent:.0f}%" + (f" · antes {_money(reference)}" if reference else ""))
    if payload.get("saving"):
        lines.append(f"💸 Ahorras: {_money(payload['saving'])}")
    lines.append(str(payload.get("message") or ""))
    store = extra.get("store") or payload.get("store")
    product_id = extra.get("product_id") or payload.get("product_id")
    ficha = _safe_http_url(payload.get("short_url")) or product_page_url(store, product_id)
    if ficha:
        lines.append(f"🔗 Ficha: {ficha}")
    return "\n".join(line for line in lines if line)


def _safe_http_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def product_page_url(store: Any, product_id: Any) -> str:
    return _safe_http_url(public_product_url(store, product_id))


def _product_urls(payload: dict[str, Any]) -> tuple[str, str]:
    extra = payload.get("extra") or {}
    store = extra.get("store") or payload.get("store")
    product_id = extra.get("product_id") or payload.get("product_id")
    ficha = _safe_http_url(payload.get("short_url")) or product_page_url(store, product_id)
    return _safe_http_url(ficha), _safe_http_url(payload.get("url"))


def _store_logo_url(store: Any) -> str:
    """Logo público disponible para web/correo, con fallback de tienda genérica."""
    raw = str(store or "").strip().lower()
    key = "".join(char for char in raw if char.isalnum() or char in {"-", "_"})
    filename = "_store.svg"
    if key and key == raw:
        logo_dir = Path(__file__).resolve().parents[1] / "web" / "static" / "logos"
        for suffix in ("png", "jpg", "jpeg", "webp", "svg"):
            candidate = logo_dir / f"{key}.{suffix}"
            if candidate.is_file():
                filename = candidate.name
                break
    public_site = os.environ.get("PUBLIC_SITE_URL", "https://precios.meincart.cl").rstrip("/")
    return f"{public_site}/static/logos/{quote(filename, safe='._-')}"


def product_email_html(
    payload: dict[str, Any],
    *,
    eyebrow: str = "Alerta de precio",
    heading: str | None = None,
) -> str:
    """Tarjeta compatible con clientes de correo, inspirada en la ficha web."""
    extra = payload.get("extra") or {}
    name = str(payload.get("name") or payload.get("query") or "Producto")
    store = str(extra.get("store_title") or payload.get("store_title") or payload.get("store") or "Tienda")
    store_logo = _safe_http_url(
        _store_logo_url(extra.get("display_store") or extra.get("store") or payload.get("store"))
    )
    message = str(payload.get("message") or "Revisa el precio y su historial antes de comprar.")
    price = payload.get("price")
    percent, reference = _discount(payload)
    saving = payload.get("saving")
    image = _safe_http_url(payload.get("image_url"))
    ficha_url, store_url = _product_urls(payload)
    main_url = ficha_url or store_url
    old_price = reference or payload.get("previous_price") or payload.get("price_normal")
    rule = str(payload.get("rule") or "")
    default_titles = {
        "cross_store_gap": "Mejor precio entre tiendas",
        "below_median": "Bajo su precio habitual",
        "watch_target": "Llegó a tu precio objetivo",
        "watch_change": "Cambió el precio",
        "common_discount": "Descuento publicado",
    }
    title = heading or default_titles.get(rule) or (
        "Bajó de precio" if old_price and price and int(price) < int(old_price) else "Oferta encontrada"
    )
    is_rise = "subió" in title.casefold() or "alza" in title.casefold()
    accent = "#be123c" if is_rise else "#047857"
    accent_soft = "#ffe4e6" if is_rise else "#d1fae5"
    accent_text = "#9f1239" if is_rise else "#065f46"
    reference_label = "Antes"
    if extra.get("second_price") is not None:
        reference_label = f"Otra tienda ({extra.get('second_store') or 'comparación'})"
    elif extra.get("median") is not None:
        reference_label = "Precio habitual"
    elif extra.get("target_price") is not None:
        reference_label = "Tu precio objetivo"

    image_html = ""
    if image:
        image_html = (
            '<tr><td style="padding:0 24px 20px;text-align:center">'
            f'<img src="{escape(image, quote=True)}" alt="{escape(name, quote=True)}" width="320" '
            'style="display:inline-block;width:100%;max-width:320px;height:260px;object-fit:contain;'
            'border:0;border-radius:16px;background:#ffffff">'
            '</td></tr>'
        )
    discount_html = ""
    if percent is not None and percent > 0:
        discount_html = (
            '<span style="display:inline-block;margin-left:8px;padding:5px 9px;border-radius:999px;'
            f'background:{accent_soft};color:{accent_text};font-size:13px;font-weight:800">'
            f'−{percent:.0f}%</span>'
        )
    reference_html = ""
    if old_price and price and int(old_price) != int(price):
        reference_html = (
            f'<div style="margin-top:6px;color:#64748b;font-size:15px">{escape(reference_label)} '
            f'<span style="text-decoration:line-through">{escape(_money(old_price))}</span></div>'
        )
    saving_html = ""
    if saving:
        saving_html = (
            '<div style="margin-top:10px;color:#047857;font-size:15px;font-weight:700">'
            f'Ahorras {escape(_money(saving))}</div>'
        )
    detail_rows: list[str] = []
    condition_labels = {
        "refurbished": "Reacondicionado", "open_box": "Caja abierta",
        "display": "Exhibición", "used": "Usado",
    }
    condition = condition_labels.get(str(extra.get("condition") or ""))
    if condition:
        detail_rows.append(f"<strong>Condición:</strong> {escape(condition)}")
    if extra.get("price_card"):
        card = str(extra.get("payment_card_name") or "tarjeta de la tienda")
        detail_rows.append(f"<strong>Con {escape(card)}:</strong> {escape(_money(extra['price_card']))}")
    shipping = extra.get("shipping_cost")
    if shipping is not None:
        shipping_text = "Gratis" if int(shipping) == 0 else _money(shipping)
        detail_rows.append(f"<strong>Despacho informado:</strong> {escape(shipping_text)}")
        if price:
            detail_rows.append(f"<strong>Costo total:</strong> {escape(_money(int(price) + int(shipping)))}")
    elif extra.get("shipping_free_threshold"):
        detail_rows.append(
            f"<strong>Despacho gratis desde:</strong> {escape(_money(extra['shipping_free_threshold']))}"
        )
    if extra.get("pickup_available"):
        detail_rows.append("<strong>Retiro en tienda:</strong> Disponible")
    if extra.get("stock") is not None:
        detail_rows.append(f"<strong>Stock informado:</strong> {escape(str(extra['stock']))}")
    elif extra.get("low_stock"):
        detail_rows.append("<strong>Disponibilidad:</strong> Poco stock informado")
    details_html = ""
    if detail_rows:
        details_html = (
            '<tr><td style="padding:0 32px 20px"><div style="padding:14px 18px;border-radius:14px;'
            'background:#f8fafc;border:1px solid #e2e8f0;color:#334155;font-size:14px;line-height:1.8">'
            + "<br>".join(detail_rows) + "</div></td></tr>"
        )
    actions = ""
    if main_url:
        actions = (
            '<tr><td style="padding:8px 32px 32px;text-align:center">'
            f'<a href="{escape(main_url, quote=True)}" style="display:inline-block;padding:14px 24px;'
            'border-radius:12px;background:#10b981;color:#052e2b;text-decoration:none;'
            'font-size:16px;font-weight:800">Ver ficha del producto</a>'
        )
        if ficha_url and store_url and ficha_url != store_url:
            actions += (
                f'<div style="margin-top:14px"><a href="{escape(store_url, quote=True)}" '
                'style="color:#475569;font-size:13px">Abrir directamente en la tienda</a></div>'
            )
        actions += "</td></tr>"

    return (
        '<!doctype html><html><body style="margin:0;padding:0;background:#eef2f7;'
        'font-family:Arial,Helvetica,sans-serif;color:#172033">'
        '<div style="display:none;max-height:0;overflow:hidden;color:transparent">'
        f'{escape(title)}: {escape(name)} a {escape(_money(price))}</div>'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        'style="width:100%;background:#eef2f7"><tr><td align="center" style="padding:28px 12px">'
        '<table role="presentation" width="460" cellspacing="0" cellpadding="0" '
        'style="width:100%;max-width:460px;background:#ffffff;border:1px solid #dbe3ee;'
        'border-radius:20px;overflow:hidden;box-shadow:0 12px 32px rgba(15,23,42,.08)">'
        '<tr><td style="padding:24px 32px;background:#111827;color:#ffffff">'
        '<div style="font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#6ee7b7;'
        f'font-weight:800">{escape(eyebrow)}</div>'
        f'<div style="margin-top:7px;font-size:24px;line-height:1.2;font-weight:800">{escape(title)}</div>'
        '</td></tr>'
        '<tr><td style="padding:24px 24px 12px">'
        '<table role="presentation" cellspacing="0" cellpadding="0"><tr>'
        '<td style="width:30px;padding-right:8px;vertical-align:middle">'
        f'<img src="{escape(store_logo, quote=True)}" alt="" width="28" height="28" '
        'style="display:block;width:28px;height:28px;object-fit:contain;border:0;border-radius:7px;background:#ffffff">'
        '</td><td style="vertical-align:middle;color:#334155;font-size:13px;font-weight:700">'
        f'{escape(store)}</td></tr></table>'
        f'<h1 style="margin:14px 0 10px;font-size:25px;line-height:1.25;color:#0f172a">{escape(name)}</h1>'
        '</td></tr>'
        '<tr><td style="padding:2px 24px 18px">'
        '<div style="font-size:13px;color:#64748b;text-transform:uppercase;letter-spacing:.05em">Precio para todo medio de pago</div>'
        f'<div style="margin-top:4px;font-size:34px;line-height:1.15;font-weight:900;color:{accent}">'
        f'{escape(_money(price))}{discount_html}</div>{reference_html}{saving_html}'
        '</td></tr>'
        f'{image_html}'
        f'{details_html}'
        '<tr><td style="padding:0 24px 24px;text-align:center">'
        '<div style="display:inline-block;width:100%;max-width:320px;padding:14px 16px;box-sizing:border-box;'
        'text-align:left;border-radius:14px;background:#f8fafc;border:1px solid #e2e8f0;'
        f'font-size:15px;line-height:1.55;color:#334155">{escape(message)}</div>'
        '</td></tr>'
        f'{actions}'
        '<tr><td style="padding:18px 32px;background:#f8fafc;border-top:1px solid #e2e8f0;'
        'color:#64748b;font-size:12px;line-height:1.5">Precios compara valores publicados por las tiendas. '
        'Confirma precio, disponibilidad y condiciones antes de comprar.</td></tr>'
        '</table></td></tr></table></body></html>'
    )


def bind_user_chats(repo: Any, user_documents: list[dict[str, Any]] | None = None) -> None:
    """Reserva los chats personales activos para no repetirles el aviso global."""
    global _user_chats
    if user_documents is None:
        _user_chats = user_telegram_chats(repo)
        return
    chats: list[str] = []
    for document in user_documents:
        channels = (document.get("notification_preferences") or {}).get("channels") or []
        if "telegram" not in channels:
            continue
        for value in _chat_values(document):
            if value not in chats:
                chats.append(value)
    _user_chats = chats


def user_telegram_chats(repo: Any) -> list[str]:
    users = getattr(repo, "users", None)
    if users is None:
        return []
    try:
        cursor = users.find({}, {field: 1 for field in USER_TELEGRAM_FIELDS})
    except Exception as exc:
        print(f"Telegram: no se leyeron los chats de las cuentas ({exc})")
        return []
    chats: list[str] = []
    for document in cursor:
        for value in _chat_values(document):
            if value not in chats:
                chats.append(value)
    return chats


def _chat_values(document: dict[str, Any]) -> list[str]:
    primary = str(document.get("telegram_chat_id") or "").strip()
    if primary.lstrip("-").isdigit():
        return [primary]
    found: list[str] = []
    for field in ("telegram_username", "telegram_chat_id"):
        value = str(document.get(field) or "").strip()
        if value:
            found.append(value)
    telegram = document.get("telegram")
    if isinstance(telegram, str) and telegram.strip():
        found.append(telegram.strip())
    elif isinstance(telegram, dict):
        for field in ("chat_id", "username", "id"):
            value = str(telegram.get(field) or "").strip()
            if value:
                found.append(value)
    return found


def destination_chats() -> list[str]:
    """Chats administrativos; las cuentas reciben envíos personalizados."""
    chats: list[str] = []
    for raw in (os.environ.get("TELEGRAM_CHAT_ID"), load_channels().get("telegram_chat_id")):
        text = str(raw or "").strip()
        if text and text not in chats:
            chats.append(text)
    return chats


def send_to_user(user_document: dict[str, Any], text: str, image_url: str | None = None) -> bool:
    """Telegram solo a esta cuenta. No usa el chat global ni el resto de usuarios."""
    token = _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip()
    chats = [_resolve_chat(token, chat) for chat in _chat_values(user_document or {})]
    chats = list(dict.fromkeys(chat for chat in chats if chat))
    if not token or not chats or not str(text or "").strip():
        return False
    sent = False
    for chat in chats:
        if _send_telegram(token, chat, text, image_url=image_url):
            sent = True
    return sent


def dispatch_user_alerts(
    alerts: list[Alert], users: list[dict[str, Any]], *, repo: Any | None = None,
) -> int:
    """Envía solo las alertas que coinciden con la selección de cada cuenta."""
    from retail.notification_preferences import wants_alert

    delivered = 0
    for user in users:
        preferences = user.get("notification_preferences") or {}
        channels = preferences.get("channels") or []
        seen: set[str] = set()
        for alert in deduplicate_product_alerts(alerts):
            if not wants_alert(preferences, alert):
                continue
            key = alert_entity_key(alert)
            if key in seen:
                continue
            seen.add(key)
            payload = attach_short_url(_payload(alert), repo)
            text = _notification_text(payload)
            user_id = str(user.get("_id") or user.get("id") or user.get("email") or "")
            if (
                "telegram" in channels
                and wants_alert(preferences, alert, channel="telegram")
                and _telegram_offer_allowed(alert)
            ):
                token = _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip()
                deliverable = bool(token) and any(
                    _resolve_chat(token, chat) for chat in _chat_values(user)
                )
                if deliverable:
                    claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                        user_id, "telegram", key, alert.price,
                    )
                    if claimed and send_to_user(user, text, image_url=alert.image_url):
                        delivered += 1
            email = str(user.get("email") or "").strip()
            if "email" in channels and email and wants_alert(preferences, alert, channel="email"):
                claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                    user_id, "email", key, alert.price,
                )
                if claimed and send_email(
                    email,
                    f"Oferta: {alert.name or alert.query}",
                    text,
                    html=product_email_html(payload, eyebrow="Oferta detectada"),
                ):
                    delivered += 1
            if (
                "push" in channels
                and user.get("push_subscriptions")
                and wants_alert(preferences, alert, channel="push")
            ):
                claimed = not repo or not hasattr(repo, "claim_user_notification_send") or repo.claim_user_notification_send(
                    user_id, "push", key, alert.price,
                )
                if claimed:
                    from retail.web_push import send_user_push

                    if send_user_push(user, payload, repo=repo, tag=key):
                        delivered += 1
    return delivered


def _telegram_text(text: str, image_url: str | None = None) -> bool:
    token = _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip()
    excluded = {
        _resolve_chat(token, chat)
        for chat in _user_chats
        if token and chat
    }
    chats = list(dict.fromkeys(
        resolved
        for chat in destination_chats()
        if (resolved := _resolve_chat(token, chat)) and resolved not in excluded
    ))
    if not token or not chats:
        print("Telegram: sin token o sin chat guardado; no se envía.")
        return False
    sent = False
    for chat in chats:
        if _send_telegram(token, chat, text, image_url=image_url):
            sent = True
    return sent


def saved_notice_chat(user_document: dict[str, Any] | None = None) -> str:
    """Un solo chat por prueba: canales, luego la cuenta, luego TELEGRAM_CHAT_ID."""
    for raw in (
        load_channels().get("telegram_chat_id"),
        *_chat_values(user_document or {}),
        os.environ.get("TELEGRAM_CHAT_ID"),
    ):
        text = str(raw or "").strip()
        if text:
            return text
    return ""


def send_telegram_test(user_document: dict[str, Any] | None = None) -> dict[str, Any]:
    """Un mensaje de prueba al chat guardado. No incluye token ni chat en el resultado."""
    token = _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip()
    if not token:
        return {"ok": False, "error": "Falta el token del bot de Telegram."}
    chat = saved_notice_chat(user_document)
    if not chat:
        return {"ok": False, "error": "No hay chat de Telegram guardado."}
    ok, detail = _send_telegram_result(
        token,
        chat,
        "Prueba de aviso de Precios.\nSi lees esto, Telegram está bien configurado.",
    )
    if ok:
        return {"ok": True, "message": "Mensaje de prueba enviado por Telegram."}
    return {"ok": False, "error": _public_telegram_error(detail, token)}


def send_email_test(to_addr: str) -> dict[str, Any]:
    """Un correo de prueba. Si no hay destinatario, usa el de la prueba. No incluye claves."""
    recipient = str(to_addr or "").strip() or DEFAULT_NOTICE_TEST_EMAIL
    if not _secret("SMTP_HOST", "smtp_host"):
        return {"ok": False, "error": "Falta configurar SMTP."}
    sample = {
        "name": "Producto de ejemplo",
        "store": "lider",
        "product_id": "ejemplo",
        "price": 99990,
        "previous_price": 129990,
        "saving": 30000,
        "message": "Este es un correo de prueba. Las alertas reales mostrarán aquí el motivo del aviso.",
        "extra": {"product_id": "ejemplo", "store_title": "Tienda de ejemplo"},
    }
    sent = send_email(
        recipient,
        "Prueba de aviso de Precios",
        "Este es un correo de prueba. Si lo recibes, el aviso por correo está bien configurado.",
        html=product_email_html(sample, eyebrow="Prueba de notificación", heading="Correo correctamente configurado"),
    )
    if sent:
        return {"ok": True, "message": "Correo de prueba enviado a tu cuenta."}
    return {"ok": False, "error": "No se pudo enviar el correo. Revisa la configuración SMTP."}


def _send_telegram(token: str, chat: str, text: str, image_url: str | None = None) -> bool:
    ok, _detail = _send_telegram_result(token, chat, text, image_url=image_url)
    return ok


def _telegram_caption(text: str, limit: int = 1024) -> str:
    """Una sola leyenda por producto, conservando el enlace de la ficha."""
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean
    link = next((line for line in reversed(clean.splitlines()) if line.startswith("🔗 ")), "")
    suffix = f"\n{link}" if link else ""
    room = max(1, limit - len(suffix) - 1)
    return f"{clean[:room].rstrip()}…{suffix}"[:limit]


def _send_telegram_result(
    token: str,
    chat: str,
    text: str,
    image_url: str | None = None,
) -> tuple[bool, str]:
    resolved = _resolve_chat(token, chat)
    if not resolved:
        return False, "No se pudo resolver el chat de Telegram."
    if image_url:
        caption = _telegram_caption(text)
        payload = _telegram_api(token, "sendPhoto", {"chat_id": resolved, "photo": image_url, "caption": caption})
        if not payload.get("ok"):
            detail = str(payload.get("description") or payload.get("error") or "sin respuesta")
            print(f"Telegram: la imagen no se pudo enviar ({detail}); se intenta solo texto.")
            payload = _telegram_api(
                token,
                "sendMessage",
                {"chat_id": resolved, "text": text, "disable_web_page_preview": "true"},
            )
    else:
        payload = _telegram_api(token, "sendMessage", {"chat_id": resolved, "text": text, "disable_web_page_preview": "true"})
    if payload.get("ok"):
        return True, ""
    detail = str(payload.get("description") or payload.get("error") or "sin respuesta")
    print(f"Telegram no envió: {detail}")
    return False, detail


def _public_telegram_error(detail: str, token: str) -> str:
    text = str(detail or "")
    if token and token in text:
        text = text.replace(token, "")
    lowered = text.lower()
    if "unauthorized" in lowered or ("token" in lowered and "bot" in lowered):
        return "Telegram no aceptó el token."
    if "chat not found" in lowered or "peer" in lowered or "resolver el chat" in lowered:
        return "Telegram no reconoció el chat guardado."
    if "api.telegram.org" in lowered or "bot" in lowered:
        return "No se pudo enviar el mensaje de Telegram."
    return "No se pudo enviar el mensaje de Telegram."


def _resolve_chat(token: str, chat: str) -> str:
    raw = str(chat or "").strip()
    if not raw:
        return ""
    if raw.lstrip("-").isdigit():
        return raw
    cached = _resolved_chats.get(raw.lower())
    if cached:
        return cached
    if raw.lower() in _unresolved_chats:
        return ""
    username = raw if raw.startswith("@") else f"@{raw}"
    payload = _telegram_api(token, "getChat", {"chat_id": username})
    chat_id = str((payload.get("result") or {}).get("id") or "")
    if not chat_id:
        detail = payload.get("description") or payload.get("error") or "sin id"
        print(f"Telegram: no se pudo resolver el @usuario guardado ({detail})")
        _unresolved_chats.add(raw.lower())
        return ""
    _resolved_chats[raw.lower()] = chat_id
    print("Telegram: @usuario guardado resuelto al id del chat.")
    return chat_id


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """api.telegram.org a veces resuelve IPv6 y el contenedor responde 'network unreachable'."""

    def connect(self) -> None:
        infos = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        if not infos:
            raise OSError(f"sin IPv4 para {self.host}")
        sock = socket.create_connection(infos[0][4], self.timeout)
        context = self._context or ssl.create_default_context()
        self.sock = context.wrap_socket(sock, server_hostname=self.host)


def _telegram_api(token: str, method: str, params: dict[str, str]) -> dict[str, Any]:
    body = urlencode(params).encode()
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with _ipv4_open(request) as response:
            raw = response.read()
    except HTTPError as exc:
        parsed = _json_or_empty(exc.read())
        parsed.setdefault("ok", False)
        parsed.setdefault("description", f"HTTP {exc.code}")
        return parsed
    except URLError as exc:
        return {"ok": False, "error": str(exc.reason)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    parsed = _json_or_empty(raw)
    if not parsed:
        return {"ok": False, "error": "respuesta vacía"}
    return parsed


def _ipv4_open(request: Request):
    """Abre api.telegram.org por IPv4 con timeout.

    `HTTPSHandler.do_open` arma la conexión con `timeout=req.timeout`. Un
    `urllib.request.Request` no trae ese atributo (de ahí el error
    `'Request' object has no attribute 'timeout'` al resolver @usuario).
    Tampoco se puede pasar `timeout=` aquí: do_open lo reenvía otra vez y
    choca con `timeout=req.timeout`.
    """
    request.timeout = 20
    return HTTPSHandler().do_open(_IPv4HTTPSConnection, request)


def _json_or_empty(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def reales_digest_text(cards: list[dict[str, Any]], *, title: str, top: int = 25) -> str:
    lineas = [f"{title} · {len(cards)} ofertas reales"]
    for card in cards[:top]:
        gap = card.get("gap")
        ahorro = f"−{_money(gap)} " if gap else ""
        name = str(card.get("name") or "sin nombre")[:58]
        store = card.get("store") or ""
        rival = card.get("rival_store") or ""
        ficha = product_page_url(card.get("store"), card.get("product_id"))
        lineas.append("")
        lineas.append(f"• {ahorro}{name}")
        lineas.append(f"  {store} {_money(card.get('price'))} vs {rival}" + (f" · {ficha}" if ficha else ""))
    restantes = len(cards) - min(len(cards), top)
    if restantes > 0:
        lineas.append("")
        lineas.append(f"y {restantes} más en {PUBLIC_REALES}")
    elif cards:
        lineas.append("")
        lineas.append(PUBLIC_REALES)
    return "\n".join(lineas)[:TELEGRAM_LIMIT]


def notify_real_offers(repo: Any, *, title: str, top: int = 25, state_path: Path = REALES_STATE) -> int:
    """Comparte con las otras ofertas la reserva de Telegram por producto/precio."""
    if not _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip() or not destination_chats():
        print("Telegram: sin token o sin chat guardado; no se envían ofertas reales.")
        return 0
    found = repo.real_offers(comparacion=True, historial=True, iguales=False, page=1, size=80)
    cards = [
        item for item in (found.get("items") or [])
        if item and _real_discount(item) >= TELEGRAM_MIN_DISCOUNT
    ]
    persistent_history = hasattr(repo, "claim_user_notification_send")
    legacy_keys, sent_entities = _load_real_state(state_path) if not persistent_history else (set(), set())
    fresh = [
        card for card in cards
        if _real_entity_key(card) not in sent_entities and _legacy_real_key(card) not in legacy_keys
    ]
    if not fresh:
        return 0
    delivered_keys: set[str] = set()
    for card in fresh[:top]:
        if persistent_history and not repo.claim_user_notification_send(
            "global", "telegram", _real_entity_key(card), card.get("price"),
        ):
            continue
        name = str(card.get("name") or "Producto")
        price = _money(card.get("price"))
        normal = card.get("price_normal")
        lines = [f"🔔 {name}", f"🏬 {card.get('store') or 'Tienda'}", f"💰 Precio actual: {price}"]
        if card.get("discount"):
            lines.append(f"🏷️ Descuento: {float(card['discount']):.0f}%" + (f" · antes {_money(normal)}" if normal else ""))
        lines.append(f"🆚 {card.get('rival_store') or 'Otra tienda'}: {_money(card.get('rival_price'))} · {float(card.get('gap_percent') or 0):.0f}% más barato")
        if card.get("gap"):
            lines.append(f"💸 Ahorras {_money(card['gap'])} frente a la otra tienda")
        ficha = short_product_url(repo, card.get("store"), card.get("product_id"))
        if ficha:
            lines.append(f"🔗 Ficha: {ficha}")
        image_url = None
        if card.get("has_thumb") and card.get("store") and card.get("product_id"):
            image_url = f"{PUBLIC_REALES.rsplit('/reales', 1)[0]}/api/thumb?{urlencode({'store': card['store'], 'id': card['product_id']})}"
        if _telegram_text("\n".join(lines), image_url=image_url):
            delivered_keys.add(_real_entity_key(card))
    if delivered_keys and not persistent_history:
        _save_real_entities(state_path, delivered_keys)
    print(f"Telegram: {len(delivered_keys)} ofertas reales enviadas ({len(fresh)} nuevas).")
    return len(delivered_keys)


def _real_discount(card: dict[str, Any]) -> float:
    values = (
        card.get("discount"), card.get("published_discount"),
        card.get("verified_discount"), card.get("gap_percent"),
    )
    clean: list[float] = []
    for value in values:
        try:
            if value is not None:
                clean.append(float(value))
        except (TypeError, ValueError):
            continue
    return max(clean, default=0.0)


def _real_entity_key(card: dict[str, Any]) -> str:
    code = str(card.get("compare_code") or "").strip()
    if code:
        return code
    product_id = str(card.get("product_id") or "").strip()
    if product_id:
        return f"product:{card.get('store') or ''}:{product_id}"
    return "name:" + " ".join(str(card.get("name") or "").casefold().split())


def _legacy_real_key(card: dict[str, Any]) -> str:
    return "|".join(
        [
            str(card.get("compare_code") or card.get("name") or ""),
            str(card.get("store") or ""),
            str(card.get("price") or ""),
        ]
    )


def _load_real_state(path: Path) -> tuple[set[str], set[str]]:
    if not path.exists():
        return set(), set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), set()
    return (
        {str(item) for item in (data.get("keys") or [])},
        {str(item) for item in (data.get("entities") or [])},
    )


def _save_real_entities(path: Path, entities: set[str]) -> None:
    legacy, current = _load_real_state(path)
    current.update(entities)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "keys": sorted(legacy)[-4000:],
            "entities": sorted(current)[-10000:],
        }, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _email(payload: dict[str, Any]) -> bool:
    subject = f"Oferta: {payload.get('name') or payload.get('query') or 'producto'}"
    text = _notification_text(payload)
    html = product_email_html(payload, eyebrow="Oferta detectada")
    return send_email(_secret("ALERT_EMAIL_TO", "alert_email_to"), subject, text, html=html)


def send_email(
    to_addr: str,
    subject: str,
    body: str,
    *,
    log_skip: bool = False,
    image_url: str | None = None,
    html: str | None = None,
) -> bool:
    """Manda un correo con el SMTP ya configurado. Sin host o sin destinatario, no envía."""
    host = _secret("SMTP_HOST", "smtp_host")
    recipient = str(to_addr or "").strip()
    if not host or not recipient:
        if log_skip:
            print("Correo de alerta de precio: SMTP no configurado; no se envía.")
        return False
    local = load_channels()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _secret("SMTP_FROM", "smtp_from") or _secret("SMTP_USER", "smtp_user") or "ofertas@localhost"
    message["To"] = recipient
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    elif image_url:
        html_body = escape(body).replace("\n", "<br>\n")
        safe_image = escape(str(image_url), quote=True)
        message.add_alternative(
            f'<html><body><img src="{safe_image}" alt="Producto" '
            f'style="display:block;max-width:420px;max-height:420px;object-fit:contain;margin-bottom:16px">'
            f'<div>{html_body}</div></body></html>',
            subtype="html",
        )
    try:
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT") or local.get("smtp_port") or 587), timeout=20) as smtp:
            smtp.starttls()
            user = _secret("SMTP_USER", "smtp_user")
            password = _secret("SMTP_PASSWORD", "smtp_password")
            if user and password:
                smtp.login(user, password)
            smtp.send_message(message)
    except Exception as exc:
        print(f"Correo no envió la alerta: {exc}")
        return False
    return True


def _email_text(subject: str, body: str, image_url: str | None = None) -> None:
    host = _secret("SMTP_HOST", "smtp_host")
    to_addr = _secret("ALERT_EMAIL_TO", "alert_email_to")
    if not host or not to_addr:
        return
    send_email(to_addr, subject, body, image_url=image_url)
