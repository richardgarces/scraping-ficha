"""Barreras ligeras contra extracción automatizada de la aplicación pública.

No pretende distinguir de forma perfecta a una persona de un bot (un cliente
puede imitar un navegador), pero evita el acceso directo a las APIs, rechaza
agentes automatizados conocidos y limita los recorridos masivos por IP.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Mapping

from retail.auth import session_secret
from retail.request_stats import client_ip

VISITOR_COOKIE = "retail_visitor"
VISITOR_MAX_AGE = 12 * 60 * 60

_AUTOMATION_RE = re.compile(
    r"(?:bot\b|spider|crawler|scrapy|selenium|playwright|puppeteer|headless|"
    r"python-requests|python-httpx|aiohttp|curl/|wget/|go-http-client|java/|"
    r"libwww|httpclient|postmanruntime|insomnia)",
    re.I,
)
_DATA_PREFIXES = (
    "/api/catalog",
    "/api/catalog-insights",
    "/api/categories",
    "/api/deals",
    "/api/forecasts",
    "/api/product",
    "/api/reales",
    "/api/stores",
    "/api/stores-drops",
    "/api/stores-report",
    "/api/super",
)
_PUBLIC_PAGES = {"/", "/catalogo", "/hoy", "/producto"}
_EXEMPT_PREFIXES = (
    "/api/admin/",
    "/api/account/",
    "/api/auth/",
    "/api/settings",
    "/api/batch/",
    "/api/alerts",
    "/api/history",
    "/api/price-alert",
    "/api/watches",
    "/static/",
    "/o/",
    "/offer-shots/",
)


@dataclass(frozen=True)
class GuardDecision:
    status_code: int
    detail: str
    retry_after: int | None = None


_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_lock = threading.Lock()
_last_cleanup = 0.0


def enabled() -> bool:
    return os.environ.get("RETAIL_ANTI_SCRAPING", "1").strip().lower() not in {"0", "false", "no", "off"}


def protected_api(path: str) -> bool:
    clean = path.rstrip("/") or "/"
    if clean in {"/api/search", "/api/search/stream"}:
        return True
    return any(clean == prefix or clean.startswith(prefix + "/") for prefix in _DATA_PREFIXES)


def public_page(path: str) -> bool:
    return (path.rstrip("/") or "/") in _PUBLIC_PAGES


def should_issue_visitor_cookie(path: str, content_type: str) -> bool:
    return "text/html" in content_type.lower() and not path.startswith("/api/")


def sign_visitor(*, now: int | None = None) -> str:
    issued = int(time.time() if now is None else now)
    payload = f"v1.{issued}"
    signature = hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def valid_visitor(token: str | None, *, now: int | None = None) -> bool:
    if not token or token.count(".") != 2:
        return False
    version, issued_raw, signature = token.split(".", 2)
    if version != "v1":
        return False
    payload = f"{version}.{issued_raw}"
    expected = hmac.new(session_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        issued = int(issued_raw)
    except ValueError:
        return False
    current = int(time.time() if now is None else now)
    return 0 <= current - issued <= VISITOR_MAX_AGE and issued <= current + 60


def _header(headers: Mapping[str, str], name: str) -> str:
    try:
        return str(headers.get(name, "") or "")
    except (AttributeError, TypeError):
        return ""


def automated_client(headers: Mapping[str, str]) -> bool:
    user_agent = _header(headers, "user-agent").strip()
    return not user_agent or bool(_AUTOMATION_RE.search(user_agent))


def _rate_rule(path: str) -> tuple[str, int, int] | None:
    clean = path.rstrip("/") or "/"
    if clean in {"/api/search", "/api/search/stream"}:
        return "search", 20, 60
    if protected_api(clean):
        return "data", 90, 60
    if public_page(clean):
        return "page", 120, 60
    return None


def _rate_limited(key: str, bucket: str, limit: int, window: int, now: float) -> int | None:
    global _last_cleanup
    cutoff = now - window
    with _lock:
        queue = _hits[(key, bucket)]
        while queue and queue[0] <= cutoff:
            queue.popleft()
        if len(queue) >= limit:
            return max(1, int(window - (now - queue[0])) + 1)
        queue.append(now)
        if now - _last_cleanup > 300:
            stale = [item for item, values in _hits.items() if not values or values[-1] <= now - 600]
            for item in stale:
                _hits.pop(item, None)
            _last_cleanup = now
    return None


def inspect_request(
    path: str,
    method: str,
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
    client_host: str | None,
    *,
    now: float | None = None,
) -> GuardDecision | None:
    """Devuelve el motivo de bloqueo o ``None`` cuando la petición es válida."""
    if not enabled() or method.upper() not in {"GET", "HEAD"}:
        return None
    clean = path.rstrip("/") or "/"
    if clean in {"/api/health", "/robots.txt", "/favicon.ico", "/apple-touch-icon.png"}:
        return None
    if any(clean.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
        return None
    guarded_api = protected_api(clean)
    guarded_page = public_page(clean)
    if not guarded_api and not guarded_page:
        return None
    if automated_client(headers):
        return GuardDecision(403, "Acceso automatizado no permitido.")
    if guarded_api and not valid_visitor(cookies.get(VISITOR_COOKIE)):
        return GuardDecision(403, "Abre la aplicación antes de consultar sus datos.")
    rule = _rate_rule(clean)
    if rule:
        bucket, limit, window = rule
        ip = client_ip(headers, client_host)
        retry = _rate_limited(ip, bucket, limit, window, time.monotonic() if now is None else now)
        if retry is not None:
            return GuardDecision(429, "Demasiadas solicitudes. Espera antes de volver a intentar.", retry)
    return None


def reset_limits() -> None:
    """Limpia contadores; se usa en pruebas y operaciones controladas."""
    global _last_cleanup
    with _lock:
        _hits.clear()
        _last_cleanup = 0.0
