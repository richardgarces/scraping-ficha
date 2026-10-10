"""Límites de concurrencia compartidos para scraping (Redis o in-process).

Arquitectura en BMAX (precios-web + batch/soyo):

                precios-web / batch
                         |
               Límite global scrape: 8
                         |
                +--------+--------+
                |                 |
           HTTP directo       Playwright
           (hasta 8)          máximo 3
                |                 |
                +--------+--------+
                         |
                      MongoDB

El tope global se aplica dentro de ``scrape_store`` (y en capturas Chromium),
no solo vía ``max_workers`` de cada ThreadPoolExecutor: varios procesos Uvicorn
u otros contenedores comparten el mismo presupuesto vía Redis (``REDIS_URL`` /
precios-redis). Si Redis no está, cae a ``threading.Semaphore`` por proceso.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

SCRAPE_LIMIT = max(1, int(os.environ.get("RETAIL_SCRAPE_CONCURRENCY", "8") or 8))
CHROMIUM_LIMIT = max(1, int(os.environ.get("RETAIL_CHROMIUM_CONCURRENCY", "3") or 3))
# Lease por slot: si el proceso muere sin release, Redis libera el token.
_LEASE_SECONDS = max(30, int(os.environ.get("RETAIL_CONCURRENCY_LEASE_SECONDS", "180") or 180))
_POLL_SECONDS = 0.05
_KEY_PREFIX = "retail:sem:"

_ACQUIRE_LUA = """
local key = KEYS[1]
local token = ARGV[1]
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local expire_at = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, expire_at, token)
  return 1
end
return 0
"""

_RELEASE_LUA = """
return redis.call('ZREM', KEYS[1], ARGV[1])
"""

_redis_client: Any | None = None
_redis_checked = False
_redis_lock = threading.Lock()
_local_semaphores: dict[str, threading.Semaphore] = {}
_local_lock = threading.Lock()


class ConcurrencyTimeout(TimeoutError):
    """No se obtuvo un slot antes del timeout."""


def scrape_limit() -> int:
    return SCRAPE_LIMIT


def chromium_limit() -> int:
    return CHROMIUM_LIMIT


def _env_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def store_workers() -> int:
    return _env_int("RETAIL_STORE_WORKERS", 8)


def optional_store_workers(optional_count: int) -> int:
    cap = _env_int("RETAIL_OPTIONAL_STORE_WORKERS", 2)
    return max(1, min(cap, max(1, optional_count)))


def thumb_workers() -> int:
    return _env_int("RETAIL_THUMB_WORKERS", 2)


def batch_product_workers() -> int:
    # Tope duro 4: no dejar que un env agresivo sature el host.
    return _env_int("BATCH_PRODUCT_WORKERS", 2, maximum=4)


def reset_backend_for_tests() -> None:
    """Limpia cliente Redis cacheado y semáforos locales (solo tests)."""
    global _redis_client, _redis_checked
    with _redis_lock:
        _redis_client = None
        _redis_checked = False
    with _local_lock:
        _local_semaphores.clear()


def _connect_redis() -> Any | None:
    global _redis_client, _redis_checked
    with _redis_lock:
        if _redis_checked:
            return _redis_client
        _redis_checked = True
        try:
            from retail.search_cache import connect_redis

            _redis_client = connect_redis()
        except Exception:
            _redis_client = None
        if _redis_client is None:
            logger.info("Concurrency: Redis no disponible; límites solo in-process.")
        return _redis_client


def _local_semaphore(name: str, limit: int) -> threading.Semaphore:
    with _local_lock:
        sem = _local_semaphores.get(name)
        if sem is None:
            sem = threading.Semaphore(limit)
            _local_semaphores[name] = sem
        return sem


def _redis_acquire(client: Any, name: str, limit: int, token: str, lease: float) -> bool:
    now = time.time()
    result = client.eval(
        _ACQUIRE_LUA,
        1,
        f"{_KEY_PREFIX}{name}",
        token,
        int(limit),
        now,
        now + lease,
    )
    return bool(int(result or 0))


def _redis_release(client: Any, name: str, token: str) -> None:
    try:
        client.eval(_RELEASE_LUA, 1, f"{_KEY_PREFIX}{name}", token)
    except Exception:
        logger.debug("Concurrency: falló release Redis %s", name, exc_info=True)


def acquire(
    name: str,
    limit: int,
    *,
    timeout: float | None = None,
    lease_seconds: float | None = None,
) -> str:
    """Bloquea hasta obtener un slot. Devuelve token a pasar a ``release``."""
    if limit < 1:
        limit = 1
    lease = float(lease_seconds if lease_seconds is not None else _LEASE_SECONDS)
    token = uuid.uuid4().hex
    deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
    client = _connect_redis()

    if client is not None:
        while True:
            try:
                if _redis_acquire(client, name, limit, token, lease):
                    return token
            except Exception:
                logger.warning(
                    "Concurrency: Redis falló en acquire(%s); se usa semáforo local.",
                    name,
                    exc_info=True,
                )
                with _redis_lock:
                    global _redis_client, _redis_checked
                    _redis_client = None
                    _redis_checked = True
                break
            if deadline is not None and time.monotonic() >= deadline:
                raise ConcurrencyTimeout(f"timeout esperando slot {name}")
            time.sleep(_POLL_SECONDS)

    sem = _local_semaphore(name, limit)
    while True:
        if sem.acquire(blocking=False):
            return f"local:{token}"
        if deadline is not None and time.monotonic() >= deadline:
            raise ConcurrencyTimeout(f"timeout esperando slot {name}")
        time.sleep(_POLL_SECONDS)


def release(name: str, token: str | None) -> None:
    if not token:
        return
    if token.startswith("local:"):
        _local_semaphore(name, 1).release()
        return
    client = _connect_redis()
    if client is not None:
        _redis_release(client, name, token)


@contextmanager
def slot(
    name: str,
    limit: int,
    *,
    timeout: float | None = None,
    lease_seconds: float | None = None,
) -> Iterator[str]:
    token = acquire(name, limit, timeout=timeout, lease_seconds=lease_seconds)
    try:
        yield token
    finally:
        release(name, token)


@contextmanager
def scrape_slot(*, timeout: float | None = None) -> Iterator[str]:
    """Slot del presupuesto global de scrape (HTTP + Chromium)."""
    with slot("scrape", scrape_limit(), timeout=timeout) as token:
        yield token


@contextmanager
def chromium_slot(*, timeout: float | None = None) -> Iterator[tuple[str, str]]:
    """Toma slot global scrape y luego slot Chromium (anidados)."""
    with scrape_slot(timeout=timeout) as scrape_token:
        with slot("chromium", chromium_limit(), timeout=timeout) as chrome_token:
            yield scrape_token, chrome_token
