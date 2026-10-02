from __future__ import annotations

import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from retail.intent import parse
from retail.models import Product
from retail.relevance import _SPEC_RE, fold, tokenize

DEFAULT_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
MIN_SCORE = float(os.environ.get("RETAIL_SEARCH_CACHE_MIN_SCORE", "0.72"))
TZ = ZoneInfo("America/Santiago")


def _now() -> datetime:
    return datetime.now(TZ)


def connect_redis(url: str = DEFAULT_URL):
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return None


def chile_today(now: datetime | None = None) -> str:
    stamp = now or _now()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TZ)
    return stamp.astimezone(TZ).date().isoformat()


def ttl_until_midnight(now: datetime | None = None) -> int:
    stamp = now or _now()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TZ)
    local = stamp.astimezone(TZ)
    tomorrow = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    # Restar timestamps respeta los días de 23/25 horas por cambio de horario.
    return max(1, math.ceil(tomorrow.timestamp() - local.timestamp()))


def start_of_today_ts(now: datetime | None = None) -> float:
    stamp = now or _now()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TZ)
    local = stamp.astimezone(TZ)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def canonical_query(text: str) -> str:
    # La caché debe conservar modelos de un dígito y calificadores como
    # "gamer"/"sin sodio", aunque el filtro de relevancia los trate distinto.
    return " ".join(re.findall(r"[a-z0-9]+", fold(text)))


def query_digest(text: str) -> str:
    return hashlib.sha256(canonical_query(text).encode()).hexdigest()[:24]


def store_redis_key(store_id: str, digest: str, day: str | None = None) -> str:
    return f"search:{day or chile_today()}:store:v2:{store_id}:{digest}"


def result_scope_digest(
    *,
    source: str,
    stores: list[str],
    max_items: int,
    price_band: bool,
) -> str:
    payload = json.dumps(
        {
            "source": source,
            "stores": sorted(store.lower() for store in stores),
            "max": int(max_items),
            "band": bool(price_band),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def result_redis_key(
    query: str,
    *,
    source: str,
    stores: list[str],
    max_items: int,
    price_band: bool,
    day: str | None = None,
) -> str:
    return (
        f"search:{day or chile_today()}:result:v2:{query_digest(query)}:"
        f"{result_scope_digest(source=source, stores=stores, max_items=max_items, price_band=price_band)}"
    )


def query_redis_key(digest: str, day: str | None = None) -> str:
    return f"search:{day or chile_today()}:query:{digest}"


def typo_equivalent(current: str, cached: str) -> bool:
    """Solo letras duplicadas; no aproxima modelos, medidas ni modificadores."""
    left, right = canonical_query(current).split(), canonical_query(cached).split()
    if not left or len(left) != len(right):
        return False
    changes = 0
    for a, b in zip(left, right):
        if a == b:
            continue
        if not a.isalpha() or not b.isalpha():
            return False
        # Una letra repetida: ssal→sal, lecche→leche. No sal→sol/cal.
        long, short = (a, b) if len(a) > len(b) else (b, a)
        if len(short) < 3 or len(long) != len(short) + 1:
            return False
        if not any(long[i] == long[i - 1] and long[:i] + long[i + 1:] == short for i in range(1, len(long))):
            return False
        changes += 1
    return changes <= 1


def _specs(text: str) -> set[str]:
    return {token for token in tokenize(text) if _SPEC_RE.match(token)}


def compatible_queries(current: str, cached: str) -> bool:
    """Misma consulta de fondo, sin mezclar pulgadas ni capacidad."""
    left = parse(fold(current))
    right = parse(fold(cached))
    if left.inches and right.inches and left.inches != right.inches:
        return False
    specs_left, specs_right = _specs(current), _specs(cached)
    if specs_left and specs_right and specs_left != specs_right:
        return False
    tokens_left, tokens_right = set(tokenize(current)), set(tokenize(cached))
    if not tokens_left or not tokens_right:
        return False
    overlap = len(tokens_left & tokens_right) / min(len(tokens_left), len(tokens_right))
    return overlap >= 0.75


def _products(raw: list[Any]) -> list[Product]:
    products: list[Product] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            products.append(Product.from_dict(item))
        except Exception:
            continue
    return products


class SearchCache:
    def __init__(self, redis_client: Any, qdrant: Any | None = None) -> None:
        self.redis = redis_client
        self.qdrant = qdrant

    def lookup_result(
        self,
        query: str,
        *,
        source: str,
        stores: list[str],
        max_items: int,
        price_band: bool,
    ) -> dict[str, Any] | None:
        day = chile_today()
        raw = self.redis.get(
            result_redis_key(
                query, source=source, stores=stores, max_items=max_items, price_band=price_band, day=day
            )
        )
        if not raw or chile_today() != day:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("rows"), list):
            return None
        result = dict(result)
        result["groups"] = result.get("groups") or []
        result["saved"] = None
        result["cache"] = {
            "hit": "result",
            "ttl": ttl_until_midnight(),
            "day": day,
            "query": payload.get("cached_query") or query,
        }
        return result

    def store_result(
        self,
        query: str,
        *,
        source: str,
        stores: list[str],
        max_items: int,
        price_band: bool,
        result: dict[str, Any],
    ) -> None:
        progress = result.get("progress") or []
        stores_completed = any(item.get("state") == "ok" or item.get("cached") for item in progress)
        unavailable = (
            source in {"db", "both"}
            and result.get("mongo") is False
            and result.get("qdrant") is False
            and not result.get("scraped_count")
            and not stores_completed
        )
        if (
            not isinstance(result.get("rows"), list)
            or result.get("cancelled")
            or result.get("store_errors")
            or result.get("warnings")
            or unavailable
            or any(item.get("state") not in {"ok", "skip"} for item in progress)
        ):
            return
        stamp = _now()
        day, ttl = chile_today(stamp), ttl_until_midnight(stamp)
        slim = {key: value for key, value in result.items() if key not in {"groups", "saved"}}
        payload = {"cached_query": query, "result": slim, "day": day}
        self.redis.setex(
            result_redis_key(
                query, source=source, stores=stores, max_items=max_items, price_band=price_band, day=day
            ),
            ttl,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
        if result.get("rows"):
            self._remember_query(query, day=day, ttl=ttl)

    def lookup_stores(
        self,
        query: str,
        stores: list[str],
        *,
        max_items: int,
    ) -> dict[str, dict[str, Any]]:
        day = chile_today()
        digest = query_digest(query)
        found: dict[str, dict[str, Any]] = {}
        for store_id in stores:
            payload = self._load_store(day, store_id, digest)
            hit = self._accept(payload, max_items=max_items)
            if hit is not None:
                found[store_id] = {**hit, "hit": "exact", "query": payload.get("cached_query") or query}
        missing = [store_id for store_id in stores if store_id not in found]
        if not missing:
            return found if day == chile_today() else {}
        similar = self._similar(query)
        if similar is None:
            return found if day == chile_today() else {}
        for store_id in missing:
            payload = self._load_store(day, store_id, similar["digest"])
            hit = self._accept(payload, max_items=max_items)
            if hit is None:
                continue
            found[store_id] = {
                **hit,
                "hit": "similar",
                "query": similar["query"],
                "score": similar["score"],
            }
        return found if day == chile_today() else {}

    def store_stores(
        self,
        query: str,
        by_store: dict[str, list[Product]],
        *,
        max_items: int,
    ) -> None:
        if not by_store:
            return
        stamp = _now()
        day = chile_today(stamp)
        digest = query_digest(query)
        ttl = ttl_until_midnight(stamp)
        for store_id, products in by_store.items():
            payload = {
                "cached_query": query,
                "max_items": int(max_items),
                "products": [item.to_dict(flatten_specs=False) for item in products],
            }
            self.redis.setex(
                store_redis_key(store_id, digest, day),
                ttl,
                json.dumps(payload, ensure_ascii=False, default=str),
            )
        if any(by_store.values()):
            from retail.relevance import filter_relevant

            matches, _, _ = filter_relevant(query, [item for rows in by_store.values() for item in rows], price_band=False)
            if matches:
                self._remember_query(query, day=day, ttl=ttl)

    def _remember_query(self, query: str, *, day: str, ttl: int) -> None:
        digest = query_digest(query)
        self.redis.setex(query_redis_key(digest, day), ttl, query)
        self.redis.setex(f"search:{day}:queries-ready", ttl, "1")
        if self.qdrant is None:
            return
        try:
            self.qdrant.upsert_search_query(query, digest=digest)
        except Exception:
            return

    def _load_store(self, day: str, store_id: str, digest: str) -> dict[str, Any] | None:
        raw = self.redis.get(store_redis_key(store_id, digest, day))
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _accept(self, payload: dict[str, Any] | None, *, max_items: int) -> dict[str, Any] | None:
        if payload is None:
            return None
        cached_max = int(payload.get("max_items") or 0)
        if cached_max < max_items:
            return None
        products = _products(payload.get("products") or [])[:max_items]
        return {"products": products}

    def _similar(self, query: str) -> dict[str, Any] | None:
        if self.qdrant is None:
            return None
        try:
            hits = self.qdrant.similar_search_queries(
                query,
                min_age=start_of_today_ts(),
                limit=8,
            )
        except Exception:
            return None
        for score, payload in hits:
            cached_query = str(payload.get("query") or "")
            digest = str(payload.get("digest") or "")
            if not cached_query or not digest or not typo_equivalent(query, cached_query):
                continue
            # Las palabras cortas con letra duplicada tienen menos trigramas
            # compartidos; ssal/sal puntúa ~0.67 aunque sea la misma consulta.
            if score < min(MIN_SCORE, 0.60):
                continue
            if not self.redis.get(query_redis_key(digest)):
                continue
            return {"score": round(float(score), 3), "query": cached_query, "digest": digest}
        return None


def resolve_search_query(query: str) -> str:
    """Usa Qdrant para corregir una errata hacia una búsqueda de hoy en Redis."""
    client = connect_redis()
    if client is None:
        return query
    try:
        if client.get(query_redis_key(query_digest(query))):
            return query
        if not client.get(f"search:{chile_today()}:queries-ready"):
            return query
        from retail.qdrant_index import connect_qdrant

        qdrant = connect_qdrant()
        if qdrant is None:
            return query
        match = SearchCache(client, qdrant)._similar(query)
        return match["query"] if match else query
    except Exception:
        return query


def describe_cache(
    found: dict[str, dict[str, Any]],
    chosen: list[str],
    *,
    resume_missing: bool = True,
) -> dict[str, Any] | None:
    if not found:
        return None
    kind = "partial"
    if not resume_missing or len(found) == len(chosen):
        kind = "exact" if all(item.get("hit") == "exact" for item in found.values()) else "similar"
    similar = next((item for item in found.values() if item.get("hit") == "similar"), None)
    return {
        "hit": kind,
        "stores": list(found),
        "query": (similar or next(iter(found.values()))).get("query"),
        "score": (similar or {}).get("score"),
    }


def cache_warnings(
    found: dict[str, dict[str, Any]],
    chosen: list[str],
    titles: dict[str, str],
    *,
    resume_missing: bool = True,
) -> list[str]:
    if not found:
        return []
    cached_names = [titles.get(store_id, store_id) for store_id in found]
    missing_names = [titles.get(store_id, store_id) for store_id in chosen if store_id not in found]
    if not missing_names or not resume_missing:
        similar = next((item for item in found.values() if item.get("hit") == "similar"), None)
        if similar:
            return [f"Sin ir a las tiendas: hoy ya se buscó «{similar['query']}»."]
        return ["Sin ir a las tiendas: esa búsqueda ya se hizo hoy."]
    return [f"Hoy ya se buscó en {', '.join(cached_names)}. Consultando {', '.join(missing_names)}."]


def lookup_search_result(
    query: str,
    *,
    source: str,
    stores: list[str],
    max_items: int,
    price_band: bool,
) -> dict[str, Any] | None:
    client = connect_redis()
    if client is None:
        return None
    try:
        return SearchCache(client).lookup_result(
            query, source=source, stores=stores, max_items=max_items, price_band=price_band
        )
    except Exception:
        return None


def store_search_result(
    query: str,
    *,
    source: str,
    stores: list[str],
    max_items: int,
    price_band: bool,
    result: dict[str, Any],
    qdrant: Any | None = None,
) -> None:
    client = connect_redis()
    if client is None:
        return
    try:
        SearchCache(client, qdrant).store_result(
            query,
            source=source,
            stores=stores,
            max_items=max_items,
            price_band=price_band,
            result=result,
        )
    except Exception:
        return


def lookup_store_products(
    query: str,
    stores: list[str],
    *,
    max_items: int,
    qdrant=None,
) -> dict[str, dict[str, Any]]:
    client = connect_redis()
    if client is None:
        return {}
    try:
        return SearchCache(client, qdrant).lookup_stores(query, stores, max_items=max_items)
    except Exception:
        return {}


def store_store_products(
    query: str,
    by_store: dict[str, list[Product]],
    *,
    max_items: int,
    qdrant=None,
) -> None:
    client = connect_redis()
    if client is None:
        return
    try:
        SearchCache(client, qdrant).store_stores(query, by_store, max_items=max_items)
    except Exception:
        return
