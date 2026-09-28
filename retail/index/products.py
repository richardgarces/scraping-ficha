"""Productos genéricos: semilla en Mongo, índice en Redis, enrutado de tiendas.

No filtra accesorios (eso sigue en intent/relevance). Acá solo se decide
*qué* es la consulta y *en qué grupos de tiendas* buscarla.

La verdad vive en Mongo (`product_index_seed`). `productos.json` arranca la
colección si está vacía y sirve de respaldo local. Redis (`retail:pindex:`)
es la copia caliente; se renueva a diario desde Mongo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from retail.registry import GROUP_ORDER, GROUP_TITLES, STORE_GROUP
from retail.relevance import fold
from retail.search_cache import TZ, connect_redis, ttl_until_midnight

PREFIX = "retail:pindex:"
META_KEY = f"{PREFIX}meta"
MANIFEST_KEY = f"{PREFIX}manifest"
ALL_KEY = f"{PREFIX}all"
SWEEP_PREFIX = f"{PREFIX}sweep:"
SWEEP_TTL_FLOOR = 4 * 3600
SEED_PATH = Path(__file__).resolve().parent / "productos.json"
# Sin genérico: department stores + electrónica. No moda, farmacia, té, etc.
# Si la consulta parece médica (`intent.looks_pharmacy`), se suman farmacias
# (+ supermercados OTC) vía `unmatched_fallback_groups`.
UNMATCHED_FALLBACK_GROUPS = ("retail", "tecnologia")
UNMATCHED_PHARMACY_EXTRA_GROUPS = ("farmacias", "supermercados")
VEHICLE_QUERY_TOKENS = frozenset(
    {
        "auto", "autos", "automovil", "camioneta", "suv", "pickup", "4x4", "vehiculo",
        "toyota", "chevrolet", "hyundai", "kia", "suzuki", "nissan", "mazda", "ford",
        "volkswagen", "subaru", "mitsubishi", "honda", "peugeot", "citroen", "renault",
        "chery", "mg", "jac", "great wall", "gwm", "bmw", "mercedes", "audi", "volvo",
        "lexus", "jeep", "ram", "fiat", "skoda", "seat", "opel", "ssangyong",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOCK = threading.Lock()
logger = logging.getLogger(__name__)

_MEMORY: _MemoryIndex | None = None
_SWEEPS: dict[str, float] = {}

# Palabras que no se indexan como alias: artículos, preposiciones, conjunciones.
ALIAS_STOPWORDS = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "lo",
        "le",
        "les",
        "un",
        "una",
        "unos",
        "unas",
        "y",
        "e",
        "o",
        "u",
        "ni",
        "que",
        "pero",
        "sino",
        "aunque",
        "a",
        "al",
        "de",
        "del",
        "en",
        "con",
        "sin",
        "por",
        "para",
        "sobre",
        "entre",
        "hacia",
        "hasta",
        "desde",
        "segun",
        "durante",
        "mediante",
        "contra",
        "bajo",
        "ante",
        "tras",
        "como",
        "vs",
        "versus",
        "the",
        "of",
        "and",
        "or",
        "for",
        "with",
    }
)
# Medidas y unidades: no son marcas ni genéricos.
ALIAS_UNITS = frozenset(
    {
        "pulgadas",
        "pulgada",
        "pulg",
        "centimetros",
        "centimetro",
        "cm",
        "mm",
        "metros",
        "metro",
        "km",
        "kilos",
        "kilo",
        "kilogramos",
        "kilogramo",
        "kg",
        "gramos",
        "gramo",
        "gr",
        "mililitros",
        "mililitro",
        "ml",
        "litros",
        "litro",
        "lts",
        "lt",
        "watts",
        "watt",
        "watios",
        "watio",
        "kw",
        "hertz",
        "hz",
        "mah",
        "gigas",
        "giga",
        "gb",
        "teras",
        "tera",
        "tb",
        "mb",
        "mg",
        "mcg",
        "ug",
        "ui",
        "iu",
        "inches",
        "inch",
        "in",
        "onzas",
        "oz",
        "libras",
        "lb",
        "lbs",
    }
)


@dataclass(frozen=True, slots=True)
class GenericProduct:
    id: str
    name: str
    aliases: tuple[str, ...]
    groups: tuple[str, ...]

    def keys(self) -> tuple[str, ...]:
        seen: list[str] = []
        found: set[str] = set()
        for raw in (self.id, self.name, *self.aliases):
            folded = fold(raw)
            if len(folded) < 2:
                continue
            for item in (folded, folded.replace(" ", "")):
                if len(item) < 2 or item in found:
                    continue
                found.add(item)
                seen.append(item)
        return tuple(seen)

    def letter(self) -> str:
        return letter_bucket(self.id)

    def to_public(self, *, store_count: int, applied: bool) -> dict[str, Any]:
        groups = [group for group in self.groups if group in GROUP_TITLES]
        return {
            "id": self.id,
            "name": self.name,
            "groups": groups,
            "group_titles": [GROUP_TITLES[group] for group in groups],
            "store_count": store_count,
            "applied": applied,
        }


@dataclass(frozen=True, slots=True)
class ResolvedProduct:
    id: str
    name: str
    groups: tuple[str, ...]
    matched_alias: str

    def to_public(self, *, store_count: int, applied: bool) -> dict[str, Any]:
        return GenericProduct(self.id, self.name, (), self.groups).to_public(
            store_count=store_count, applied=applied
        )


@dataclass
class _MemoryIndex:
    version: int
    seed_hash: str
    by_id: dict[str, GenericProduct]
    aliases: dict[str, str]
    letters: dict[str, tuple[str, ...]]


def letter_bucket(value: str) -> str:
    folded = fold(value)
    if not folded:
        return "0"
    first = folded[0]
    return first if "a" <= first <= "z" else "0"


def seed_path() -> Path:
    return SEED_PATH


def load_seed(path: Path | None = None) -> tuple[int, str, list[GenericProduct]]:
    """Lee `productos.json`. Bootstrap y fallback; la semilla viva está en Mongo."""
    target = path or SEED_PATH
    raw = target.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    version = int(payload.get("version") or 1)
    products = [_parse_product(item) for item in payload.get("products") or []]
    _validate_products(products)
    return version, digest_products(version, products), products


def digest_products(version: int, products: list[GenericProduct]) -> str:
    payload = {
        "version": version,
        "products": [
            {
                "id": item.id,
                "name": item.name,
                "aliases": list(item.aliases),
                "groups": list(item.groups),
            }
            for item in sorted(products, key=lambda item: item.id)
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def load_active_seed(
    *,
    repo: Any | None = None,
    sync_json: bool = False,
) -> tuple[int, str, list[GenericProduct], str]:
    """Mongo primero; JSON si Mongo está vacío, caído o se pide omitir (`repo=False`)."""
    close = False
    if repo is False:
        version, digest, products = load_seed()
        return version, digest, products, "json"
    if repo is None:
        repo = _connect_mongo()
        close = repo is not None
    try:
        if repo is not None:
            if repo.product_index_seed_empty() or sync_json:
                json_version, _digest, json_products = load_seed()
                repo.sync_product_index_seed(_product_payloads(json_products), json_version)
            try:
                from retail.store_categories import ensure_store_categories

                ensure_store_categories(repo=repo)
            except Exception:
                logger.debug("No se pudo sincronizar store_categories", exc_info=True)
            version, rows = repo.load_product_index_seed()
            if rows:
                products = [_parse_product(item) for item in rows]
                _validate_products(products)
                return version, digest_products(version, products), products, "mongo"
    except Exception:
        logger.debug("Semilla Mongo no disponible; se usa productos.json", exc_info=True)
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
    version, digest, products = load_seed()
    return version, digest, products, "json"


def feed_search(
    query: str,
    product_index: dict[str, Any] | None,
    *,
    store_count: int,
    applied: bool,
    repo: Any | None = None,
    background: bool = True,
) -> None:
    """Registra la consulta en Mongo sin frenar la búsqueda.

    Alimentar = log + estadísticas + cola de sin-match. Si resolvió un genérico,
    los tokens sobrantes (marcas, modelos) se suman como alias de *ese* producto.
    No crea genéricos nuevos desde texto libre (`colun` no se vuelve un producto).
    """
    text = str(query or "").strip()
    if not text:
        return
    payload = dict(product_index) if product_index else None
    kwargs = {
        "query": text,
        "product_index": payload,
        "store_count": int(store_count),
        "applied": bool(applied),
        "repo": repo,
    }
    if repo is not None or not background:
        _feed_search_now(**kwargs)
        return
    try:
        threading.Thread(
            target=_feed_search_now,
            kwargs=kwargs,
            daemon=True,
            name="product-index-feed",
        ).start()
    except Exception:
        logger.debug("No se pudo disparar la alimentación del índice", exc_info=True)


def unique_product_id(query: str, *, client: Any | None = None) -> str | None:
    """Id del genérico resuelto. `tele`, `tv mini` y `tv` colapsan a `tv`."""
    found = resolve(query, client=client)
    return found.id if found is not None else None


def leftover_alias_tokens(
    query: str,
    *,
    client: Any | None = None,
    product: ResolvedProduct | None = None,
) -> list[str]:
    """Tokens de la consulta que pueden indexarse como alias del genérico ganador.

    Vacío si no hay producto, o si solo quedan stopwords, números, unidades
    o el propio alias que ya pegó (`parlante` en «parlante jbl partibox»).
    """
    found = product if product is not None else resolve(query, client=client)
    if found is None:
        return []
    claimed = _claimed_alias_tokens(found, client=client)
    leftovers: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(fold(query)):
        if token in seen or not _usable_alias_token(token, claimed):
            continue
        owner = _alias_owner(token, client=client)
        if owner and owner != found.id:
            continue
        if owner == found.id:
            continue
        seen.add(token)
        leftovers.append(token)
    return leftovers


def claim_unique_sweep(product_id: str, *, client: Any | None = None) -> bool:
    """Reserva el barrido extra de un genérico. False si ya corre o corrió hace poco."""
    ident = str(product_id or "").strip()
    if not ident:
        return False
    ttl = max(SWEEP_TTL_FLOOR, ttl_until_midnight())
    redis = _redis(client)
    if redis is not None:
        try:
            return bool(redis.set(f"{SWEEP_PREFIX}{ident}", "running", nx=True, ex=ttl))
        except Exception:
            logger.debug("No se pudo reservar el barrido extra en Redis", exc_info=True)
    now = time.time()
    with _LOCK:
        expires = _SWEEPS.get(ident) or 0.0
        if expires > now:
            return False
        _SWEEPS[ident] = now + ttl
        return True


def release_unique_sweep(product_id: str, *, client: Any | None = None) -> None:
    """Suelta el lock del barrido extra si la búsqueda se detuvo antes de lanzarlo."""
    ident = str(product_id or "").strip()
    if not ident:
        return
    redis = _redis(client)
    if redis is not None:
        try:
            redis.delete(f"{SWEEP_PREFIX}{ident}")
        except Exception:
            logger.debug("No se pudo soltar el barrido extra en Redis", exc_info=True)
    with _LOCK:
        _SWEEPS.pop(ident, None)


def feed_query_aliases(
    query: str,
    *,
    repo: Any | None = None,
    client: Any | None = None,
) -> list[str]:
    """Suma a la semilla los tokens sobrantes de una consulta que ya resolvió genérico."""
    found = resolve(query, client=client)
    if found is None:
        return []
    tokens = leftover_alias_tokens(query, client=client, product=found)
    if not tokens:
        return []
    return add_product_aliases(found.id, tokens, repo=repo, client=client)


def add_product_aliases(
    product_id: str,
    aliases: list[str],
    *,
    repo: Any | None = None,
    client: Any | None = None,
) -> list[str]:
    """Agrega alias al mismo genérico. No crea productos ni pisa alias de otro id."""
    ident = str(product_id or "").strip()
    wanted: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        token = fold(str(raw or ""))
        if token in seen or not _usable_alias_token(token, set()):
            continue
        owner = _alias_owner(token, client=client)
        if owner and owner != ident:
            continue
        if owner == ident:
            continue
        seen.add(token)
        wanted.append(token)
    if not ident or not wanted:
        return []
    extra: list[str] = []
    close = False
    if repo is None:
        repo = _connect_mongo()
        close = repo is not None
    try:
        if repo is not None:
            extra = list(repo.add_product_index_aliases(ident, wanted) or [])
        else:
            extra = list(wanted)
        if extra:
            _patch_live_aliases(ident, extra, client=client)
    except Exception:
        logger.debug("No se pudieron sumar alias a %s", ident, exc_info=True)
        extra = []
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
    return extra


def feed_discovered_groups(
    product_id: str,
    store_ids: list[str],
    *,
    query: str = "",
    repo: Any | None = None,
    client: Any | None = None,
) -> list[str]:
    """Suma a la semilla los grupos de tiendas extra que sí devolvieron el producto."""
    ident = str(product_id or "").strip()
    stores = [str(item).strip() for item in store_ids if str(item).strip()]
    if not ident or not stores:
        return []
    wanted: list[str] = []
    seen: set[str] = set()
    for store_id in stores:
        group = STORE_GROUP.get(store_id)
        if not group or group not in GROUP_TITLES or group == "otros" or group in seen:
            continue
        seen.add(group)
        wanted.append(group)
    if not wanted:
        return []
    extra: list[str] = []
    close = False
    if repo is None:
        repo = _connect_mongo()
        close = repo is not None
    try:
        if repo is not None:
            extra = list(repo.add_product_index_groups(ident, wanted, store_ids=stores) or [])
            if extra:
                try:
                    repo.save_product_index_query(
                        {
                            "query": query,
                            "folded": fold(query) if query else "",
                            "product_id": ident,
                            "groups": extra,
                            "store_count": len(stores),
                            "applied": True,
                            "unmatched": False,
                            "background": True,
                            "discovered_stores": stores,
                            "extra_groups": extra,
                            "created_at": datetime.now(timezone.utc),
                        }
                    )
                except Exception:
                    logger.debug("No se pudo registrar el barrido extra", exc_info=True)
        else:
            extra = list(wanted)
        if extra:
            _patch_live_groups(ident, extra, client=client)
    except Exception:
        logger.debug("No se pudieron sumar grupos descubiertos a %s", ident, exc_info=True)
        extra = []
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
    return extra


def resolve(query: str, *, client: Any | None = None) -> ResolvedProduct | None:
    """Producto genérico de la consulta, o None si no hay coincidencia."""
    redis = _redis(client)
    if redis is not None:
        try:
            ensure_loaded(client=redis)
            found = _resolve_redis(redis, query)
            if found is not None:
                return found
        except Exception:
            logger.debug("Índice Redis no disponible; se usa la semilla en memoria", exc_info=True)
    return _resolve_memory(query)


def unmatched_fallback_groups(query: str = "") -> tuple[str, ...]:
    """Grupos cuando no hay genérico: retail+tecnología, y farmacias si parece médico."""
    from retail.intent import looks_pharmacy

    groups = list(UNMATCHED_FALLBACK_GROUPS)
    folded = fold(query) if query else ""
    if folded and looks_pharmacy(folded):
        for group in UNMATCHED_PHARMACY_EXTRA_GROUPS:
            if group not in groups:
                groups.append(group)
    words = set(folded.split())
    if folded and (words.intersection(VEHICLE_QUERY_TOKENS) or any(token in folded for token in ("great wall", "mercedes benz"))):
        if "autos" not in groups:
            groups.append("autos")
    return tuple(groups)


def unmatched_fallback_stores(
    available_store_ids: list[str],
    *,
    query: str = "",
) -> list[str]:
    """Tiendas del fallback sin genérico (retail+tecnología; +farmacias si parece médico)."""
    wanted = set(unmatched_fallback_groups(query))
    return [store_id for store_id in available_store_ids if STORE_GROUP.get(store_id) in wanted]


def stores_for(
    query: str,
    available_store_ids: list[str],
    *,
    client: Any | None = None,
) -> list[str] | None:
    """Tiendas de los grupos del producto, en el orden de `available_store_ids`.

    Si no hay genérico, recorta a retail+tecnología; si la consulta parece
    medicamento, suma farmacias y supermercados. Lista vacía si ninguna
    disponible cae ahí.
    """
    product = resolve(query, client=client)
    wanted = set(product.groups) if product is not None else set(unmatched_fallback_groups(query))
    return [store_id for store_id in available_store_ids if STORE_GROUP.get(store_id) in wanted]


def products_for_letter(letter: str, *, client: Any | None = None) -> list[GenericProduct]:
    text = (letter or "").strip()
    if not text:
        return []
    bucket = letter_bucket(text[:1])
    redis = _redis(client)
    ids: list[str] = []
    if redis is not None:
        try:
            ensure_loaded(client=redis)
            ids = sorted(redis.smembers(f"{PREFIX}letter:{bucket}") or [])
        except Exception:
            ids = []
            redis = None
    if redis is None:
        ids = list(_memory_index().letters.get(bucket) or ())
    products = []
    for product_id in ids:
        item = _product_by_id(product_id, client=redis if redis is not None else False)
        if item is not None:
            products.append(item)
    products.sort(key=lambda item: (fold(item.name), item.id))
    return products


def ensure_loaded(
    *,
    client: Any | None = None,
    force: bool = False,
    repo: Any | None = None,
    sync_json: bool = False,
) -> dict[str, Any]:
    """Carga el índice en Redis si falta o cambió la semilla. Siempre deja memoria lista.

    La semilla sale de Mongo (JSON si Mongo está vacío o caído). `force` reescribe
    Redis aunque el hash coincida (renovación diaria). `sync_json` inserta ids del
    JSON que aún no están en Mongo, sin pisar documentos existentes.
    """
    redis = _redis(client)
    if (
        not force
        and not sync_json
        and repo is None
        and redis is not None
        and _MEMORY is not None
        and _redis_current(redis, _MEMORY.seed_hash)
    ):
        meta = redis.hgetall(META_KEY) or {}
        return {
            "backend": "redis",
            "source": meta.get("source") or "mongo",
            "version": int(meta.get("version") or _MEMORY.version),
            "seed_hash": meta.get("seed_hash") or _MEMORY.seed_hash,
            "count": int(meta.get("count") or len(_MEMORY.by_id)),
            "loaded_at": meta.get("loaded_at") or _now(),
        }
    version, digest, products, source = load_active_seed(
        repo=repo, sync_json=sync_json or force
    )
    _set_memory(version, digest, products)
    if redis is None:
        return {
            "backend": "memory",
            "source": source,
            "version": version,
            "seed_hash": digest,
            "count": len(products),
            "loaded_at": _now(),
        }
    with _LOCK:
        if not force and _redis_current(redis, digest):
            meta = redis.hgetall(META_KEY) or {}
            return {
                "backend": "redis",
                "source": meta.get("source") or source,
                "version": int(meta.get("version") or version),
                "seed_hash": meta.get("seed_hash") or digest,
                "count": int(meta.get("count") or len(products)),
                "loaded_at": meta.get("loaded_at") or _now(),
            }
        if not force and source == "json" and (redis.hget(META_KEY, "source") == "mongo"):
            meta = redis.hgetall(META_KEY) or {}
            return {
                "backend": "redis",
                "source": meta.get("source") or "mongo",
                "version": int(meta.get("version") or version),
                "seed_hash": meta.get("seed_hash") or digest,
                "count": int(meta.get("count") or len(products)),
                "loaded_at": meta.get("loaded_at") or _now(),
            }
        written = _write_redis(redis, version, digest, products, source=source)
        logger.info("Índice de productos: %s genéricos en Redis desde %s", written["count"], source)
        return written


def public_payload(
    query: str,
    chosen: list[str],
    *,
    applied: bool,
    client: Any | None = None,
) -> dict[str, Any] | None:
    found = resolve(query, client=client)
    if found is None:
        return None
    return found.to_public(store_count=len(chosen), applied=applied)


def _parse_product(item: dict[str, Any]) -> GenericProduct:
    product_id = fold(str(item.get("id") or "")).replace(" ", "-")
    name = str(item.get("name") or "").strip()
    aliases = tuple(str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip())
    groups = tuple(str(group).strip().lower() for group in (item.get("groups") or []) if str(group).strip())
    if not product_id or not name or not groups:
        raise ValueError(f"Producto genérico incompleto: {item!r}")
    unknown = [group for group in groups if group not in GROUP_TITLES]
    if unknown:
        raise ValueError(f"{product_id}: grupos desconocidos {', '.join(unknown)}")
    ordered = tuple(group for group in groups if group in GROUP_ORDER)
    return GenericProduct(id=product_id, name=name, aliases=aliases, groups=ordered)


def _validate_products(products: list[GenericProduct]) -> None:
    ids: set[str] = set()
    aliases: dict[str, str] = {}
    for product in products:
        if product.id in ids:
            raise ValueError(f"Producto duplicado: {product.id}")
        ids.add(product.id)
        for key in product.keys():
            owner = aliases.get(key)
            if owner and owner != product.id:
                raise ValueError(f"Alias «{key}» choca entre {owner} y {product.id}")
            aliases[key] = product.id
    if not products:
        raise ValueError("La semilla de productos genéricos está vacía")


def _candidates(query: str) -> list[str]:
    folded = fold(query)
    tokens = _TOKEN_RE.findall(folded)
    spans: list[str] = []
    count = len(tokens)
    for length in range(count, 0, -1):
        for start in range(0, count - length + 1):
            chunk = tokens[start : start + length]
            phrase = " ".join(chunk)
            spans.append(phrase)
            compact = "".join(chunk)
            if compact != phrase:
                spans.append(compact)
    seen: set[str] = set()
    ordered: list[str] = []
    for item in spans:
        if item in seen or len(item) < 2 or item.isdigit():
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def _resolve_memory(query: str) -> ResolvedProduct | None:
    memory = _memory_index()
    for alias in _candidates(query):
        product_id = memory.aliases.get(alias)
        if not product_id:
            continue
        product = memory.by_id.get(product_id)
        if product is None:
            continue
        return ResolvedProduct(product.id, product.name, product.groups, alias)
    return None


def _resolve_redis(redis: Any, query: str) -> ResolvedProduct | None:
    aliases = _candidates(query)
    if not aliases:
        return None
    keys = [f"{PREFIX}alias:{alias}" for alias in aliases]
    values = redis.mget(keys)
    for alias, product_id in zip(aliases, values or []):
        if not product_id:
            continue
        product = _load_product(redis, product_id)
        if product is None:
            continue
        return ResolvedProduct(product.id, product.name, product.groups, alias)
    return None


def _product_by_id(product_id: str, *, client: Any) -> GenericProduct | None:
    if client and client is not False:
        return _load_product(client, product_id)
    return _memory_index().by_id.get(product_id)


def _load_product(redis: Any, product_id: str) -> GenericProduct | None:
    raw = redis.get(f"{PREFIX}product:{product_id}")
    if not raw:
        return _memory_index().by_id.get(product_id)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return _memory_index().by_id.get(product_id)
    return GenericProduct(
        id=str(payload.get("id") or product_id),
        name=str(payload.get("name") or product_id),
        aliases=tuple(payload.get("aliases") or ()),
        groups=tuple(payload.get("groups") or ()),
    )


def _memory_index() -> _MemoryIndex:
    global _MEMORY
    if _MEMORY is None:
        version, digest, products = load_seed()
        _set_memory(version, digest, products)
    assert _MEMORY is not None
    return _MEMORY


def _set_memory(version: int, digest: str, products: list[GenericProduct]) -> None:
    global _MEMORY
    by_id = {item.id: item for item in products}
    aliases: dict[str, str] = {}
    letters: dict[str, list[str]] = {}
    for item in products:
        for key in item.keys():
            aliases.setdefault(key, item.id)
        letters.setdefault(item.letter(), []).append(item.id)
    _MEMORY = _MemoryIndex(
        version=version,
        seed_hash=digest,
        by_id=by_id,
        aliases=aliases,
        letters={key: tuple(sorted(value)) for key, value in letters.items()},
    )


def _redis(client: Any | None) -> Any | None:
    if client is False:
        return None
    if client is not None:
        return client
    return connect_redis()


def _redis_current(redis: Any, digest: str) -> bool:
    try:
        return redis.hget(META_KEY, "seed_hash") == digest
    except Exception:
        return False


def _write_redis(
    redis: Any,
    version: int,
    digest: str,
    products: list[GenericProduct],
    *,
    source: str = "json",
) -> dict[str, Any]:
    previous = set(_manifest(redis))
    keys: list[str] = [META_KEY, MANIFEST_KEY, ALL_KEY]
    letters: dict[str, list[str]] = {}
    for product in products:
        product_key = f"{PREFIX}product:{product.id}"
        redis.set(
            product_key,
            json.dumps(
                {
                    "id": product.id,
                    "name": product.name,
                    "aliases": list(product.aliases),
                    "groups": list(product.groups),
                },
                ensure_ascii=False,
            ),
        )
        keys.append(product_key)
        for alias in product.keys():
            alias_key = f"{PREFIX}alias:{alias}"
            redis.set(alias_key, product.id)
            keys.append(alias_key)
        letters.setdefault(product.letter(), []).append(product.id)
    for letter, ids in letters.items():
        letter_key = f"{PREFIX}letter:{letter}"
        redis.delete(letter_key)
        if ids:
            redis.sadd(letter_key, *ids)
        keys.append(letter_key)
    redis.delete(ALL_KEY)
    if products:
        redis.zadd(ALL_KEY, {item.id: 0 for item in products})
    loaded_at = _now()
    redis.hset(
        META_KEY,
        mapping={
            "version": str(version),
            "seed_hash": digest,
            "loaded_at": loaded_at,
            "count": str(len(products)),
            "source": source,
        },
    )
    redis.set(MANIFEST_KEY, json.dumps(sorted(set(keys))))
    stale = previous - set(keys)
    if stale:
        redis.delete(*stale)
    return {
        "backend": "redis",
        "source": source,
        "version": version,
        "seed_hash": digest,
        "count": len(products),
        "loaded_at": loaded_at,
    }


def _manifest(redis: Any) -> list[str]:
    raw = redis.get(MANIFEST_KEY)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(item) for item in payload] if isinstance(payload, list) else []


def _now() -> str:
    return datetime.now(TZ).isoformat()


def _product_payloads(products: list[GenericProduct]) -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "name": item.name,
            "aliases": list(item.aliases),
            "groups": list(item.groups),
        }
        for item in products
    ]


def _connect_mongo() -> Any | None:
    try:
        from retail.mongo import ProductRepository

        repo = ProductRepository()
        if repo.ping():
            return repo
        repo.close()
    except Exception:
        logger.debug("Mongo no disponible para el índice de productos", exc_info=True)
    return None


def _usable_alias_token(token: str, claimed: set[str]) -> bool:
    if len(token) < 2 or token.isdigit() or token in claimed:
        return False
    if token in ALIAS_STOPWORDS or token in ALIAS_UNITS:
        return False
    return True


def _claimed_alias_tokens(product: ResolvedProduct, *, client: Any | None = None) -> set[str]:
    claimed: set[str] = {product.id, fold(product.name), fold(product.matched_alias)}
    claimed.update(_TOKEN_RE.findall(fold(product.id)))
    claimed.update(_TOKEN_RE.findall(fold(product.name)))
    claimed.update(_TOKEN_RE.findall(fold(product.matched_alias)))
    redis = _redis(client)
    item = _product_by_id(product.id, client=redis if redis is not None else False)
    if item is None:
        return {token for token in claimed if token}
    for key in item.keys():
        claimed.add(key)
        claimed.update(_TOKEN_RE.findall(key))
    return {token for token in claimed if token}


def _alias_owner(token: str, *, client: Any | None = None) -> str | None:
    redis = _redis(client)
    if redis is not None:
        try:
            found = redis.get(f"{PREFIX}alias:{token}")
            if found:
                return str(found)
        except Exception:
            logger.debug("No se pudo leer alias %s en Redis", token, exc_info=True)
    memory = _memory_index()
    owner = memory.aliases.get(token)
    if owner:
        return owner
    other = memory.by_id.get(token)
    return other.id if other is not None else None


def _merge_groups(current: tuple[str, ...], extra: list[str]) -> tuple[str, ...]:
    wanted = set(current) | {group for group in extra if group in GROUP_TITLES and group != "otros"}
    return tuple(group for group in GROUP_ORDER if group in wanted)


def _patch_live_groups(product_id: str, groups: list[str], *, client: Any | None = None) -> None:
    extra = [group for group in groups if group in GROUP_TITLES and group != "otros"]
    if not extra:
        return
    with _LOCK:
        memory = _memory_index()
        current = memory.by_id.get(product_id)
        if current is not None:
            merged = _merge_groups(current.groups, extra)
            if merged != current.groups:
                memory.by_id[product_id] = GenericProduct(
                    current.id, current.name, current.aliases, merged
                )
    redis = _redis(client)
    if redis is None:
        return
    try:
        key = f"{PREFIX}product:{product_id}"
        raw = redis.get(key)
        payload: dict[str, Any]
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"id": product_id, "name": product_id, "aliases": [], "groups": []}
        else:
            payload = {"id": product_id, "name": product_id, "aliases": [], "groups": []}
        payload["groups"] = list(_merge_groups(tuple(payload.get("groups") or ()), extra))
        redis.set(
            key,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception:
        logger.debug("No se pudo parchar grupos Redis de %s", product_id, exc_info=True)


def _patch_live_aliases(product_id: str, aliases: list[str], *, client: Any | None = None) -> None:
    extra = [fold(item) for item in aliases if fold(item)]
    extra = [item for item in extra if len(item) >= 2]
    if not extra:
        return
    with _LOCK:
        memory = _memory_index()
        current = memory.by_id.get(product_id)
        if current is not None:
            merged_aliases = tuple(
                dict.fromkeys([*current.aliases, *[item for item in extra if item != current.id]])
            )
            updated = GenericProduct(current.id, current.name, merged_aliases, current.groups)
            memory.by_id[product_id] = updated
            for key in updated.keys():
                memory.aliases.setdefault(key, product_id)
    redis = _redis(client)
    if redis is None:
        return
    try:
        key = f"{PREFIX}product:{product_id}"
        raw = redis.get(key)
        payload: dict[str, Any]
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"id": product_id, "name": product_id, "aliases": [], "groups": []}
        else:
            payload = {"id": product_id, "name": product_id, "aliases": [], "groups": []}
        payload["aliases"] = list(dict.fromkeys([*(payload.get("aliases") or []), *extra]))
        redis.set(key, json.dumps(payload, ensure_ascii=False))
        patched = GenericProduct(
            str(payload.get("id") or product_id),
            str(payload.get("name") or product_id),
            tuple(payload.get("aliases") or ()),
            tuple(payload.get("groups") or ()),
        )
        for alias in patched.keys():
            redis.set(f"{PREFIX}alias:{alias}", product_id)
    except Exception:
        logger.debug("No se pudo parchar alias Redis de %s", product_id, exc_info=True)


def _feed_search_now(
    query: str,
    product_index: dict[str, Any] | None,
    *,
    store_count: int,
    applied: bool,
    repo: Any | None = None,
) -> None:
    close = False
    if repo is None:
        try:
            from retail.search import connect_repo

            repo = connect_repo()
            close = repo is not None
        except Exception:
            return
    if repo is None:
        return
    try:
        product_id = str((product_index or {}).get("id") or "").strip() or None
        groups = [str(item) for item in ((product_index or {}).get("groups") or []) if item]
        repo.save_product_index_query(
            {
                "query": query,
                "folded": fold(query),
                "product_id": product_id,
                "groups": groups,
                "store_count": store_count,
                "applied": applied,
                "unmatched": product_id is None,
                "created_at": datetime.now(timezone.utc),
            }
        )
        if product_id:
            repo.bump_product_index_hit(product_id)
            try:
                added = feed_query_aliases(query, repo=repo)
                if added:
                    logger.info("Índice %s: alias nuevos %s", product_id, ", ".join(added))
            except Exception:
                logger.debug("No se pudieron indexar alias de «%s»", query, exc_info=True)
    except Exception:
        logger.debug("No se pudo alimentar el índice de productos", exc_info=True)
    finally:
        if close and repo is not None:
            try:
                repo.close()
            except Exception:
                pass
