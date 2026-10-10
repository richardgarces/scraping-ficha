"""Capturas de página de oferta para adjuntar a Telegram/correo.

Solo se usa al enviar una alerta (no en cada scrape). Si Playwright/Chromium
no están instalados, falla la captura o la página es una comprobación antibot,
se intenta una captura verificada mediante FlareSolverr si está configurado.
Si el respaldo falla, se vuelve al `image_url` del producto.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import os
import re
import threading
import time
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from retail.short_links import public_product_url

DEFAULT_DIR = Path("output/offer_screenshots")
DEFAULT_TIMEOUT_MS = 15_000
DEFAULT_RETENTION_DAYS = 7
# Documento en Mongo `app_settings`. Si no existe, manda OFFER_SCREENSHOTS.
SETTING_KEY = "offer_screenshots"
# Un documento por tienda en la misma colección: `_id` = `store:<id>`.
STORE_BOT_CHECK_PREFIX = "store:"
_CACHE_SECONDS = 30.0
_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
_UNREADABLE = object()
_cache_lock = threading.Lock()
_cache_known = False
_cache_value: bool | None = None
_cache_until = 0.0


def env_screenshots_enabled() -> bool:
    return os.environ.get("OFFER_SCREENSHOTS", "").strip().lower() in {"1", "true", "yes", "on"}


def clear_screenshots_setting_cache() -> None:
    global _cache_known, _cache_value, _cache_until
    with _cache_lock:
        _cache_known = False
        _cache_value = None
        _cache_until = 0.0


def _remember_screenshots_setting(value: bool | None) -> None:
    global _cache_known, _cache_value, _cache_until
    with _cache_lock:
        _cache_known = True
        _cache_value = value
        _cache_until = time.monotonic() + _CACHE_SECONDS


def _cached_screenshots_setting() -> bool | None:
    with _cache_lock:
        if _cache_known and time.monotonic() < _cache_until:
            return _cache_value
    return None


def _coerce_enabled(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    return None


def _enabled_from_setting(document: Any) -> bool | None:
    """None si el documento no trae un enabled interpretable."""
    if not isinstance(document, dict) or "enabled" not in document:
        return None
    return _coerce_enabled(document.get("enabled"))


def load_stored_screenshots_enabled(repo: Any = None) -> Any:
    """Lee `app_settings.offer_screenshots`.

    Devuelve True/False si hay valor guardado, None si no hay documento
    (o no trae `enabled`) y `_UNREADABLE` si Mongo no responde.
    """
    owns = repo is None
    store = repo
    if store is None:
        try:
            from retail.search import connect_repo

            store = connect_repo()
        except Exception:
            return _UNREADABLE
    if store is None or not hasattr(store, "get_app_setting"):
        return _UNREADABLE
    try:
        found = store.get_app_setting(SETTING_KEY)
    except Exception:
        return _UNREADABLE
    finally:
        if owns:
            try:
                store.close()
            except Exception:
                pass
    return _enabled_from_setting(found)


def stored_screenshots_enabled(repo: Any = None) -> bool | None:
    """Override de Mongo, o None para seguir el env. Caché corta por proceso."""
    if repo is not None:
        loaded = load_stored_screenshots_enabled(repo)
        if loaded is _UNREADABLE:
            return _cached_screenshots_setting()
        _remember_screenshots_setting(loaded)
        return loaded
    cached = _cached_screenshots_setting()
    if _cache_known and time.monotonic() < _cache_until:
        return cached
    loaded = load_stored_screenshots_enabled(None)
    if loaded is _UNREADABLE:
        with _cache_lock:
            if _cache_known:
                return _cache_value
        return None
    _remember_screenshots_setting(loaded)
    return loaded


def screenshots_enabled() -> bool:
    """Mongo apaga o prende aunque el env diga lo contrario.

    Sin documento guardado (o si Mongo no responde y no hay caché), vale
    `OFFER_SCREENSHOTS`. Playwright se comprueba después, al capturar.
    """
    stored = stored_screenshots_enabled()
    if stored is None:
        return env_screenshots_enabled()
    return stored


def offer_screenshot_status(repo: Any = None) -> dict[str, Any]:
    stored = stored_screenshots_enabled(repo) if repo is not None else stored_screenshots_enabled()
    if stored is None:
        return {"enabled": env_screenshots_enabled(), "source": "env"}
    return {"enabled": stored, "source": "database"}


def save_offer_screenshots_enabled(enabled: bool, repo: Any) -> dict[str, Any]:
    if repo is None or not hasattr(repo, "save_app_setting"):
        raise RuntimeError("MongoDB no está disponible para guardar las capturas.")
    flag = bool(enabled)
    repo.save_app_setting(SETTING_KEY, {"enabled": flag})
    clear_screenshots_setting_cache()
    _remember_screenshots_setting(flag)
    return {"enabled": flag, "source": "database"}


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


# Solo el archivo de una captura, nunca el listado del directorio.
OFFER_SHOT_PREFIX = "/offer-shots"
_SHOT_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.(?:png|jpe?g|webp)$")
_SHOT_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def offer_shot_path(name: str) -> Path | None:
    """Ruta de una captura guardada, si el nombre es un archivo de ese directorio."""
    text = str(name or "")
    if text != Path(text).name or ".." in text or not _SHOT_FILE.fullmatch(text):
        return None
    root = storage_dir().resolve()
    candidate = (root / text).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.parent != root or not candidate.is_file():
        return None
    return candidate


def offer_shot_media_type(path: Path) -> str:
    return _SHOT_MIME.get(path.suffix.lower(), "application/octet-stream")


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


def _ripley_product_photo(data: dict[str, Any], fallback: str | None) -> str | None:
    """Descarga la foto con identidad de navegador para adjuntarla por multipart."""
    if not fallback or _store_id(data) != "ripley":
        return fallback
    parsed = urlparse(fallback)
    if parsed.scheme != "https" or parsed.hostname != "rimage.ripley.cl":
        return fallback
    dest = storage_dir() / ("ripley_photo_" + hashlib.sha256(fallback.encode()).hexdigest()[:24] + ".jpg")
    try:
        if dest.is_file() and time.time() - dest.stat().st_mtime < 24 * 3600:
            return str(dest)
        from curl_cffi import requests
        from PIL import Image

        with requests.Session(impersonate="chrome", trust_env=False) as session:
            reply = session.get(fallback, headers={"Referer": page_url_for_offer(data)}, timeout=20)
            reply.raise_for_status()
            with Image.open(io.BytesIO(reply.content)) as image:
                image.load()
                dest.parent.mkdir(parents=True, exist_ok=True)
                temporary = dest.with_suffix(".tmp")
                image.convert("RGB").save(temporary, format="JPEG", quality=90)
                temporary.replace(dest)
        return str(dest)
    except Exception as exc:
        print(f"Foto de producto Ripley: no se pudo descargar ({exc}); se conserva image_url.")
        return fallback


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
        return _ripley_product_photo(data, fallback)
    return captured or _ripley_product_photo(data, fallback)


def apply_offer_screenshot(payload: dict[str, Any]) -> dict[str, Any]:
    """Si hay captura válida, reemplaza `image_url` por la ruta local.

    Una comprobación antibot no se guarda: queda el `image_url` del producto.
    El push no usa la ruta local; publica la captura solo si el sitio la sirve.
    """
    if not isinstance(payload, dict):
        return payload
    resolved = resolve_alert_image(payload)
    if resolved:
        payload["image_url"] = resolved
    return payload


def screenshot_item_key(payload: dict[str, Any], *, explicit: str | None = None) -> str:
    """Clave estable para deduplicar capturas en un lote."""
    if explicit:
        return str(explicit)
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    store = str(extra.get("store") or payload.get("store") or "").strip().lower()
    product_id = str(
        extra.get("product_id") or payload.get("product_id") or payload.get("id") or ""
    ).strip()
    if store and product_id:
        return f"{store}:{product_id}"
    target = page_url_for_offer(payload)
    if target:
        return "url:" + hashlib.sha1(target.encode("utf-8")).hexdigest()[:20]
    return "anon:" + hashlib.sha1(repr(sorted(payload.items())).encode("utf-8")).hexdigest()[:16]


def apply_offer_screenshots(
    payloads_by_key: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Captura en un solo browser y aplica `image_url` local por clave.

    Pensado para el fan-out de alertas: reunir payloads únicos, llamar una vez,
    luego enviar. Si la captura falla, conserva la foto del producto (Ripley
    puede materializar una copia local).
    """
    if not payloads_by_key:
        return payloads_by_key
    keys = list(payloads_by_key.keys())
    payloads = [payloads_by_key[key] for key in keys]
    paths = capture_offer_screenshots_batch(payloads, keys=keys)
    for key in keys:
        payload = payloads_by_key[key]
        if not isinstance(payload, dict):
            continue
        fallback = str(payload.get("image_url") or "").strip() or None
        captured = paths.get(key)
        if captured:
            payload["image_url"] = captured
        else:
            resolved = _ripley_product_photo(payload, fallback)
            if resolved:
                payload["image_url"] = resolved
    return payloads_by_key


# Marcadores del HTML de la intersticial. Un widget Turnstile o el script
# pasivo /scripts/jsd/main.js no bastan: hace falta la página de comprobación.
_STRUCTURAL_MARKERS = (
    "cf-browser-verification",
    "cf-challenge-running",
    "cf-im-under-attack",
    "_cf_chl_opt",
    "cf-chl-widget",
    'id="challenge-running"',
    'id="challenge-stage"',
    'id="challenge-form"',
    'id="cf-challenge-running"',
    'id="cf-wrapper"',
    'id="cf-stage"',
    "managed-challenge",
)
_TITLE_CONTAINS = (
    "just a moment",
    "checking your browser",
    "attention required",
    "verify you are human",
    "verifying you are human",
    "are you human",
    "are you a human",
    "comprobando tu navegador",
    "comprobando su navegador",
    "comprobando si la conexión",
    "verifica que eres",
    "verifique que usted",
    "enable javascript and cookies",
    "performing security verification",
    "why have i been blocked",
    "sorry, you have been blocked",
    "one more step",
)
_TITLE_PREFIXES = ("un momento", "one moment")
_BODY_PHRASES = (
    "checking your browser",
    "verify you are human",
    "verifying you are human",
    "are you human",
    "are you a human",
    "enable javascript and cookies to continue",
    "performing security verification",
    "checking if the site connection is secure",
    "comprobando tu navegador",
    "comprobando su navegador",
    "comprobando si la conexión del sitio es segura",
    "verifica que eres humano",
    "verifique que usted es un ser humano",
    "why have i been blocked",
    "sorry, you have been blocked",
    "one more step before you proceed",
)
# PerimeterX/HUMAN usa esta variante en sitios Walmart. Las frases sueltas no
# bastan: se exige una combinación entre ellas o texto + marcador del proveedor.
_HOLD_CHALLENGE_COPY = (
    "robot or human",
    "activate and hold",
    "press & hold",
    "press and hold",
    "confirm that you're human",
    "confirm that you are human",
)
_PERIMETERX_MARKERS = (
    "px-captcha",
    "captcha.px-cdn.net",
    "_pxcaptcha",
    "_pxappid",
    "perimeterx",
    "humansecurity",
    "human security",
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_JUST_A_MOMENT_RE = re.compile(r"just a moment(?!\s+ago)\b")
_RAY_ID_RE = re.compile(r"ray id\s*[:<]")


def _title_from_html(html: str) -> str:
    match = _TITLE_RE.search(html)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip().lower()


def _bare_moment_title(title: str) -> bool:
    """«Un momento…» de Cloudflare, no un nombre de producto que empiece igual."""
    for prefix in _TITLE_PREFIXES:
        if not title.startswith(prefix):
            continue
        rest = title[len(prefix):].strip(" .…!¡")
        return rest == "" or "cloudflare" in title
    return False


def _title_is_challenge(title: str) -> bool:
    if not title:
        return False
    if any(phrase in title for phrase in _TITLE_CONTAINS):
        return True
    return _bare_moment_title(title)


def _body_has_challenge_copy(head: str) -> bool:
    if _JUST_A_MOMENT_RE.search(head):
        return True
    return any(phrase in head for phrase in _BODY_PHRASES)


def _blocking_turnstile(html: str, title: str) -> bool:
    """Turnstile de la intersticial, no el widget de un formulario."""
    if "cf-turnstile" not in html and "challenges.cloudflare.com/turnstile" not in html:
        return False
    if _title_is_challenge(title) or _body_has_challenge_copy(html[:8_000]):
        return True
    return any(marker in html for marker in ('id="cf-stage"', 'id="challenge-stage"', 'id="cf-wrapper"', "_cf_chl_opt"))


def _hold_challenge_provider(content: str) -> str:
    if any(marker in content for marker in _PERIMETERX_MARKERS):
        return "perimeterx"
    return ""


def _hold_challenge(content: str, title: str) -> bool:
    """Detecta PRESS & HOLD solo con contexto suficiente para evitar falsos positivos."""
    found = {phrase for phrase in _HOLD_CHALLENGE_COPY if phrase in content}
    title_says_robot = "robot or human" in title
    provider = _hold_challenge_provider(content)
    has_hold_action = bool({"activate and hold", "press & hold", "press and hold"} & found)
    has_human_confirmation = bool(
        {"robot or human", "confirm that you're human", "confirm that you are human"} & found
    )
    return (
        (has_hold_action and has_human_confirmation)
        or (title_says_robot and has_hold_action)
        or (bool(provider) and (has_hold_action or title_says_robot))
    )


def bot_check_provider(
    html: str | None,
    title: str | None = None,
    text_content: str | None = None,
) -> str:
    """Proveedor conocido de la intersticial; vacío si no se puede atribuir."""
    content = " ".join((str(html or ""), str(title or ""), str(text_content or ""))).lower()
    if _hold_challenge_provider(content):
        return "perimeterx"
    if "cloudflare" in content or any(marker in content for marker in _STRUCTURAL_MARKERS):
        return "cloudflare"
    return ""


def _ripley_block_page(content: str, title: str) -> bool:
    """Reconoce el bloqueo personalizado de Ripley con dos señales de contexto."""
    if title.strip() == "error en ripley.com | blocked":
        return True
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(content))).lower()
    return "alto, no puedes acceder" in text and (
        "por qué me han bloqueado" in text
        or "desencadenó la solución de seguridad" in text
    )


def is_bot_check_page(
    html: str | None,
    title: str | None = None,
    text_content: str | None = None,
) -> bool:
    """True si el HTML o el título son una intersticial de comprobación antibot.

    No intenta resolverla. Un aviso de Cloudflare Insights o un Turnstile
    embebido en la ficha no cuentan.
    """
    lowered = str(html or "").lower()
    page_title = re.sub(r"\s+", " ", str(title or "")).strip().lower()
    rendered_text = re.sub(r"\s+", " ", str(text_content or "")).strip().lower()
    if not page_title:
        page_title = _title_from_html(lowered)
    if _ripley_block_page(lowered + " " + rendered_text, page_title):
        return True
    combined = " ".join((lowered[:16_000], rendered_text[:8_000]))
    if _hold_challenge(combined, page_title):
        return True
    if _title_is_challenge(page_title):
        return True
    if any(marker in lowered for marker in _STRUCTURAL_MARKERS):
        return True
    head = lowered[:8_000]
    if _body_has_challenge_copy(head):
        return True
    if _blocking_turnstile(lowered, page_title):
        return True
    return "cloudflare" in head and _RAY_ID_RE.search(head) is not None


def _iso_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    text = str(value or "").strip()
    if text.lower() in {"none", "null"}:
        return ""
    return text


def store_bot_check_key(store_id: str) -> str:
    return f"{STORE_BOT_CHECK_PREFIX}{str(store_id or '').strip().lower()}"


def mark_store_bot_check(
    repo: Any,
    store_id: str,
    *,
    seen_at: datetime | None = None,
    provider: str | None = None,
) -> dict[str, Any] | None:
    """Deja `bot_check` en el documento `app_settings` `_id` = `store:<id>`."""
    store = str(store_id or "").strip().lower()
    if not store or repo is None or not hasattr(repo, "save_app_setting"):
        return None
    when = seen_at or datetime.now(timezone.utc)
    payload = {"bot_check": True, "bot_check_last_seen_at": when}
    clean_provider = str(provider or "").strip().lower()
    if clean_provider:
        payload["bot_check_provider"] = clean_provider
    repo.save_app_setting(store_bot_check_key(store), payload)
    return {"store": store, **payload}


def bot_checks_from_documents(documents: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    for document in documents or []:
        if not isinstance(document, dict) or not document.get("bot_check"):
            continue
        key = str(document.get("_id") or "")
        if not key.startswith(STORE_BOT_CHECK_PREFIX):
            continue
        store = key[len(STORE_BOT_CHECK_PREFIX):].strip().lower()
        if not store:
            continue
        found[store] = _iso_timestamp(document.get("bot_check_last_seen_at")) or _iso_timestamp(
            document.get("updated_at")
        )
    return found


def list_store_bot_checks(repo: Any) -> dict[str, str]:
    settings = getattr(repo, "app_settings", None)
    if settings is None or not hasattr(settings, "find"):
        return {}
    try:
        documents = settings.find({"bot_check": True})
    except Exception:
        return {}
    return bot_checks_from_documents(documents)


def annotate_store_bot_checks(rows: list[dict[str, Any]], checks: dict[str, str]) -> list[dict[str, Any]]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        store = str(row.get("store") or "").strip().lower()
        if store not in checks:
            continue
        row["bot_check"] = True
        if checks[store]:
            row["bot_check_last_seen_at"] = checks[store]
    return rows


def bot_check_api_rows(checks: dict[str, str]) -> list[dict[str, Any]]:
    from retail.store_display import public_store_label

    return [
        {
            "store": store,
            "store_title": public_store_label(store),
            "last_seen_at": seen,
            "bot_check": True,
        }
        for store, seen in sorted(checks.items())
    ]


def _store_id(payload: dict[str, Any] | None) -> str:
    data = payload or {}
    extra = data.get("extra") if isinstance(data.get("extra"), dict) else {}
    return str(extra.get("store") or data.get("store") or "").strip().lower()


def note_store_bot_check(
    payload: dict[str, Any] | None,
    *,
    repo: Any = None,
    provider: str | None = None,
) -> None:
    """Marca la tienda. Si Mongo no responde, la captura igual se descarta."""
    store_id = _store_id(payload)
    if not store_id:
        return
    owns = repo is None
    store = repo
    try:
        if store is None:
            from retail.search import connect_repo

            store = connect_repo()
        if store is None:
            return
        mark_store_bot_check(store, store_id, provider=provider)
    except Exception as exc:
        print(f"Captura de oferta: no se pudo marcar la comprobación antibot ({exc}).")
    finally:
        if owns and store is not None:
            try:
                store.close()
            except Exception:
                pass


def _bot_check_from_parts(title: str, html: str, text_content: str) -> tuple[bool, str]:
    if not any(str(value or "").strip() for value in (title, html, text_content)):
        return False, ""
    blocked = is_bot_check_page(html, title, text_content)
    provider = bot_check_provider(html, title, text_content) if blocked else ""
    return blocked, provider


def _page_bot_check_details(page: Any) -> tuple[bool, str]:
    title = ""
    html = ""
    text_content = ""
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        html = page.content()
    except Exception:
        html = ""
    try:
        text_content = page.locator("body").inner_text(timeout=1_000)
    except Exception:
        try:
            text_content = page.evaluate(
                "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''"
            )
        except Exception:
            text_content = ""
    return _bot_check_from_parts(title, html, text_content)


async def _page_bot_check_details_async(page: Any) -> tuple[bool, str]:
    title = ""
    html = ""
    text_content = ""
    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        html = await page.content()
    except Exception:
        html = ""
    try:
        text_content = await page.locator("body").inner_text(timeout=1_000)
    except Exception:
        try:
            text_content = await page.evaluate(
                "() => document.body ? (document.body.innerText || document.body.textContent || '') : ''"
            )
        except Exception:
            text_content = ""
    return _bot_check_from_parts(title, html, text_content)


def _page_is_bot_check(page: Any) -> bool:
    return _page_bot_check_details(page)[0]


def _discard_screenshot(dest: Path) -> None:
    try:
        if dest.exists():
            dest.unlink()
    except OSError:
        pass


def _capture_with_solver(target: str, dest: Path) -> bool:
    """Captura desde el mismo navegador que obtuvo el HTML validado."""
    endpoint = os.environ.get("FLARESOLVERR_URL")
    if not endpoint:
        return False
    try:
        from PIL import Image
        from retail.flaresolverr import solve

        solution = solve(target, endpoint, screenshot=True)
        content = base64.b64decode(solution.get("screenshot", ""), validate=True)
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "PNG":
                raise ValueError("FlareSolverr no devolvió una captura PNG")
            image.verify()
        dest.write_bytes(content)
        print("Captura de oferta: respaldo FlareSolverr verificado.")
        return True
    except Exception as exc:
        print(f"Captura de oferta: falló el respaldo FlareSolverr ({exc}).")
        _discard_screenshot(dest)
        return False


def _valid_shot_path(dest: Path) -> str | None:
    if dest.is_file() and dest.stat().st_size >= 100:
        return str(dest)
    return None


async def _capture_jobs_async(
    jobs: list[dict[str, Any]],
    *,
    timeout: int,
    parallel: int,
) -> tuple[dict[str, str | None], list[dict[str, Any]]]:
    """Un Chromium; hasta ``parallel`` pages a la vez. FlareSolverr queda fuera."""
    from playwright.async_api import async_playwright

    results: dict[str, str | None] = {job["key"]: None for job in jobs}
    solver_jobs: list[dict[str, Any]] = []
    gate = asyncio.Semaphore(max(1, parallel))

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:

            async def run_one(job: dict[str, Any]) -> None:
                async with gate:
                    page = await browser.new_page(viewport={"width": 1280, "height": 720})
                    try:
                        await page.goto(
                            job["target"],
                            wait_until="domcontentloaded",
                            timeout=timeout,
                        )
                        await page.wait_for_timeout(min(1_500, timeout // 4))
                        blocked, provider = await _page_bot_check_details_async(page)
                        if blocked:
                            _discard_screenshot(job["dest"])
                            solver_jobs.append({**job, "provider": provider})
                            return
                        await page.screenshot(
                            path=str(job["dest"]),
                            full_page=False,
                            type="png",
                        )
                        results[job["key"]] = _valid_shot_path(job["dest"])
                    except Exception as exc:
                        print(f"Captura de oferta: falló ({exc}); se usa image_url.")
                        _discard_screenshot(job["dest"])
                        results[job["key"]] = None
                    finally:
                        await page.close()

            await asyncio.gather(*(run_one(job) for job in jobs))
        finally:
            await browser.close()
    return results, solver_jobs


def _finish_solver_fallbacks(
    results: dict[str, str | None],
    solver_jobs: list[dict[str, Any]],
) -> dict[str, str | None]:
    """Respaldo FlareSolverr en serie tras cerrar Chromium (sin abrir otro frente)."""
    for job in solver_jobs:
        dest: Path = job["dest"]
        target: str = job["target"]
        payload: dict[str, Any] = job["payload"]
        provider = job.get("provider") or ""
        if _capture_with_solver(target, dest):
            results[job["key"]] = _valid_shot_path(dest)
            continue
        store_id = _store_id(payload) or "la tienda"
        print(
            f"Captura de oferta: {store_id} mostró una comprobación antibot; "
            "no se adjunta esa captura."
        )
        note_store_bot_check(payload, provider=provider)
        _discard_screenshot(dest)
        results[job["key"]] = None
    return results


def capture_offer_screenshots_batch(
    payloads: list[dict[str, Any]],
    *,
    keys: list[str] | None = None,
) -> dict[str, str | None]:
    """Captura varias ofertas con un solo ``chromium.launch``.

    Usa un slot Chromium compartido (Redis/in-process) y abre hasta
    ``RETAIL_CHROMIUM_CONCURRENCY`` pages en paralelo sobre ese browser.
    Devuelve ``clave → ruta PNG`` (o ``None`` si falló / está desactivado).
    """
    if not payloads:
        return {}
    if keys is not None and len(keys) != len(payloads):
        raise ValueError("keys debe tener la misma longitud que payloads")
    if not screenshots_enabled():
        out_keys = [
            keys[index] if keys is not None else screenshot_item_key(payload)
            for index, payload in enumerate(payloads)
        ]
        return {key: None for key in out_keys}

    try:
        from playwright.async_api import async_playwright  # noqa: F401
    except ImportError:
        print("Captura de oferta: Playwright no instalado; se omite.")
        out_keys = [
            keys[index] if keys is not None else screenshot_item_key(payload)
            for index, payload in enumerate(payloads)
        ]
        return {key: None for key in out_keys}

    from retail.concurrency import chromium_limit, chromium_slot

    cleanup_old_screenshots()
    timeout = screenshot_timeout_ms()
    parallel = chromium_limit()
    jobs: list[dict[str, Any]] = []
    seen: set[str] = set()
    results: dict[str, str | None] = {}

    for index, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            continue
        key = keys[index] if keys is not None else screenshot_item_key(payload)
        if key in seen:
            continue
        seen.add(key)
        target = page_url_for_offer(payload)
        if not target:
            results[key] = None
            continue
        dest = _destination_path(payload, target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        jobs.append(
            {
                "key": key,
                "payload": payload,
                "target": target,
                "dest": dest,
            }
        )

    if not jobs:
        return results

    try:
        with chromium_slot():
            captured, solver_jobs = asyncio.run(
                _capture_jobs_async(jobs, timeout=timeout, parallel=parallel)
            )
        results.update(captured)
        _finish_solver_fallbacks(results, solver_jobs)
    except Exception as exc:
        print(f"Captura de oferta: falló el lote ({exc}); se usa image_url.")
        for job in jobs:
            _discard_screenshot(job["dest"])
            results.setdefault(job["key"], None)
    return results


def capture_offer_screenshot(payload: dict[str, Any]) -> str | None:
    """Captura PNG de la página de oferta. None si está desactivado o falla."""
    key = screenshot_item_key(payload)
    return capture_offer_screenshots_batch([payload], keys=[key]).get(key)


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
