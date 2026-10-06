"""Ranking diario de búsquedas frecuentes y caché Redis top 10 (Chile).

Ventana: día civil ``America/Santiago`` (misma clave de día que ``search_cache``).
TTL: ``ttl_until_midnight`` (tope ``RETAIL_SEARCH_CACHE_MAX_TTL``, default 4 h).

Claves Redis
------------
- ``search:freq:YYYY-MM-DD`` — sorted set; member = query canónica, score = conteo.
  Se incrementa la query completa y, si difiere, la primera palabra.
- ``search:top:YYYY-MM-DD:{norm}`` — JSON con el payload útil (rows/groups) del día
  para cada término del top 10 que ya se resolvió con resultado.

Búsqueda por tienda
-------------------
Top **global** del día. Si el API filtra ``stores``, se aplica el filtro sobre el
payload multi-tienda cacheado (no hay ranking por tienda separado).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from retail.search_cache import (
    canonical_query,
    chile_today,
    connect_redis,
    ttl_until_midnight,
)

logger = logging.getLogger(__name__)

TOP_N = max(1, int(os.environ.get("RETAIL_SEARCH_FREQ_TOP", "10")))


def freq_redis_key(day: str | None = None) -> str:
    return f"search:freq:{day or chile_today()}"


def top_redis_key(norm_query: str, day: str | None = None) -> str:
    return f"search:top:{day or chile_today()}:{norm_query}"


def normalize_search_query(text: str) -> str:
    """Minúsculas, sin acentos, trim — misma canónica que la caché de resultados."""
    return canonical_query(text)


def first_word(norm_query: str) -> str:
    parts = str(norm_query or "").split()
    return parts[0] if parts else ""


def extra_tokens(norm_query: str, head: str) -> list[str]:
    parts = str(norm_query or "").split()
    if not parts or parts[0] != head:
        return parts
    return parts[1:]


def record_search_frequency(
    query: str,
    *,
    redis_client: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Incrementa contadores del día (query completa + primera palabra)."""
    norm = normalize_search_query(query)
    if not norm:
        return None
    client = redis_client if redis_client is not None else connect_redis()
    if client is None:
        return None
    day = chile_today(now)
    ttl = ttl_until_midnight(now)
    key = freq_redis_key(day)
    try:
        full_score = float(client.zincrby(key, 1, norm))
        head = first_word(norm)
        head_score = full_score
        if head and head != norm:
            head_score = float(client.zincrby(key, 1, head))
        client.expire(key, ttl)
        return {
            "day": day,
            "query": norm,
            "first_word": head,
            "count": int(full_score),
            "first_word_count": int(head_score),
        }
    except Exception:
        logger.debug("No se pudo registrar frecuencia de búsqueda", exc_info=True)
        return None


def top_queries(
    *,
    redis_client: Any | None = None,
    now: datetime | None = None,
    limit: int = TOP_N,
) -> list[dict[str, Any]]:
    client = redis_client if redis_client is not None else connect_redis()
    if client is None:
        return []
    day = chile_today(now)
    key = freq_redis_key(day)
    try:
        rows = client.zrevrange(key, 0, max(0, int(limit) - 1), withscores=True)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for member, score in rows or []:
        text = str(member)
        if not text:
            continue
        out.append({"query": text, "count": int(score), "cached": False})
    for item in out:
        try:
            item["cached"] = bool(client.get(top_redis_key(item["query"], day)))
        except Exception:
            item["cached"] = False
    return out


def is_top_query(
    norm_query: str,
    *,
    redis_client: Any,
    now: datetime | None = None,
    limit: int = TOP_N,
) -> bool:
    if not norm_query:
        return False
    top = {item["query"] for item in top_queries(redis_client=redis_client, now=now, limit=limit)}
    return norm_query in top


def _haystack(item: dict[str, Any]) -> str:
    chunks: list[str] = []
    for key in ("name", "brand", "title", "store_title", "store", "sku_id", "product_id"):
        value = item.get(key)
        if value:
            chunks.append(str(value))
    attrs = item.get("attrs") or item.get("specs") or {}
    if isinstance(attrs, dict):
        for key, value in attrs.items():
            chunks.append(str(key))
            if value is not None:
                chunks.append(str(value))
    elif isinstance(attrs, list):
        for value in attrs:
            chunks.append(str(value))
    return normalize_search_query(" ".join(chunks))


def product_matches_tokens(item: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return True
    text = _haystack(item)
    if not text:
        return False
    # Subcadena sobre el haystack canónico (cubre «s25» dentro de «galaxy s25»).
    return all(token in text for token in tokens)


def _offer_matches(offer: dict[str, Any], tokens: list[str]) -> bool:
    if product_matches_tokens(offer, tokens):
        return True
    # Atributos anidados frecuentes en filas aplanadas.
    for key in ("model", "variant", "description"):
        value = offer.get(key)
        if value and all(token in normalize_search_query(str(value)) for token in tokens):
            return True
    return False


def filter_result_payload(
    result: dict[str, Any],
    *,
    tokens: list[str] | None = None,
    stores: list[str] | None = None,
) -> dict[str, Any]:
    """Filtra rows/groups por tokens extra y/o tiendas, sin reconsultar."""
    payload = dict(result)
    store_set = {str(item).strip().lower() for item in (stores or []) if str(item).strip()}
    want_tokens = [str(token) for token in (tokens or []) if token]

    rows_in = [dict(row) for row in payload.get("rows") or [] if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for row in rows_in:
        if store_set and str(row.get("store") or "").strip().lower() not in store_set:
            continue
        if want_tokens and not _offer_matches(row, want_tokens):
            continue
        rows.append(row)

    groups_out: list[dict[str, Any]] = []
    for group in payload.get("groups") or []:
        if not isinstance(group, dict):
            continue
        group = dict(group)
        offers = []
        for offer in group.get("offers") or []:
            if not isinstance(offer, dict):
                continue
            if store_set and str(offer.get("store") or "").strip().lower() not in store_set:
                continue
            if want_tokens and not _offer_matches(offer, want_tokens):
                continue
            offers.append(dict(offer))
        if not offers:
            # Si no hay offers pero el nombre del grupo calza, conservar filas sueltas.
            if want_tokens and not _offer_matches(group, want_tokens):
                continue
            if not want_tokens:
                continue
        group["offers"] = offers
        if offers:
            prices = [item.get("price") for item in offers if isinstance(item.get("price"), (int, float))]
            if prices:
                lowest = min(prices)
                lowest_offers = [item for item in offers if item.get("price") == lowest]
                group["lowest_price"] = lowest
                group["lowest_stores"] = [item.get("store") for item in lowest_offers]
                group["lowest_store_titles"] = [
                    item.get("store_title") or item.get("store") for item in lowest_offers
                ]
        groups_out.append(group)

    payload["rows"] = rows
    payload["groups"] = groups_out
    payload["offer_count"] = len(rows)
    payload["group_count"] = len(groups_out)
    payload["comparable_count"] = sum(1 for group in groups_out if group.get("comparable"))
    if store_set:
        payload["stores"] = [store for store in (payload.get("stores") or []) if store in store_set] or sorted(
            store_set
        )
    return payload


def _load_top_payload(client: Any, norm: str, day: str) -> dict[str, Any] | None:
    if chile_today() != day:
        return None
    raw = client.get(top_redis_key(norm, day))
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("day") or "") != day:
        return None
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        return None
    return payload


def lookup_top_search(
    query: str,
    *,
    stores: list[str] | None = None,
    redis_client: Any | None = None,
    now: datetime | None = None,
    limit: int = TOP_N,
) -> dict[str, Any] | None:
    """Hit exacto o por primera palabra (top) + filtro de tokens extra."""
    norm = normalize_search_query(query)
    if not norm:
        return None
    client = redis_client if redis_client is not None else connect_redis()
    if client is None:
        return None
    day = chile_today(now)
    ranking = top_queries(redis_client=client, now=now, limit=limit)
    top_set = {item["query"] for item in ranking}
    if not top_set:
        return None

    # 1) Exacto en top 10 con payload.
    if norm in top_set:
        cached = _load_top_payload(client, norm, day)
        if cached is not None:
            result = filter_result_payload(dict(cached["result"]), stores=stores)
            if result.get("rows"):
                result = dict(result)
                result["saved"] = None
                result["cache"] = {
                    "hit": "top",
                    "ttl": ttl_until_midnight(now),
                    "day": day,
                    "query": cached.get("cached_query") or norm,
                }
                return result

    # 2) Primera palabra en top 10 → filtrar por el resto.
    head = first_word(norm)
    if not head or head == norm or head not in top_set:
        return None
    cached = _load_top_payload(client, head, day)
    if cached is None:
        return None
    tokens = extra_tokens(norm, head)
    result = filter_result_payload(dict(cached["result"]), tokens=tokens, stores=stores)
    if not result.get("rows"):
        return None
    result = dict(result)
    result["saved"] = None
    result["cache"] = {
        "hit": "top_prefix",
        "ttl": ttl_until_midnight(now),
        "day": day,
        "query": head,
        "filter_tokens": tokens,
    }
    return result


def store_top_search_result(
    query: str,
    result: dict[str, Any],
    *,
    redis_client: Any | None = None,
    now: datetime | None = None,
    limit: int = TOP_N,
    force: bool = False,
) -> bool:
    """Persiste el payload si la query (canónica) está en el top N del día."""
    norm = normalize_search_query(query)
    if not norm:
        return False
    rows = result.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    if result.get("cancelled") or result.get("store_errors"):
        return False
    client = redis_client if redis_client is not None else connect_redis()
    if client is None:
        return False
    day = chile_today(now)
    if not force and not is_top_query(norm, redis_client=client, now=now, limit=limit):
        return False
    slim = {
        key: value
        for key, value in result.items()
        if key
        not in {
            "saved",
            "product_index",
            "requested_query",
            "store_preferences",
        }
    }
    # Mantener groups/rows; son el set filtrable.
    payload = {
        "cached_query": query if str(query or "").strip() else norm,
        "norm": norm,
        "day": day,
        "result": slim,
    }
    ttl = ttl_until_midnight(now)
    try:
        client.setex(
            top_redis_key(norm, day),
            ttl,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        # Asegurar TTL del ranking aunque no haya nuevos zincrby.
        client.expire(freq_redis_key(day), ttl)
        return True
    except Exception:
        logger.debug("No se pudo guardar top search", exc_info=True)
        return False


def load_search_freq(*, now: datetime | None = None) -> dict[str, Any]:
    """Agregado admin: top 10 del día + cuántos tienen payload en Redis."""
    stamp = now
    day = chile_today(stamp)
    empty = {
        "redis": False,
        "day": day,
        "timezone": "America/Santiago",
        "top_n": TOP_N,
        "count": 0,
        "cached_count": 0,
        "items": [],
        "window": "día civil America/Santiago; TTL alineado a search_cache (medianoche o max 4h)",
        "store_policy": "top global + filtro stores sobre cache multi-tienda",
    }
    client = connect_redis()
    if client is None:
        return empty
    try:
        items = top_queries(redis_client=client, now=stamp, limit=TOP_N)
        return {
            "redis": True,
            "day": day,
            "timezone": "America/Santiago",
            "top_n": TOP_N,
            "count": len(items),
            "cached_count": sum(1 for item in items if item.get("cached")),
            "items": items,
            "window": empty["window"],
            "store_policy": empty["store_policy"],
        }
    except Exception:
        return empty
