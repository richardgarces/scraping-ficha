"""Capturas de página de oferta para adjuntar a Telegram/correo.

Solo se usa al enviar una alerta (no en cada scrape). Si Playwright/Chromium
no están instalados o falla la captura, se vuelve al `image_url` del producto.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from retail.short_links import public_product_url

DEFAULT_DIR = Path("output/offer_screenshots")
DEFAULT_TIMEOUT_MS = 15_000
DEFAULT_RETENTION_DAYS = 7
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def screenshots_enabled() -> bool:
    return os.environ.get("OFFER_SCREENSHOTS", "").strip().lower() in {"1", "true", "yes", "on"}


def screenshot_timeout_ms() -> int:
    raw = os.environ.get("OFFER_SCREENSHOT_TIMEOUT_MS") or str(DEFAULT_TIMEOUT_MS)
    try:
        return max(1_000, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_MS


def retention_days() -> int:
    raw = os.environ.get("OFFER_SCREENSHOT_RETENTION_DAYS") or str(DEFAULT_RETENTION_DAYS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_RETENTION_DAYS


def storage_dir() -> Path:
    return Path(os.environ.get("OFFER_SCREENSHOT_DIR") or DEFAULT_DIR)


def is_local_image(value: Any) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith(("http://", "https://", "cid:", "data:")):
        return False
    path = Path(text)
    return path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}


def page_url_for_offer(payload: dict[str, Any] | None = None, **fields: Any) -> str:
    """Prefiere la URL de la tienda; si falta, la ficha pública."""
    data = {**(payload or {}), **fields}
    for key in ("url", "product_url", "store_url"):
        candidate = _http_url(data.get(key))
        if candidate:
            return candidate
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    store = str(extra.get("store") or data.get("store") or "").strip()
    product_id = str(
        extra.get("product_id") or data.get("product_id") or data.get("id") or ""
    ).strip()
    return public_product_url(store, product_id)


def resolve_alert_image(
    payload: dict[str, Any] | None = None,
    *,
    image_url: str | None = None,
    page_url: str | None = None,
    store: str | None = None,
    product_id: str | None = None,
) -> str | None:
    """Devuelve ruta local de captura o el image_url original. Nunca lanza."""
    data = dict(payload or {})
    if image_url is not None:
        data["image_url"] = image_url
    if page_url is not None:
        data["url"] = page_url
    if store is not None:
        data["store"] = store
    if product_id is not None:
        data["product_id"] = product_id
    fallback = str(data.get("image_url") or "").strip() or None
    try:
        captured = capture_offer_screenshot(data)
    except Exception as exc:
        print(f"Captura de oferta: error inesperado ({exc}); se usa image_url.")
        return fallback
    return captured or fallback


def apply_offer_screenshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Si hay captura, reemplaza `image_url` por la ruta local. No altera push."""
    if not isinstance(payload, dict):
        return payload
    resolved = resolve_alert_image(payload)
    if resolved:
        payload["image_url"] = resolved
    return payload


def capture_offer_screenshot(payload: dict[str, Any]) -> str | None:
    """Captura PNG de la página de oferta. None si está desactivado o falla."""
    if not screenshots_enabled():
        return None
    target = page_url_for_offer(payload)
    if not target:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Captura de oferta: Playwright no instalado; se omite.")
        return None

    cleanup_old_screenshots()
    dest = _destination_path(payload, target)
    dest.parent.mkdir(parents=True, exist_ok=True)
    timeout = screenshot_timeout_ms()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 720})
                page.goto(target, wait_until="domcontentloaded", timeout=timeout)
                page.wait_for_timeout(min(1_500, timeout // 4))
                page.screenshot(path=str(dest), full_page=False, type="png")
            finally:
                browser.close()
    except Exception as exc:
        print(f"Captura de oferta: falló ({exc}); se usa image_url.")
        try:
            if dest.exists():
                dest.unlink()
        except OSError:
            pass
        return None
    if not dest.is_file() or dest.stat().st_size < 100:
        return None
    return str(dest)


def cleanup_old_screenshots(*, now: float | None = None) -> int:
    """Borra capturas más viejas que OFFER_SCREENSHOT_RETENTION_DAYS. Devuelve cuántas."""
    root = storage_dir()
    if not root.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - retention_days() * 86_400
    removed = 0
    for path in root.glob("**/*"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def _http_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return text
    return ""


def _destination_path(payload: dict[str, Any], page_url: str) -> Path:
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    store = str(extra.get("store") or payload.get("store") or "store").strip() or "store"
    product_id = str(
        extra.get("product_id") or payload.get("product_id") or payload.get("id") or ""
    ).strip()
    stamp = time.strftime("%Y%m%d%H%M%S")
    base = product_id or _SAFE_NAME.sub("_", urlparse(page_url).path.strip("/")) or "offer"
    name = _SAFE_NAME.sub("_", f"{store}_{base}_{stamp}")[:120]
    return storage_dir() / f"{name}.png"
