from __future__ import annotations

import os
import re
import threading
from hashlib import sha256
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from retail.models import Product

DEFAULT_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
DEFAULT_DB = os.environ.get("MONGODB_DB", "scraping")
DEFAULT_COLLECTION = "products"
APP_REQUESTS_COLLECTION = "app_requests"
APP_CLICKS_COLLECTION = "app_clicks"
NOTIFICATION_COOLDOWN_DAYS = 5

# Un punto por día caben poco más de trece meses, que es lo que hace falta para
# comparar un precio contra el mismo mes del año pasado.
HISTORY_LIMIT = 400
_INDEXED_DATABASES: set[tuple[str, str, str]] = set()
_INDEX_LOCK = threading.Lock()

# Búsqueda web: no traer miniaturas binarias ni historial (se cargan aparte).
SEARCH_FIND_PROJECTION: dict[str, int] = {
    "_id": 0,
    "thumbnail": 0,
    "price_history": 0,
}
SEARCH_FIND_MAX_TIME_MS = 1200
SEARCH_FIND_ID_LIMIT = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def batch_run_is_stale(doc: dict[str, Any], *, cutoff: datetime) -> bool:
    """Una corrida en curso envejece por su último progreso, no por la hora de inicio.

    Retail puede tardar muchas horas y seguir guardando productos. Una pausa
    no cuenta como abandono.
    """
    if doc.get("status") != "running" or doc.get("phase") == "paused":
        return False
    activity = _as_utc(doc.get("activity_at")) or _as_utc(doc.get("created_at"))
    if activity is None:
        return True
    return activity < cutoff


def _json_time(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _day(value: Any) -> str:
    return str(value or "")[:10]


def stable_product_id(item: dict[str, Any]) -> str:
    """Prefiere ID/SKU de tienda y usa una URL canónica solo como respaldo."""
    for field in ("product_id", "sku_id"):
        value = str(item.get(field) or "").strip()
        if value:
            return value
    raw_url = str(item.get("url") or "").strip()
    if not raw_url:
        return ""
    parsed = urlsplit(raw_url)
    canonical = urlunsplit((
        parsed.scheme.lower() or "https",
        parsed.netloc.lower(),
        re.sub(r"/+", "/", parsed.path).rstrip("/") or "/",
        "",
        "",
    ))
    return f"url:{sha256(canonical.encode('utf-8')).hexdigest()[:24]}"


_ALERT_RULE_LABELS = {
    "price_drop_percent": "Bajó de precio (%)",
    "price_drop_amount": "Bajó de precio ($)",
    "cross_store_gap": "Mejor precio entre tiendas",
    "below_median": "Bajo su precio habitual",
    "watch_target": "Precio objetivo",
}


def _alert_rule_label(rule: Any) -> str:
    parts = [part for part in str(rule or "").split("+") if part]
    if not parts:
        return ""
    seen: list[str] = []
    for part in parts:
        label = _ALERT_RULE_LABELS.get(part, part)
        if label not in seen:
            seen.append(label)
    return " · ".join(seen)


def should_record(
    previous: tuple[Any, ...] | None,
    price: Any,
    day: str,
    price_normal: Any = None,
) -> bool:
    """Si este precio merece un punto nuevo en el historial.

    Se guarda uno por día, y además cualquier cambio dentro del mismo día. Sin
    esta condición el historial se llenaba de repeticiones: en una corrida del
    catálogo de categorías un mismo televisor aparece en varias búsquedas y
    cada una empujaba su punto, así que la ventana se gastaba en días en vez de
    meses y las estadísticas de precio se quedaban sin pasado que mirar.
    """
    if previous is None:
        return True
    last_price, last_day = previous[:2]
    last_normal = previous[2] if len(previous) > 2 else None
    return last_price != price or last_normal != price_normal or last_day != day


def _document(product: Product, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data = product.to_dict(flatten_specs=False)
    data["updated_at"] = now
    if extra:
        data.update(extra)
    return data


def catalog_browse_filter(category: str | None = None) -> dict[str, Any]:
    """Filtro del catálogo: el calzado exige que el producto realmente sea calzado.

    `catalog_category` es metadato de la búsqueda que lo guardó y datos antiguos
    pueden tener productos ajenos dentro de categorías masivas. Para calzado,
    además de esa etiqueta, verificamos el nombre o la categoría propia de tienda.
    """
    match: dict[str, Any] = {"price": {"$gt": 0}}
    clean = str(category or "").strip()
    if not clean:
        return match
    accent_groups = {
        "a": "aáàäâ", "e": "eéèëê", "i": "iíìïî",
        "o": "oóòöô", "u": "uúùüû", "n": "nñ",
    }
    pattern_parts = []
    for char in clean:
        family = next((values for values in accent_groups.values() if char.lower() in values), None)
        pattern_parts.append(f"[{family}]" if family else re.escape(char))
    pattern = "".join(pattern_parts)
    match["catalog_category"] = {"$regex": f"^{pattern}$", "$options": "i"}
    from retail.relevance import fold

    if fold(clean) in {"calzado", "calzados", "zapatos", "zapato", "footwear"}:
        footwear = re.compile(
            r"zapatill|zapato|calzad|botas?|botines?|sandalias?|chalas?|chanclas?|"
            r"pantuflas?|mocasines?|alpargatas?|crocs|sneakers?|slippers?",
            re.I,
        )
        match["$and"] = [
            {"$or": [{"name": footwear}, {"category": footwear}]},
        ]
    return match


class ProductRepository:
    def __init__(
        self,
        uri: str = DEFAULT_URI,
        database: str = DEFAULT_DB,
        collection: str = DEFAULT_COLLECTION,
    ) -> None:
        from pymongo import ASCENDING, DESCENDING, MongoClient
        from pymongo.errors import OperationFailure

        self.client = MongoClient(uri, serverSelectionTimeoutMS=4000)
        self.db = self.client[database]
        self.collection = self.db[collection]
        self.searches = self.db["searches"]
        self.alerts = self.db["alerts"]
        self.batch_runs = self.db["batch_runs"]
        self.watches = self.db["watches"]
        self.price_alerts = self.db["price_alerts"]
        self.price_alert_sends = self.db["price_alert_sends"]
        self.user_notification_sends = self.db["user_notification_sends"]
        self.predictive_alert_sends = self.db["predictive_alert_sends"]
        self.forecasts = self.db["forecasts"]
        self.scrape_priorities = self.db["scrape_priorities"]
        self.price_patterns = self.db["price_patterns"]
        self.users = self.db["users"]
        self.product_reviews = self.db["product_reviews"]
        self.app_settings = self.db["app_settings"]
        self.categories = self.db["categories"]
        self.store_categories = self.db["store_categories"]
        self.product_index_seed = self.db["product_index_seed"]
        self.product_index_queries = self.db["product_index_queries"]
        self.search_results = self.db["search_results"]
        self.real_offer_jobs = self.db["real_offer_jobs"]
        self.daily_real_offers = self.db["daily_real_offers"]
        self.app_requests = self.db[APP_REQUESTS_COLLECTION]
        self.short_links = self.db["short_links"]
        # Validar los mismos índices para cada producto agrega muchas idas a
        # Mongo. En un proceso basta hacerlo al abrir la primera conexión.
        index_key = (str(uri), str(database), str(collection))
        with _INDEX_LOCK:
            if index_key in _INDEXED_DATABASES:
                return
        self.collection.create_index(
            [("store", ASCENDING), ("product_id", ASCENDING)],
            unique=True,
            name="store_product_id",
        )
        for keys in (
            [("compare_code", ASCENDING), ("price", ASCENDING)],
            [("last_search_query", ASCENDING), ("updated_at", DESCENDING)],
            # Lookups exactos por id/sku sin forzar COLLSCAN (find_by_query).
            [("product_id", ASCENDING)],
            [("sku_id", ASCENDING)],
            # Facetas / Explora rápido sin COLLSCAN completo.
            [("catalog_category", ASCENDING)],
        ):
            try:
                self.collection.create_index(keys)
            except OperationFailure:
                pass
        try:
            self.collection.create_index([("name", "text"), ("brand", "text"), ("sku_id", "text")])
        except OperationFailure:
            pass
        try:
            self.short_links.create_index("code", unique=True, name="short_link_code")
            self.short_links.create_index(
                [("store", ASCENDING), ("product_id", ASCENDING)],
                unique=True,
                name="short_link_product",
            )
        except OperationFailure:
            pass
        try:
            self.collection.create_index([("availability", ASCENDING)])
        except OperationFailure:
            pass
        try:
            self.searches.create_index([("query", ASCENDING), ("created_at", DESCENDING)])
            self.searches.create_index([("created_at", DESCENDING)], name="search_created_at")
            self.search_results.create_index(
                [("search_id", ASCENDING), ("product_id", ASCENDING)],
                unique=True,
                name="search_product_unique",
            )
            self.search_results.create_index(
                [("search_id", ASCENDING), ("position", ASCENDING)],
                name="search_result_order",
            )
            self.search_results.create_index(
                [("product_id", ASCENDING), ("created_at", DESCENDING)],
                name="product_search_history",
            )
        except OperationFailure:
            pass
        try:
            # Colecciones nuevas: remover únicamente duplicados de ellas antes
            # de activar la garantía única (útil si quedaron de una prueba).
            for target, key_fields in (
                (self.real_offer_jobs, ("product_id", "day", "price_signature")),
                (self.daily_real_offers, ("product_id", "day")),
            ):
                groups = target.aggregate([
                    {
                        "$group": {
                            "_id": {field: f"${field}" for field in key_fields},
                            "ids": {"$push": "$_id"},
                            "count": {"$sum": 1},
                        }
                    },
                    {"$match": {"count": {"$gt": 1}}},
                ])
                for duplicate in groups:
                    target.delete_many({"_id": {"$in": duplicate["ids"][1:]}})
            self.real_offer_jobs.create_index(
                [("product_id", ASCENDING), ("day", ASCENDING), ("price_signature", ASCENDING)],
                unique=True,
                name="real_offer_job_dedupe",
            )
            self.real_offer_jobs.create_index(
                [("status", ASCENDING), ("available_at", ASCENDING)],
                name="real_offer_job_claim",
            )
            self.daily_real_offers.create_index(
                [("product_id", ASCENDING), ("day", ASCENDING)],
                unique=True,
                name="daily_real_offer_product",
            )
            self.daily_real_offers.create_index(
                [("day", ASCENDING), ("is_real", ASCENDING), ("evaluated_at", DESCENDING)],
                name="daily_real_offer_listing",
            )
        except OperationFailure:
            pass
        try:
            self.collection.create_index([("catalog_id", ASCENDING), ("updated_at", DESCENDING)])
        except OperationFailure:
            pass
        try:
            self.batch_runs.create_index([("started_at", DESCENDING)])
            self.batch_runs.create_index([("grupo", ASCENDING), ("started_at", DESCENDING)])
            self.batch_runs.create_index([("tienda", ASCENDING), ("started_at", DESCENDING)])
            self.batch_runs.create_index([("job", ASCENDING), ("started_at", DESCENDING)])
            self.batch_runs.create_index([("scope", ASCENDING), ("started_at", DESCENDING)])
            self.batch_runs.create_index([("status", ASCENDING), ("started_at", DESCENDING)])
        except OperationFailure:
            pass
        try:
            self.categories.create_index(
                [("store", ASCENDING), ("id", ASCENDING)],
                unique=True,
                name="category_key",
            )
            self.categories.create_index([("store", ASCENDING), ("parent_id", ASCENDING)])
            self.categories.create_index([("store", ASCENDING), ("name", ASCENDING)])
        except OperationFailure:
            pass
        try:
            self.alerts.create_index([("day", DESCENDING), ("saving", DESCENDING)])
        except OperationFailure:
            pass
        try:
            self.users.create_index("email", unique=True, name="user_email")
            self.users.create_index(
                "confirmation_token_hash",
                sparse=True,
                name="user_confirmation_token",
            )
            self.users.create_index(
                "password_reset_token_hash",
                sparse=True,
                name="user_password_reset_token",
            )
        except OperationFailure:
            pass
        try:
            self.product_reviews.create_index(
                [("user_id", ASCENDING), ("store", ASCENDING), ("product_id", ASCENDING)],
                unique=True,
                name="product_review_user_product",
            )
            self.product_reviews.create_index(
                [("store", ASCENDING), ("product_id", ASCENDING), ("updated_at", DESCENDING)],
                name="product_review_latest",
            )
        except OperationFailure:
            pass
        try:
            self.watches.drop_index("watch_key")
        except OperationFailure:
            pass
        try:
            self.watches.create_index(
                [("user_id", ASCENDING), ("compare_code", ASCENDING), ("query", ASCENDING)],
                unique=True,
                name="watch_user_key",
            )
        except OperationFailure:
            pass
        try:
            self.price_alerts.create_index(
                [("user_id", ASCENDING), ("store", ASCENDING), ("product_id", ASCENDING)],
                unique=True,
                name="price_alert_user_product",
            )
            self.price_alerts.create_index(
                [("store", ASCENDING), ("product_id", ASCENDING), ("active", ASCENDING)],
                name="price_alert_product",
            )
        except OperationFailure:
            pass
        try:
            self.price_alert_sends.create_index(
                [
                    ("user_id", ASCENDING),
                    ("store", ASCENDING),
                    ("product_id", ASCENDING),
                    ("previous_price", ASCENDING),
                    ("price", ASCENDING),
                ],
                unique=True,
                name="price_alert_send_once",
            )
            self.price_alert_sends.create_index(
                [("user_id", ASCENDING), ("store", ASCENDING), ("product_id", ASCENDING),
                 ("price", ASCENDING), ("created_at", DESCENDING)],
                name="price_alert_recent_price",
            )
        except OperationFailure:
            pass
        try:
            self.user_notification_sends.create_index(
                [("user_id", ASCENDING), ("channel", ASCENDING), ("entity_key", ASCENDING)],
                unique=True,
                name="user_notification_product_once",
            )
            self.user_notification_sends.create_index("last_sent_at", name="user_notification_last_sent")
        except OperationFailure:
            pass
        try:
            self.predictive_alert_sends.create_index(
                [("user_id", ASCENDING), ("forecast_key", ASCENDING), ("kind", ASCENDING), ("generated_at", ASCENDING)],
                unique=True,
                name="predictive_alert_send_once",
            )
        except OperationFailure:
            pass
        try:
            self.forecasts.create_index(
                [("forecast_key", ASCENDING), ("model", ASCENDING), ("generated_at", DESCENDING)],
                name="forecast_offer_signal",
            )
        except OperationFailure:
            pass
        try:
            self.scrape_priorities.create_index("catalog_id", unique=True, name="scrape_priority_catalog")
            self.scrape_priorities.create_index([("next_due_at", ASCENDING), ("score", DESCENDING)])
            self.price_patterns.create_index("product_key", unique=True, name="price_pattern_product")
            self.price_patterns.create_index("expires_at", expireAfterSeconds=0, name="price_pattern_expiry")
        except OperationFailure:
            pass
        try:
            self.alerts.create_index(
                [("day", ASCENDING), ("catalog_id", ASCENDING), ("rule", ASCENDING), ("store", ASCENDING), ("compare_code", ASCENDING)],
                name="alert_dedup",
            )
            self.alerts.create_index(
                [("day", ASCENDING), ("compare_code", ASCENDING)],
                name="alert_product_day",
            )
            self.alerts.create_index([("run", ASCENDING), ("saving", DESCENDING)], name="alert_run")
        except OperationFailure:
            pass
        try:
            self.product_index_seed.create_index("id", unique=True, name="product_index_seed_id")
        except OperationFailure:
            pass
        try:
            self.store_categories.create_index("id", unique=True, name="store_categories_id")
            self.store_categories.create_index([("sort_order", ASCENDING), ("id", ASCENDING)])
        except OperationFailure:
            pass
        try:
            self.app_requests.create_index(
                [("day", ASCENDING), ("hour", ASCENDING), ("ip", ASCENDING), ("country", ASCENDING)],
                unique=True,
                name="app_request_bucket",
            )
            self.app_requests.create_index([("day", ASCENDING)], name="app_request_day")
        except OperationFailure:
            pass
        try:
            self.product_index_queries.create_index([("folded", ASCENDING), ("created_at", DESCENDING)])
            self.product_index_queries.create_index([("unmatched", ASCENDING), ("created_at", DESCENDING)])
            self.product_index_queries.create_index([("product_id", ASCENDING), ("created_at", DESCENDING)])
        except OperationFailure:
            pass
        try:
            quotes = self.db["business_quotes"]
            quotes.create_index(
                [("owner_id", ASCENDING), ("created_at", DESCENDING)],
                name="business_quote_owner_created",
            )
            quotes.create_index(
                [("owner_id", ASCENDING), ("status", ASCENDING)],
                name="business_quote_owner_status",
            )
            quote_events = self.db["business_quote_events"]
            quote_events.create_index(
                [("owner_id", ASCENDING), ("at", DESCENDING)],
                name="business_quote_event_owner_at",
            )
            quote_events.create_index(
                [("quote_id", ASCENDING), ("at", ASCENDING)],
                name="business_quote_event_quote_at",
            )
        except OperationFailure:
            pass
        with _INDEX_LOCK:
            _INDEXED_DATABASES.add(index_key)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> ProductRepository:
        self.client.admin.command("ping")
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def ping(self) -> bool:
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    def last_points(self, keys: list[tuple[str, str]]) -> dict[tuple[str, str], tuple[Any, str, Any]]:
        """Último precio guardado y el día en que se guardó, por producto."""
        wanted = [(store, product_id) for store, product_id in keys if store and product_id]
        if not wanted:
            return {}
        cursor = self.collection.find(
            {"$or": [{"store": store, "product_id": product_id} for store, product_id in wanted]},
            {"store": 1, "product_id": 1, "price_history": {"$slice": -1}},
        )
        found: dict[tuple[str, str], tuple[Any, str]] = {}
        for item in cursor:
            points = item.get("price_history") or []
            if not points:
                continue
            key = (item.get("store") or "", item.get("product_id") or "")
            found[key] = (
                points[-1].get("price"),
                _day(points[-1].get("scraped_at")),
                points[-1].get("price_normal"),
            )
        return found

    def _write_products(
        self,
        products: list[Product],
        extras: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, int]:
        from pymongo import UpdateOne

        seen: set[tuple[str, str]] = set()
        unique: list[Product] = []
        for product in products:
            key = (product.store, product.product_id)
            if not product.product_id or key in seen:
                continue
            seen.add(key)
            unique.append(product)
        if not unique:
            return {"upserted": 0, "modified": 0, "matched": 0}

        # Respaldo opcional: completa condición/logística cuando la API de la
        # tienda no los entrega. Está desactivado salvo configuración explícita.
        try:
            from retail.structured_extraction import enrich_products

            unique = enrich_products(unique)
        except Exception:
            pass

        previous = self.last_points([(product.store, product.product_id) for product in unique])
        keys = [(product.store, product.product_id) for product in unique]
        manual_overrides: dict[tuple[str, str], str] = {}
        for start in range(0, len(keys), 500):
            query = {
                "$or": [
                    {"store": store, "product_id": product_id}
                    for store, product_id in keys[start : start + 500]
                ]
            }
            for row in self.collection.find(
                query, {"store": 1, "product_id": 1, "entity_override": 1}
            ):
                if row.get("entity_override"):
                    manual_overrides[(
                        str(row.get("store") or ""), str(row.get("product_id") or "")
                    )] = str(row["entity_override"])
        operations: list[UpdateOne] = []
        now = _now()
        for product in unique:
            key = (product.store, product.product_id)
            extra = dict(extras.get(key) or {})
            manual = manual_overrides.get(key)
            if manual:
                # Una nueva pasada del scraper no debe deshacer una corrección
                # de identidad tomada por el administrador.
                product.entity_override = manual
                extra.update({
                    "compare_code": manual,
                    "entity_id": manual,
                    "entity_confidence": 1.0,
                    "entity_match_method": "manual",
                })
            document = _document(product, now, extra)
            # Una búsqueda/listado puede traer menos datos que la ficha. Nunca
            # debe borrar la imagen válida obtenida en un scraping anterior.
            if not product.image_url:
                document.pop("image_url", None)
            if not product.image_urls:
                document.pop("image_urls", None)
            update: dict[str, Any] = {
                "$set": document,
                "$setOnInsert": {"created_at": now},
            }
            if should_record(
                previous.get(key),
                product.price,
                _day(product.scraped_at or now),
                product.price_normal,
            ):
                point = {
                    "price": product.price,
                    "price_offer": product.price,
                    "price_normal": product.price_normal,
                    "price_basis": "all_payment" if product.price_all_payment else "published",
                    "scraped_at": product.scraped_at,
                    "search_query": extra.get("last_search_query"),
                    "is_lowest": extra.get("is_lowest"),
                }
                update["$push"] = {"price_history": {"$each": [point], "$slice": -HISTORY_LIMIT}}
            operations.append(
                UpdateOne({"store": product.store, "product_id": product.product_id}, update, upsert=True)
            )

        changes: list[dict[str, Any]] = []
        try:
            from retail.price_alerts import price_deltas

            changes = price_deltas(previous, unique)
        except Exception as exc:
            print(f"Alerta de precio: no se pudo comparar el precio anterior ({exc}).")
        result = self.collection.bulk_write(operations, ordered=False)
        try:
            from retail.scrape_stats import record_product_writes

            record_product_writes(previous, unique, when=now)
        except Exception as exc:
            print(f"Estadísticas de scrape: no se pudo registrar el lote ({exc}).")
        if changes:
            self._fanout_price_alerts(changes)
        return {
            "upserted": result.upserted_count,
            "modified": result.modified_count,
            "matched": result.matched_count,
        }

    def _fanout_price_alerts(self, changes: list[dict[str, Any]]) -> None:
        if not changes or not hasattr(self, "price_alerts"):
            return
        try:
            from retail.price_alerts import notify_price_changes

            notify_price_changes(self, changes)
        except Exception as exc:
            print(f"Alerta de precio: no se pudo avisar el cambio ({exc}).")

    def upsert_many(
        self,
        products: list[Product],
        *,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        if not products:
            return {"upserted": 0, "modified": 0, "matched": 0}
        shared = extra or {}
        extras = {(product.store, product.product_id): shared for product in products}
        return self._write_products(products, extras)

    def upsert_offers(
        self,
        offers: list[dict[str, Any]],
        query: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        if not offers:
            return {"upserted": 0, "modified": 0, "matched": 0}
        products: list[Product] = []
        extras: dict[tuple[str, str], dict[str, Any]] = {}
        shared = {key: value for key, value in (extra or {}).items() if value is not None}
        for offer in offers:
            payload = dict(offer)
            payload["product_id"] = stable_product_id(payload)
            product = Product.from_dict(payload)
            if not product.product_id:
                continue
            products.append(product)
            extras[(product.store, product.product_id)] = {
                "compare_code": offer.get("compare_code"),
                "entity_id": offer.get("entity_id"),
                "entity_confidence": offer.get("entity_confidence"),
                "entity_match_method": offer.get("entity_match_method"),
                "is_lowest": bool(offer.get("is_lowest")),
                "last_search_query": query,
                **shared,
            }
        if not products:
            return {"upserted": 0, "modified": 0, "matched": 0}
        return self._write_products(products, extras)

    def save_search(
        self,
        query: str,
        groups: list[dict[str, Any]],
        *,
        source: str,
        store_errors: list[dict[str, str]],
        extra: dict[str, Any] | None = None,
    ) -> str:
        from retail.relevance import fold

        now = _now()
        offers = [offer for group in groups for offer in group.get("offers") or []]
        document = {
            "query": query,
            "query_normalized": fold(query),
            "source": source,
            "created_at": now,
            "offer_count": len(offers),
            "group_count": len(groups),
            "comparable_count": sum(1 for group in groups if group.get("comparable")),
            "store_errors": store_errors,
            "schema_version": 2,
            "relation_status": "pending",
        }
        if extra:
            forbidden = {"groups", "rows", "offers", "products", "cheapest"}
            document.update({
                key: value
                for key, value in extra.items()
                if value is not None and key not in forbidden
            })
        result = self.searches.insert_one(document)
        try:
            relation_metrics = self._save_search_results(result.inserted_id, groups, created_at=now)
            self.searches.update_one(
                {"_id": result.inserted_id},
                {
                    "$set": {
                        "relation_status": "complete",
                        "result_count": relation_metrics["relations"],
                    }
                },
            )
        except Exception:
            self.searches.update_one(
                {"_id": result.inserted_id},
                {"$set": {"relation_status": "failed"}},
            )
            raise
        return str(result.inserted_id)

    def _save_search_results(
        self,
        search_id: Any,
        groups: list[dict[str, Any]],
        *,
        created_at: datetime | None = None,
    ) -> dict[str, int]:
        """Relaciona una búsqueda con productos canónicos, sin copiar su payload."""
        from pymongo import UpdateOne

        positioned: list[tuple[int, int, int, dict[str, Any], dict[str, Any]]] = []
        keys: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        position = 0
        duplicates = 0
        invalid = 0
        for group_position, group in enumerate(groups):
            for offer_position, offer in enumerate(group.get("offers") or []):
                store = str(offer.get("store") or "").strip()
                external_id = stable_product_id(offer)
                key = (store, external_id)
                if not store or not external_id:
                    invalid += 1
                    continue
                if key in seen:
                    duplicates += 1
                    continue
                seen.add(key)
                keys.append(key)
                positioned.append((position, group_position, offer_position, group, offer))
                position += 1

        canonical: dict[tuple[str, str], Any] = {}
        for start in range(0, len(keys), 500):
            wanted = keys[start : start + 500]
            for row in self.collection.find(
                {"$or": [{"store": store, "product_id": product_id} for store, product_id in wanted]},
                {"store": 1, "product_id": 1},
            ):
                canonical[(str(row.get("store") or ""), str(row.get("product_id") or ""))] = row["_id"]

        now = created_at or _now()
        operations = []
        for position, group_position, offer_position, group, offer in positioned:
            store = str(offer.get("store") or "").strip()
            external_id = stable_product_id(offer)
            canonical_id = canonical.get((store, external_id))
            if canonical_id is None:
                continue
            relation = {
                "search_id": search_id,
                "product_id": canonical_id,
                "product_key": f"{store}:{external_id}",
                "position": position,
                "group_position": group_position,
                "offer_position": offer_position,
                "created_at": now,
            }
            group_key = group.get("compare_code") or offer.get("compare_code")
            if group_key:
                relation["group_key"] = str(group_key)
            operations.append(
                UpdateOne(
                    {"search_id": search_id, "product_id": canonical_id},
                    {"$set": relation},
                    upsert=True,
                )
            )
        if operations:
            self.search_results.bulk_write(operations, ordered=False)
        return {
            "relations": len(operations),
            "missing_products": len(keys) - len(canonical),
            "duplicates": duplicates,
            "invalid": invalid,
        }

    def search_with_results(self, search_id: Any) -> dict[str, Any] | None:
        """Lee evento + productos en un único lookup, ordenado y sin N+1."""
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            ident = search_id if isinstance(search_id, ObjectId) else ObjectId(str(search_id))
        except (InvalidId, TypeError):
            return None
        rows = list(self.searches.aggregate([
            {"$match": {"_id": ident}},
            {
                "$lookup": {
                    "from": self.search_results.name,
                    "let": {"search_id": "$_id"},
                    "pipeline": [
                        {"$match": {"$expr": {"$eq": ["$search_id", "$$search_id"]}}},
                        {"$sort": {"position": 1}},
                        {
                            "$lookup": {
                                "from": self.collection.name,
                                "localField": "product_id",
                                "foreignField": "_id",
                                "pipeline": [
                                    {"$project": {
                                        "thumbnail": 0,
                                        "price_history": 0,
                                    }},
                                ],
                                "as": "product",
                            }
                        },
                        {"$set": {"product": {"$first": "$product"}}},
                    ],
                    "as": "results",
                }
            },
        ]))
        if not rows:
            return None
        event = rows[0]
        event["id"] = str(event.pop("_id"))
        for relation in event.get("results") or []:
            relation.pop("_id", None)
            relation["search_id"] = str(relation.get("search_id") or "")
            relation["product_id"] = str(relation.get("product_id") or "")
            if isinstance(relation.get("product"), dict):
                relation["product"].pop("_id", None)
        return event

    def product_index_seed_empty(self) -> bool:
        return self.product_index_seed.find_one({}, {"_id": 1}) is None

    def load_product_index_seed(self) -> tuple[int, list[dict[str, Any]]]:
        rows = list(self.product_index_seed.find({}, {"_id": 0}).sort("id", 1))
        version = 1
        for row in rows:
            if row.get("version") is not None:
                version = int(row["version"])
                break
        return version, rows

    def sync_product_index_seed(self, products: list[dict[str, Any]], version: int) -> int:
        """Inserta genéricos que aún no están. Suma alias nuevos del JSON; no pisa el resto."""
        from pymongo import UpdateOne

        now = _now()
        operations = []
        for item in products:
            product_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not product_id or not name:
                continue
            operations.append(
                UpdateOne(
                    {"id": product_id},
                    {
                        "$setOnInsert": {
                            "id": product_id,
                            "name": name,
                            "aliases": list(item.get("aliases") or []),
                            "groups": list(item.get("groups") or []),
                            "version": version,
                            "hit_count": 0,
                            "last_seen_at": None,
                            "updated_at": now,
                        }
                    },
                    upsert=True,
                )
            )
        if not operations:
            return 0
        result = self.product_index_seed.bulk_write(operations, ordered=False)
        for item in products:
            product_id = str(item.get("id") or "").strip()
            aliases = [str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip()]
            if product_id and aliases:
                self.add_product_index_aliases(product_id, aliases)
        return int(result.upserted_count or 0)

    def bump_product_index_hit(self, product_id: str) -> None:
        ident = str(product_id or "").strip()
        if not ident:
            return
        self.product_index_seed.update_one(
            {"id": ident},
            {"$inc": {"hit_count": 1}, "$set": {"last_seen_at": _now()}},
        )

    def save_product_index_query(self, document: dict[str, Any]) -> None:
        self.product_index_queries.insert_one(document)

    def add_product_index_aliases(self, product_id: str, aliases: list[str]) -> list[str]:
        ident = str(product_id or "").strip()
        wanted = [str(item).strip() for item in aliases if str(item).strip()]
        if not ident or not wanted:
            return []
        row = self.product_index_seed.find_one({"id": ident}, {"aliases": 1})
        if not row:
            return []
        existing = {str(item) for item in (row.get("aliases") or [])}
        extra = [item for item in wanted if item not in existing]
        if not extra:
            return []
        self.product_index_seed.update_one(
            {"id": ident},
            {
                "$addToSet": {"aliases": {"$each": extra}},
                "$set": {"updated_at": _now()},
            },
        )
        return extra

    def add_product_index_groups(
        self,
        product_id: str,
        groups: list[str],
        *,
        store_ids: list[str] | None = None,
    ) -> list[str]:
        ident = str(product_id or "").strip()
        wanted = [str(item).strip() for item in groups if str(item).strip()]
        stores = [str(item).strip() for item in (store_ids or []) if str(item).strip()]
        if not ident or (not wanted and not stores):
            return []
        row = self.product_index_seed.find_one({"id": ident}, {"groups": 1})
        if not row:
            return []
        existing = {str(item) for item in (row.get("groups") or [])}
        extra = [item for item in wanted if item not in existing]
        add_to_set: dict[str, Any] = {}
        if extra:
            add_to_set["groups"] = {"$each": extra}
            add_to_set["extra_groups"] = {"$each": extra}
        if stores:
            add_to_set["discovered_stores"] = {"$each": stores}
        if not add_to_set:
            return []
        self.product_index_seed.update_one(
            {"id": ident},
            {"$addToSet": add_to_set, "$set": {"updated_at": _now()}},
        )
        return extra

    def unmatched_product_index_queries(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = []
        cursor = (
            self.product_index_queries.find({"unmatched": True}, {"_id": 0})
            .sort("created_at", -1)
            .limit(max(1, int(limit)))
        )
        for item in cursor:
            rows.append(item)
        return rows

    def store_categories_empty(self) -> bool:
        return self.store_categories.find_one({}, {"_id": 1}) is None

    def load_store_categories(self) -> list[dict[str, Any]]:
        return list(
            self.store_categories.find({}, {"_id": 0}).sort([("sort_order", 1), ("id", 1)])
        )

    def get_store_category(self, category_id: str) -> dict[str, Any] | None:
        ident = str(category_id or "").strip().lower()
        if not ident:
            return None
        return self.store_categories.find_one({"id": ident}, {"_id": 0})

    def sync_store_categories(self, categories: list[dict[str, Any]]) -> int:
        """Inserta grupos nuevos desde el registry. Suma store_ids; no pisa título ni extras."""
        from pymongo import UpdateOne

        now = _now()
        operations = []
        for item in categories:
            category_id = str(item.get("id") or "").strip().lower()
            title = str(item.get("title") or "").strip()
            if not category_id or not title:
                continue
            store_ids = [
                str(store).strip().lower()
                for store in (item.get("store_ids") or [])
                if str(store).strip()
            ]
            sort_order = int(item.get("sort_order") if item.get("sort_order") is not None else 999)
            operations.append(
                UpdateOne(
                    {"id": category_id},
                    {
                        "$setOnInsert": {
                            "id": category_id,
                            "title": title,
                            "updated_at": now,
                        },
                        "$set": {"sort_order": sort_order},
                        "$addToSet": {"store_ids": {"$each": store_ids}},
                    },
                    upsert=True,
                )
            )
        if not operations:
            return 0
        result = self.store_categories.bulk_write(operations, ordered=False)
        return int(result.upserted_count or 0)

    def product_seed_ids_for_group(self, group_id: str) -> set[str]:
        """IDs de genéricos en product_index_seed cuyo `groups` incluye el grupo de tiendas."""
        ident = str(group_id or "").strip().lower()
        if not ident:
            return set()
        return {
            str(row["id"])
            for row in self.product_index_seed.find({"groups": ident}, {"id": 1})
            if row.get("id")
        }

    def persist_search(
        self,
        query: str,
        groups: list[dict[str, Any]],
        *,
        source: str,
        store_errors: list[dict[str, str]],
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        offers = [offer for group in groups for offer in group.get("offers") or []]
        saved = self.upsert_offers(offers, query, extra=extra)
        search_id = self.save_search(
            query, groups, source=source, store_errors=store_errors, extra=extra
        )
        try:
            queue = self.enqueue_real_offer_candidates(offers)
        except Exception as exc:
            print(f"Ofertas reales: no se pudo encolar candidatos ({exc}).")
            self.record_real_offer_stats({"enqueue_errors": 1})
            queue = {"candidates": 0, "enqueued": 0, "deduplicated": 0, "errors": 1}
        return {"search_id": search_id, **saved, "real_offer_queue": queue}

    def enqueue_real_offer_candidates(
        self,
        offers: list[dict[str, Any]],
        *,
        day: str | None = None,
    ) -> dict[str, int]:
        """Encola descuentos publicados por producto canónico, día y precio."""
        from pymongo.errors import DuplicateKeyError
        from retail.real_offer_worker import chile_day, price_signature, valid_discount

        unique: dict[tuple[str, str], dict[str, Any]] = {}
        for offer in offers:
            if not valid_discount(offer):
                continue
            store = str(offer.get("store") or "").strip()
            external_id = stable_product_id(offer)
            if store and external_id:
                unique[(store, external_id)] = offer
        if not unique:
            return {"candidates": 0, "enqueued": 0, "deduplicated": 0, "errors": 0}

        canonical: dict[tuple[str, str], dict[str, Any]] = {}
        keys = list(unique)
        for start in range(0, len(keys), 500):
            wanted = keys[start : start + 500]
            for row in self.collection.find(
                {"$or": [{"store": store, "product_id": product_id} for store, product_id in wanted]},
                {"store": 1, "product_id": 1, "price": 1, "price_normal": 1},
            ):
                canonical[(str(row.get("store") or ""), str(row.get("product_id") or ""))] = row

        now = _now()
        local_day = day or chile_day(now)
        enqueued = deduplicated = errors = 0
        for key, offered in unique.items():
            product = canonical.get(key)
            if not product:
                errors += 1
                continue
            signature = price_signature(product)
            document = {
                "product_id": product["_id"],
                "day": local_day,
                "price_signature": signature,
                "price": int(product.get("price") or offered.get("price") or 0),
                "price_normal": int(product.get("price_normal") or offered.get("price_normal") or 0),
                "status": "queued",
                "attempts": 0,
                "available_at": now,
                "created_at": now,
                "updated_at": now,
            }
            try:
                result = self.real_offer_jobs.update_one(
                    {
                        "product_id": product["_id"],
                        "day": local_day,
                        "price_signature": signature,
                    },
                    {"$setOnInsert": document},
                    upsert=True,
                )
                if result.upserted_id is None:
                    deduplicated += 1
                else:
                    enqueued += 1
            except DuplicateKeyError:
                deduplicated += 1
            except Exception:
                errors += 1
        self.record_real_offer_stats({
            "enqueued": enqueued,
            "deduplicated": deduplicated,
            "enqueue_errors": errors,
        })
        print(
            f"Ofertas reales: candidatos={len(unique)} encoladas={enqueued} "
            f"deduplicadas={deduplicated} errores={errors} día={local_day}."
        )
        return {
            "candidates": len(unique),
            "enqueued": enqueued,
            "deduplicated": deduplicated,
            "errors": errors,
        }

    def enqueue_today_real_offer_candidates(self, day: str | None = None) -> dict[str, int]:
        """Backfill idempotente de descuentos presentes en búsquedas del día Chile."""
        from retail.real_offer_worker import chile_day, chile_day_bounds

        local_day = day or chile_day()
        start, end = chile_day_bounds(local_day)
        product_ids = self.search_results.distinct(
            "product_id", {"created_at": {"$gte": start, "$lt": end}}
        )
        candidates = list(self.collection.find(
            {
                "_id": {"$in": product_ids},
                "price": {"$gt": 0},
                "$expr": {"$gt": ["$price_normal", "$price"]},
            },
            {
                "_id": 0, "store": 1, "product_id": 1, "price": 1,
                "price_normal": 1, "url": 1,
            },
        ))
        result = self.enqueue_real_offer_candidates(candidates, day=local_day)
        result["found_today"] = len(product_ids)
        return result

    def record_real_offer_stats(self, counters: dict[str, int]) -> None:
        increments = {
            f"counters.{key}": int(value)
            for key, value in counters.items()
            if value
        }
        update: dict[str, Any] = {"$set": {"updated_at": _now()}}
        if increments:
            update["$inc"] = increments
        self.app_settings.update_one(
            {"_id": "real_offer_worker_stats"},
            update,
            upsert=True,
        )

    def touch_real_offer_worker(self) -> None:
        self.app_settings.update_one(
            {"_id": "real_offer_worker_status"},
            {
                "$set": {
                    "heartbeat_at": _now(),
                    "host": os.environ.get("HOSTNAME") or "unknown",
                    "criterion_version": "real-offer-v1",
                }
            },
            upsert=True,
        )

    def real_offer_worker_status(self) -> dict[str, Any]:
        status = self.app_settings.find_one({"_id": "real_offer_worker_status"}) or {}
        stats = self.app_settings.find_one({"_id": "real_offer_worker_stats"}) or {}
        heartbeat = _as_utc(status.get("heartbeat_at"))
        healthy = bool(heartbeat and heartbeat >= _now() - timedelta(minutes=3))
        return {
            "healthy": healthy,
            "heartbeat_at": _json_time(heartbeat),
            "criterion_version": status.get("criterion_version"),
            "counters": stats.get("counters") or {},
            "queued": self.real_offer_jobs.count_documents({"status": {"$in": ["queued", "retry"]}}),
            "failed": self.real_offer_jobs.count_documents({"status": "failed"}),
        }

    def start_batch_run(self, data: dict[str, Any]) -> str:
        document = {
            **data,
            "status": "running",
            "phase": data.get("phase") or "starting",
            "searches": [],
            "processed": 0,
            "saved_upserted": 0,
            "saved_modified": 0,
            "created_at": _now(),
            "activity_at": _now(),
        }
        if document.get("scope") == "grupo" and document.get("grupo"):
            return self._start_group_batch_run(document)
        return str(self.batch_runs.insert_one(document).inserted_id)

    def _start_group_batch_run(self, document: dict[str, Any]) -> str:
        """Reserva el grupo antes de arrancar, compartida por web y cron del host."""
        from uuid import uuid4

        from pymongo.errors import DuplicateKeyError
        from retail.batch.group_scope import GroupBatchBusy

        group = document["grupo"]
        lock_id = f"batch_start:{group}"
        token = uuid4().hex
        now = _now()
        try:
            self.app_settings.update_one(
                {"_id": lock_id, "expires_at": {"$lte": now}},
                {"$set": {"token": token, "expires_at": now + timedelta(minutes=1)}},
                upsert=True,
            )
        except DuplicateKeyError:
            raise GroupBatchBusy(group) from None
        try:
            running = self.batch_runs.find_one({
                "grupo": group, "status": "running",
                "tienda": {"$in": [None, ""]},
                "scope": {"$nin": ["tienda", "basico"]},
            })
            if running:
                raise GroupBatchBusy(group)
            return str(self.batch_runs.insert_one(document).inserted_id)
        finally:
            self.app_settings.delete_one({"_id": lock_id, "token": token})

    def activate_group_batch_run(self, run_id: str, group: str, data: dict[str, Any]) -> None:
        """Entrega una reserva al worker una sola vez, sin crear otra corrida."""
        from bson import ObjectId
        from retail.batch.group_scope import GroupBatchBusy, GroupBatchStopped

        item = self.batch_runs.find_one({"_id": ObjectId(run_id)})
        if not item or item.get("grupo") != group or item.get("scope") != "grupo":
            raise GroupBatchBusy(group)
        if item.get("status") != "running":
            raise GroupBatchBusy(group)
        if item.get("stop_requested") or item.get("phase") == "stopping":
            raise GroupBatchStopped()
        if item.get("phase") != "starting":
            # Ya activada (p. ej. reintento); solo completa los campos nuevos.
            self.batch_runs.update_one({"_id": item["_id"], "status": "running"}, {"$set": data})
            return
        result = self.batch_runs.update_one(
            {"_id": item["_id"], "status": "running", "phase": "starting"},
            {"$set": data},
        )
        if not result.matched_count:
            raise GroupBatchBusy(group)

    def activate_store_batch_run(self, run_id: str, store_id: str, data: dict[str, Any]) -> None:
        """Entrega la reserva de una tienda al worker sin crear otra corrida."""
        from bson import ObjectId
        from retail.batch.group_scope import GroupBatchStopped
        from retail.batch.store_scope import StoreBatchBusy

        item = self.batch_runs.find_one({"_id": ObjectId(run_id)})
        if not item or item.get("tienda") != store_id or item.get("scope") != "tienda":
            raise StoreBatchBusy(store_id)
        if item.get("status") != "running":
            raise StoreBatchBusy(store_id)
        if item.get("stop_requested") or item.get("phase") == "stopping":
            raise GroupBatchStopped()
        if item.get("phase") != "starting":
            self.batch_runs.update_one({"_id": item["_id"], "status": "running"}, {"$set": data})
            return
        result = self.batch_runs.update_one(
            {
                "_id": item["_id"],
                "tienda": store_id,
                "scope": "tienda",
                "status": "running",
                "phase": "starting",
            },
            {"$set": data},
        )
        if not result.matched_count:
            raise StoreBatchBusy(store_id)

    def request_store_stop(self, store_id: str) -> bool:
        """Pide parar la corrida de una tienda. No toca las de grupos u otras tiendas."""
        key = (store_id or "").strip().lower()
        if not key:
            return False
        result = self.batch_runs.update_one(
            {
                "tienda": key,
                "scope": "tienda",
                "status": "running",
            },
            {"$set": {"stop_requested": True, "phase": "stopping"}},
        )
        return bool(result.matched_count)

    def request_basic_stop(self) -> bool:
        """Pide parar el scraping básico. No toca corridas de grupos ni tiendas."""
        result = self.batch_runs.update_one(
            {
                "job": "scraping_basico",
                "scope": "basico",
                "status": "running",
            },
            {"$set": {"stop_requested": True, "phase": "stopping"}},
        )
        return bool(result.matched_count)

    def request_group_stop(self, group: str) -> bool:
        """Pide parar la corrida de un grupo. No toca las de los demás."""
        result = self.batch_runs.update_one(
            {
                "grupo": group,
                "status": "running",
                "tienda": {"$in": [None, ""]},
                "scope": {"$nin": ["tienda", "basico"]},
            },
            {"$set": {"stop_requested": True, "phase": "stopping"}},
        )
        return bool(result.matched_count)

    def group_stop_requested(self, run_id: str) -> bool:
        from bson import ObjectId

        item = self.batch_runs.find_one(
            {"_id": ObjectId(run_id)},
            {"stop_requested": 1, "status": 1},
        )
        return bool(item and item.get("status") == "running" and item.get("stop_requested"))

    def set_group_batch_cursor(self, group: str, next_id: str | None) -> None:
        """Guarda desde qué producto retomar la próxima corrida del grupo."""
        from retail.batch.group_scope import batch_cursor_key

        key = batch_cursor_key(group)
        product = str(next_id or "").strip()
        if not product:
            self.app_settings.delete_one({"_id": key})
            return
        self.save_app_setting(
            key,
            {
                "next_id": product,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "budget_exhausted": False,
            },
        )

    def clear_group_batch_cursor(self, group: str) -> None:
        self.set_group_batch_cursor(group, None)

    def set_store_batch_cursor(self, store_id: str, next_id: str | None) -> None:
        """Guarda desde qué consulta retomar el scraping de una tienda."""
        from retail.batch.store_scope import store_cursor_key

        key = store_cursor_key(store_id)
        product = str(next_id or "").strip()
        if not product:
            self.app_settings.delete_one({"_id": key})
            return
        self.save_app_setting(
            key,
            {
                "next_id": product,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def clear_store_batch_cursor(self, store_id: str) -> None:
        self.set_store_batch_cursor(store_id, None)

    def latest_group_batch_run(self, group: str) -> dict[str, Any] | None:
        return self.batch_runs.find_one(
            {
                "grupo": group,
                "tienda": {"$in": [None, ""]},
                "scope": {"$nin": ["tienda", "basico"]},
            },
            sort=[("started_at", -1)],
        )

    def latest_store_batch_run(self, store_id: str) -> dict[str, Any] | None:
        key = (store_id or "").strip().lower()
        if not key:
            return None
        return self.batch_runs.find_one(
            {"tienda": key, "scope": "tienda"},
            sort=[("started_at", -1)],
        )

    def remember_group_batch_resume(self, group: str | None, run: dict[str, Any] | None) -> None:
        """Si la corrida quedó a medias, la próxima «Continuar» parte desde ahí."""
        from retail.batch.group_scope import resume_product_id

        if not group:
            return
        product = resume_product_id(run)
        if product:
            self.set_group_batch_cursor(group, product)

    def remember_store_batch_resume(self, store_id: str | None, run: dict[str, Any] | None) -> None:
        """Si el scraping de tienda quedó a medias, la próxima «Continuar» parte desde ahí."""
        from retail.batch.group_scope import resume_product_id

        if not store_id:
            return
        product = resume_product_id(run)
        if product:
            self.set_store_batch_cursor(store_id, product)

    def update_batch_run(self, run_id: str, **fields: Any) -> None:
        """Actualiza progreso en vivo (fase, consulta actual, error) sin tocar contadores."""
        from bson import ObjectId

        if not fields:
            return
        fields = {**fields, "activity_at": _now()}
        self.batch_runs.update_one({"_id": ObjectId(run_id)}, {"$set": fields})

    def append_batch_search(self, run_id: str, row: dict[str, Any]) -> None:
        from bson import ObjectId

        saved = row.get("saved") or {}
        update: dict[str, Any] = {
            "$push": {"searches": row},
            "$inc": {
                "processed": 1,
                "saved_upserted": int(saved.get("upserted") or 0),
                "saved_modified": int(saved.get("modified") or 0),
            },
        }
        update["$set"] = {"activity_at": _now()}
        if row.get("error"):
            update["$set"]["last_error"] = str(row["error"])
        self.batch_runs.update_one({"_id": ObjectId(run_id)}, update)

    def advance_batch_run(
        self,
        run_id: str,
        *,
        processed: int = 0,
        upserted: int = 0,
        modified: int = 0,
        skipped: int = 0,
        failed: int = 0,
        error: str | None = None,
    ) -> None:
        """Avanza contadores sin guardar cada búsqueda (el barrido básico es largo)."""
        from bson import ObjectId

        update: dict[str, Any] = {
            "$inc": {
                "processed": int(processed),
                "saved_upserted": int(upserted),
                "saved_modified": int(modified),
                "skipped": int(skipped),
                "failed": int(failed),
            }
        }
        update["$set"] = {"activity_at": _now()}
        if error:
            update["$set"]["last_error"] = str(error)[:500]
        self.batch_runs.update_one({"_id": ObjectId(run_id)}, update)

    def finish_batch_run(self, run_id: str, **fields: Any) -> None:
        from bson import ObjectId

        fields.setdefault("status", "done")
        if fields.get("status") == "error":
            fields["status"] = "failed"
        fields.setdefault("phase", "done" if fields.get("status") == "done" else "failed")
        fields["finished_at"] = _now()
        fields["current_query"] = None
        fields["current_id"] = None
        self.batch_runs.update_one({"_id": ObjectId(run_id)}, {"$set": fields})

    def fail_stale_batch_runs(self, *, hours: float = 3) -> int:
        """Cierra corridas sin progreso después de un reinicio o un despliegue.

        No usa la hora de inicio: una corrida de muchas horas que sigue
        avanzando no es un abandono.
        """
        from datetime import timedelta

        now = _now()
        cutoff = now - timedelta(hours=max(1.0, float(hours)))
        closed = 0
        for doc in self.batch_runs.find({"status": "running", "phase": {"$ne": "paused"}}):
            if not batch_run_is_stale(doc, cutoff=cutoff):
                continue
            group = str(doc.get("grupo") or "").strip()
            store = str(doc.get("tienda") or "").strip()
            if store and (doc.get("scope") == "tienda" or not group):
                self.remember_store_batch_resume(store, doc)
            elif group and not store:
                self.remember_group_batch_resume(group, doc)
            elif doc.get("job") == "scraping_basico":
                after = doc.get("resume_after_id")
                if after:
                    self.set_basic_scrape_cursor(after)
            result = self.batch_runs.update_one(
                {"_id": doc["_id"], "status": "running"},
                {
                    "$set": {
                        "status": "failed",
                        "phase": "failed",
                        "finished_at": now,
                        "last_error": "Corrida interrumpida o sin actividad; se cerró automáticamente.",
                        "current_query": None,
                        "current_id": None,
                    }
                },
            )
            closed += int(getattr(result, "modified_count", 0) or 0)
        return closed

    def find_by_query(self, query: str, limit: int = 200) -> list[dict[str, Any]]:
        """Candidatos para la búsqueda web sin COLLSCAN ni documentos enormes.

        Preferencia (índices): ``last_search_query`` exacto, ``$text`` sobre
        name/brand/sku_id, ids exactos. El regex multi-campo sin anclar queda
        solo como fallback si no hubo hits (misma semántica antigua).
        """
        text = query.strip()
        if not text:
            return []
        limit = max(1, min(int(limit), 500))
        seen: dict[tuple[str, str], dict[str, Any]] = {}

        def take(cursor) -> None:
            for item in cursor:
                key = (str(item.get("store") or ""), str(item.get("product_id") or ""))
                if not key[1] or key in seen:
                    continue
                item.pop("_id", None)
                item.pop("score", None)
                seen[key] = item
                if len(seen) >= limit:
                    return

        def run(filter_doc: dict[str, Any], *, sort=None, cap: int | None = None, projection=None) -> None:
            if len(seen) >= limit:
                return
            remaining = limit - len(seen)
            want = remaining if cap is None else min(remaining, cap)
            cursor = self.collection.find(filter_doc, projection if projection is not None else SEARCH_FIND_PROJECTION)
            if sort is not None:
                cursor = cursor.sort(sort)
            cursor = cursor.limit(want).max_time_ms(SEARCH_FIND_MAX_TIME_MS)
            take(cursor)

        # 1) Repeticiones del día / scrapes previos: índice last_search_query+updated_at.
        try:
            run({"last_search_query": text}, sort=[("updated_at", -1)])
        except Exception:
            pass

        # 2) Índice de texto (name/brand/sku_id) — evita el COLLSCAN del regex.
        if len(seen) < limit:
            try:
                run(
                    {"$text": {"$search": text}},
                    sort=[("score", {"$meta": "textScore"})],
                    projection={**SEARCH_FIND_PROJECTION, "score": {"$meta": "textScore"}},
                )
            except Exception:
                pass

        # 3) Código/sku exacto (consultas de una sola ficha).
        if " " not in text and len(text) >= 3 and len(seen) < limit:
            try:
                run(
                    {"$or": [{"product_id": text}, {"sku_id": text}]},
                    cap=SEARCH_FIND_ID_LIMIT,
                )
            except Exception:
                pass

        # 4) Fallback: misma $or regex de antes, solo si no hubo candidatos.
        if not seen:
            escaped = re.escape(text)
            try:
                run(
                    {
                        "$or": [
                            {"last_search_query": {"$regex": escaped, "$options": "i"}},
                            {"name": {"$regex": escaped, "$options": "i"}},
                            {"brand": {"$regex": escaped, "$options": "i"}},
                            {"sku_id": {"$regex": escaped, "$options": "i"}},
                            {"product_id": {"$regex": escaped, "$options": "i"}},
                        ]
                    },
                    sort=[("updated_at", -1)],
                )
            except Exception:
                return []

        rows = list(seen.values())
        rows.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
        return rows[:limit]

    @staticmethod
    def _store_product_filter(wanted: list[tuple[str, str]]) -> dict[str, Any]:
        """Filtro por (store, product_id) agrupando $in por tienda (usa store_product_id)."""
        by_store: dict[str, list[str]] = {}
        for store, product_id in wanted:
            by_store.setdefault(store, []).append(product_id)
        if len(by_store) == 1:
            store, product_ids = next(iter(by_store.items()))
            return {"store": store, "product_id": {"$in": product_ids}}
        return {
            "$or": [
                {"store": store, "product_id": {"$in": product_ids}}
                for store, product_ids in by_store.items()
            ]
        }

    def histories(self, keys: list[tuple[str, str]], limit: int = 80) -> dict[tuple[str, str], list[dict[str, Any]]]:
        wanted = [(store, product_id) for store, product_id in keys if store and product_id]
        if not wanted:
            return {}
        cursor = self.collection.find(
            self._store_product_filter(wanted),
            {"store": 1, "product_id": 1, "price_history": 1},
        )
        found: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in cursor:
            points = []
            for entry in (item.get("price_history") or [])[-limit:]:
                if not isinstance(entry, dict):
                    continue
                points.append(
                    {
                        "price": entry.get("price"),
                        "scraped_at": entry.get("scraped_at"),
                    }
                )
            found[(item.get("store") or "", item.get("product_id") or "")] = points
        return found

    def thumb_flags(self, keys: list[tuple[str, str]]) -> set[tuple[str, str]]:
        wanted = [(store, product_id) for store, product_id in keys if store and product_id]
        if not wanted:
            return set()
        cursor = self.collection.find(
            {
                **self._store_product_filter(wanted),
                "thumbnail.data": {"$exists": True},
            },
            {"store": 1, "product_id": 1},
        )
        return {(item.get("store") or "", item.get("product_id") or "") for item in cursor}

    def thumbnail(self, store: str, product_id: str) -> dict[str, Any] | None:
        item = self.collection.find_one(
            {"store": store, "product_id": product_id},
            {"thumbnail": 1},
        )
        return (item or {}).get("thumbnail")

    def product_images(self, store: str, product_id: str) -> dict[str, Any]:
        from retail.models import normalize_image_url

        item = self.collection.find_one(
            {"store": store, "product_id": product_id},
            {"_id": 0, "thumbnail": 1, "image_url": 1, "image_urls": 1},
        ) or {}
        sources: list[str] = []
        for value in [item.get("image_url"), *(item.get("image_urls") or [])]:
            text = normalize_image_url(store, str(value or "").strip()) or ""
            if text and text not in sources:
                sources.append(text)
        return {"thumbnail": item.get("thumbnail"), "sources": sources}

    def missing_thumbnails(self, wanted: list[tuple[tuple[str, str], str]]) -> list[tuple[tuple[str, str], str]]:
        """Filtra los que ya tienen miniatura de la misma imagen."""
        pairs = [(key, url) for key, url in wanted if key[0] and key[1] and url]
        if not pairs:
            return []
        cursor = self.collection.find(
            self._store_product_filter([key for key, _ in pairs]),
            {"store": 1, "product_id": 1, "thumbnail.source_url": 1},
        )
        current = {
            (item.get("store") or "", item.get("product_id") or ""): ((item.get("thumbnail") or {}).get("source_url"))
            for item in cursor
        }
        return [(key, url) for key, url in pairs if current.get(key) != url]

    def save_thumbnails(self, thumbnails: dict[tuple[str, str], dict[str, Any]]) -> int:
        if not thumbnails:
            return 0
        from pymongo import UpdateOne

        now = _now()
        operations = [
            UpdateOne(
                {"store": store, "product_id": product_id},
                {"$set": {"thumbnail": {**thumb, "updated_at": now}}, "$unset": {"thumbnail_attempted_at": ""}},
            )
            for (store, product_id), thumb in thumbnails.items()
        ]
        result = self.collection.bulk_write(operations, ordered=False)
        return result.modified_count

    def mark_thumbnail_attempted(self, keys: list[tuple[str, str]]) -> int:
        wanted = [(store, product_id) for store, product_id in keys if store and product_id]
        if not wanted:
            return 0
        result = self.collection.update_many(
            {"$or": [{"store": store, "product_id": product_id} for store, product_id in wanted]},
            {"$set": {"thumbnail_attempted_at": _now()}},
        )
        return result.modified_count

    def browse(
        self,
        *,
        text: str | None = None,
        category: str | None = None,
        store: str | None = None,
        brand: str | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        only_offers: bool = False,
        only_comparable: bool = False,
        sort: str = "updated",
        page: int = 1,
        size: int = 40,
    ) -> dict[str, Any]:
        """Catálogo navegable sobre los productos ya guardados."""
        match: dict[str, Any] = catalog_browse_filter(category)
        if text:
            match["name"] = {"$regex": re.escape(text.strip()), "$options": "i"}
        if store:
            match["store"] = store
        if brand:
            match["brand"] = {"$regex": f"^{re.escape(brand.strip())}$", "$options": "i"}
        if min_price or max_price:
            bounds: dict[str, Any] = {"$gt": 0}
            if min_price:
                bounds["$gte"] = int(min_price)
            if max_price:
                bounds["$lte"] = int(max_price)
            match["price"] = bounds
        if only_offers:
            match["$expr"] = {"$lt": ["$price", {"$ifNull": ["$price_normal", "$price"]}]}
        if only_comparable:
            match["specifications"] = {"$type": "object", "$ne": {}}

        order = {
            "price": [("price", 1)],
            "price_desc": [("price", -1)],
            "name": [("name", 1)],
        }.get(sort, [("updated_at", -1)])

        skip = max(0, (page - 1) * size)
        cursor = self.collection.find(
            match,
            {
                "store": 1,
                "product_id": 1,
                "sku_id": 1,
                "name": 1,
                "brand": 1,
                "seller": 1,
                "url": 1,
                "price": 1,
                "price_normal": 1,
                "price_internet": 1,
                "price_cmr": 1,
                "price_all_payment": 1,
                "price_card": 1,
                "payment_card_name": 1,
                "installment_count": 1,
                "installment_total": 1,
                "financial_cae": 1,
                "payment_conditions": 1,
                "condition": 1,
                "condition_confidence": 1,
                "shipping_cost": 1,
                "shipping_free_threshold": 1,
                "shipping_region": 1,
                "pickup_available": 1,
                "stock": 1,
                "availability": 1,
                "low_stock": 1,
                "only_extreme_sizes": 1,
                "variants": 1,
                "entity_id": 1,
                "entity_confidence": 1,
                "entity_override": 1,
                "entity_match_method": 1,
                "discount_percent": 1,
                "rating": 1,
                "reviews": 1,
                "catalog_category": 1,
                "compare_code": 1,
                "updated_at": 1,
                "image_url": 1,
                "image_urls": 1,
                "thumbnail.mime": 1,
                "specifications": 1,
            },
        )
        for field, direction in order:
            cursor = cursor.sort(field, direction)
        rows = []
        for item in cursor.skip(skip).limit(size):
            item.pop("_id", None)
            specs = item.pop("specifications", None) or {}
            item["comparison_fields"] = sum(1 for value in specs.values() if value not in (None, "", [], {})) if isinstance(specs, dict) else 0
            item["has_thumb"] = bool(
                item.pop("thumbnail", None) or item.pop("image_url", None) or item.pop("image_urls", None)
            )
            updated = item.get("updated_at")
            item["updated_at"] = updated.isoformat() if hasattr(updated, "isoformat") else updated
            rows.append(item)
        return {
            "total": self.collection.count_documents(match),
            "page": page,
            "size": size,
            "items": rows,
        }

    def _legacy_real_offers(
        self,
        *,
        comparacion: bool = True,
        historial: bool = True,
        iguales: bool = False,
        text: str | None = None,
        store: str | None = None,
        category: str | None = None,
        min_gap: float = 0,
        min_super: float = 0,
        page: int = 1,
        size: int = 40,
    ) -> dict[str, Any]:
        """Productos con descuento real frente a otra tienda y/o a su propio pasado."""
        from retail.compare import cluster_offer_rows
        from retail.predictive_alerts import predictive_validation_status
        from retail.reales import MIN_ENTITY_CONFIDENCE, is_agotado, is_super_offer, pick_real_offer

        timesfm_status = predictive_validation_status(self)
        empty = {
            "total": 0, "page": page, "size": size, "items": [], "stores": [], "categories": [],
            "timesfm_signal_status": timesfm_status,
        }
        if not comparacion and not historial and not iguales:
            return empty

        projection: dict[str, Any] = {
            "store": 1,
            "product_id": 1,
            "name": 1,
            "brand": 1,
            "url": 1,
            "seller": 1,
            "price": 1,
            "price_normal": 1,
            "price_internet": 1,
            "price_all_payment": 1,
            "price_card": 1,
            "payment_card_name": 1,
            "installment_count": 1,
            "installment_total": 1,
            "financial_cae": 1,
            "payment_conditions": 1,
            "condition": 1,
            "condition_confidence": 1,
            "shipping_cost": 1,
            "shipping_free_threshold": 1,
            "shipping_region": 1,
            "pickup_available": 1,
            "stock": 1,
            "stock_verified": 1,
            "low_stock": 1,
            "only_extreme_sizes": 1,
            "variants": 1,
            "entity_id": 1,
            "entity_confidence": 1,
            "entity_override": 1,
            "entity_match_method": 1,
            "discount_percent": 1,
            "compare_code": 1,
            "catalog_category": 1,
            "availability": 1,
            "status": 1,
            "stock_status": 1,
            "updated_at": 1,
            "has_thumb": {
                "$or": [
                    {"$gt": [{"$strLenCP": {"$ifNull": ["$thumbnail.mime", ""]}}, 0]},
                    {"$gt": [{"$strLenCP": {"$ifNull": ["$image_url", ""]}}, 0]},
                ]
            },
        }
        # Se muestra la baja verificada por historial junto al descuento publicado,
        # aunque el usuario esté consultando principalmente la comparación entre tiendas.
        projection["price_history"] = {"$slice": ["$price_history", -40]}

        # No agrupar por compare_code/SKU: cada tienda usa códigos propios.
        # Se cargan avisos con precio y se agrupan por nombre/identidad.
        pipeline = [
            {"$match": {"price": {"$gt": 0}, "name": {"$nin": [None, ""]}}},
            {"$project": projection},
        ]
        docs = list(self.collection.aggregate(pipeline, allowDiskUse=True))
        found: list[dict[str, Any]] = []
        needle = (text or "").strip().lower()
        wanted_store = (store or "").strip().lower()
        wanted_category = (category or "").strip().lower()
        for group in cluster_offer_rows(docs):
            if int(group.get("store_count") or 0) < 2:
                continue
            if float(group.get("entity_confidence") or 0) < MIN_ENTITY_CONFIDENCE:
                continue
            card = pick_real_offer(
                group.get("offers") or [],
                comparacion=comparacion,
                historial=historial,
                iguales=iguales,
            )
            if not card or is_agotado(card):
                continue
            if needle:
                blob = " ".join(
                    str(card.get(key) or "")
                    for key in ("name", "brand", "store", "compare_code", "category")
                ).lower()
                if needle not in blob:
                    continue
            found.append(card)
        store_options = sorted({item.get("store") for item in found if item.get("store")})
        raw_categories = {
            str(item.get("category") or "").strip()
            for item in found
            if str(item.get("category") or "").strip()
        }
        raw_keys = {label.casefold() for label in raw_categories}

        def category_key(label: str) -> str:
            key = label.casefold()
            # Une pares evidentes singular/plural únicamente cuando ambas
            # variantes existen (Deporte/deportes, Consola/consolas).
            return key[:-1] if key.endswith("s") and key[:-1] in raw_keys else key

        category_by_key: dict[str, str] = {}
        for item in found:
            label = str(item.get("category") or "").strip()
            if not label:
                continue
            key = category_key(label)
            previous = category_by_key.get(key)
            # Prefiere la variante bien presentada (Automotriz) frente a la
            # misma categoría enteramente en minúsculas.
            if previous is None or (previous.islower() and not label.islower()):
                category_by_key[key] = label
        category_options = sorted(category_by_key.values(), key=str.casefold)
        if wanted_store:
            found = [item for item in found if (item.get("store") or "").lower() == wanted_store]
        if wanted_category:
            wanted_key = category_key(wanted_category)
            found = [
                item for item in found
                if category_key(str(item.get("category") or "").strip()) == wanted_key
            ]
        floor = float(min_gap or 0)
        if floor > 0:
            found = [item for item in found if (item.get("gap_percent") or 0) >= floor]
        super_floor = float(min_super or 0)
        if super_floor > 0:
            found = [item for item in found if is_super_offer(item, super_floor)]
        found.sort(key=lambda row: (-(row.get("gap_percent") or 0), -(row.get("gap") or 0), row.get("name") or ""))
        skip = max(0, (page - 1) * size)
        page_items = found[skip : skip + size]
        signals = 0
        if timesfm_status["enabled"] and page_items:
            from retail.offer_forecast_signal import attach_offer_forecast_signals

            keys = [
                f"{str(item.get('store') or '').strip().lower()}:{str(item.get('product_id') or '').strip()}"
                for item in page_items
                if item.get("store") and item.get("product_id")
            ]
            forecasts = list(
                self.forecasts.find(
                    {"forecast_key": {"$in": keys}, "model": "timesfm"},
                    {
                        "_id": 0, "forecast_key": 1, "model": 1, "horizon": 1,
                        "point_forecast": 1, "quantiles": 1, "metadata": 1, "generated_at": 1,
                    },
                ).sort("generated_at", -1)
            )
            signals = attach_offer_forecast_signals(page_items, forecasts)
        return {
            "total": len(found),
            "page": page,
            "size": size,
            "stores": store_options,
            "categories": category_options,
            "items": page_items,
            "timesfm_signal_status": {**timesfm_status, "visible_signals": signals},
        }

    def real_offers(
        self,
        *,
        comparacion: bool = True,
        historial: bool = True,
        iguales: bool = False,
        text: str | None = None,
        store: str | None = None,
        category: str | None = None,
        min_gap: float = 0,
        min_super: float = 0,
        page: int = 1,
        size: int = 40,
    ) -> dict[str, Any]:
        """Lee exclusivamente marcas reales del día Chile; no clasifica en request."""
        from retail.offer_forecast_signal import attach_offer_forecast_signals
        from retail.predictive_alerts import predictive_validation_status
        from retail.real_offer_worker import chile_day
        from retail.reales import is_super_offer

        timesfm_status = predictive_validation_status(self)
        selected_kinds = {
            kind for kind, enabled in (
                ("comparacion", comparacion),
                ("historial", historial),
                ("iguales", iguales),
            )
            if enabled
        }
        if not selected_kinds:
            return {
                "total": 0, "page": page, "size": size, "items": [],
                "stores": [], "categories": [], "day": chile_day(),
                "timesfm_signal_status": timesfm_status,
            }

        today = chile_day()
        rows = list(self.daily_real_offers.aggregate([
            {"$match": {"day": today, "is_real": True}},
            {
                "$lookup": {
                    "from": self.collection.name,
                    "localField": "product_id",
                    "foreignField": "_id",
                    "as": "product",
                }
            },
            {"$set": {"product": {"$first": "$product"}}},
            {
                "$match": {
                    "product": {"$ne": None},
                    "$expr": {"$eq": ["$evaluated_price", "$product.price"]},
                }
            },
            {
                "$project": {
                    "_id": 0, "analysis": 1, "evaluated_at": 1,
                    "evaluated_price": 1, "criterion_version": 1,
                    "product.store": 1, "product.product_id": 1,
                    "product.name": 1, "product.brand": 1,
                    "product.catalog_category": 1, "product.category": 1,
                    "product.url": 1, "product.updated_at": 1,
                    "product.image_url": 1, "product.thumbnail.mime": 1,
                }
            },
        ]))
        found: list[dict[str, Any]] = []
        needle = str(text or "").strip().casefold()
        wanted_store = str(store or "").strip().casefold()
        wanted_category = str(category or "").strip().casefold()
        all_stores: set[str] = set()
        all_categories: set[str] = set()
        for row in rows:
            product = row.get("product") or {}
            card = {
                **(row.get("analysis") or {}),
                "store": product.get("store"),
                "product_id": product.get("product_id"),
                "name": product.get("name"),
                "brand": product.get("brand"),
                "category": product.get("catalog_category") or product.get("category"),
                "url": product.get("url"),
                "updated_at": _json_time(product.get("updated_at")),
                "evaluated_at": _json_time(row.get("evaluated_at")),
                "evaluated_price": row.get("evaluated_price"),
                "criterion_version": row.get("criterion_version"),
                "has_thumb": bool(product.get("image_url") or product.get("thumbnail")),
            }
            kinds = set(card.get("kinds") or [])
            if not kinds.intersection(selected_kinds):
                continue
            if card.get("store"):
                all_stores.add(str(card["store"]))
            if card.get("category"):
                all_categories.add(str(card["category"]))
            if needle:
                blob = " ".join(
                    str(card.get(key) or "")
                    for key in ("name", "brand", "store", "compare_code", "category")
                ).casefold()
                if needle not in blob:
                    continue
            if wanted_store and str(card.get("store") or "").casefold() != wanted_store:
                continue
            if wanted_category and str(card.get("category") or "").casefold() != wanted_category:
                continue
            if float(min_gap or 0) > float(card.get("gap_percent") or 0):
                continue
            if float(min_super or 0) > 0 and not is_super_offer(card, float(min_super)):
                continue
            found.append(card)

        found.sort(key=lambda item: (
            -float(item.get("gap_percent") or 0),
            -float(item.get("offer_score") or 0),
            str(item.get("name") or ""),
        ))
        skip = max(0, (page - 1) * size)
        page_items = found[skip : skip + size]
        signals = 0
        if timesfm_status["enabled"] and page_items:
            keys = [
                f"{str(item.get('store') or '').strip().lower()}:{str(item.get('product_id') or '').strip()}"
                for item in page_items
            ]
            forecasts = list(self.forecasts.find(
                {"forecast_key": {"$in": keys}, "model": "timesfm"},
                {"_id": 0, "forecast_key": 1, "model": 1, "horizon": 1,
                 "point_forecast": 1, "quantiles": 1, "metadata": 1, "generated_at": 1},
            ).sort("generated_at", -1))
            signals = attach_offer_forecast_signals(page_items, forecasts)
        return {
            "total": len(found), "page": page, "size": size, "day": today,
            "stores": sorted(all_stores), "categories": sorted(all_categories, key=str.casefold),
            "items": page_items,
            "timesfm_signal_status": {**timesfm_status, "visible_signals": signals},
        }

    def save_categories(self, store: str, categories: list[dict[str, Any]]) -> dict[str, int]:
        """Guarda el árbol de categorías de una tienda. Idempotente por (store, id)."""
        from pymongo import UpdateOne

        operations = []
        for item in categories:
            if not item.get("id"):
                continue
            payload = {key: value for key, value in item.items() if key != "_id"}
            payload["store"] = store
            payload["updated_at"] = _now()
            operations.append(UpdateOne({"store": store, "id": item["id"]}, {"$set": payload}, upsert=True))
        if not operations:
            return {"upserted": 0, "modified": 0}
        result = self.categories.bulk_write(operations, ordered=False)
        return {"upserted": len(result.upserted_ids), "modified": result.modified_count}

    def list_categories(
        self,
        store: str = "falabella",
        *,
        text: str | None = None,
        parent_id: str | None = None,
        depth: int | None = None,
        roots: bool = False,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        match: dict[str, Any] = {"store": store}
        if text:
            match["$or"] = [
                {"name": {"$regex": re.escape(text.strip()), "$options": "i"}},
                {"path": {"$regex": re.escape(text.strip()), "$options": "i"}},
            ]
        if parent_id:
            match["parent_id"] = parent_id
        if roots:
            match["parent_id"] = None
        if depth is not None:
            match["depth"] = depth
        from pymongo import ASCENDING

        cursor = self.categories.find(match, {"_id": 0, "store": 0, "updated_at": 0})
        return list(cursor.sort("name", ASCENDING).limit(limit))

    def count_categories(self, store: str = "falabella") -> int:
        return self.categories.count_documents({"store": store})

    def browse_facets(
        self,
        limit: int = 30,
        *,
        category: str | None = None,
        store: str | None = None,
        include_counts: bool = False,
        fields: tuple[str, ...] | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """Facetas del catálogo.

        Por defecto no calcula conteos ($group + $sum sobre products): eso es lo
        que hace lento «Explora rápido». Con ``include_counts=True`` (admin)
        se conserva el comportamiento anterior.
        """
        wanted = fields or ("categories", "stores", "brands")
        category_filter = catalog_browse_filter(category)
        store_filter = dict(category_filter)
        if store:
            store_filter["store"] = store

        def top(
            field: str,
            fold_case: bool = False,
            base_match: dict[str, Any] | None = None,
        ) -> list[dict[str, Any]]:
            key = {"$toLower": f"${field}"} if fold_case else f"${field}"
            match = dict(base_match or {})
            match.update({field: {"$nin": [None, ""]}, "price": {"$gt": 0}})
            if include_counts:
                pipeline = [
                    {"$match": match},
                    {"$group": {"_id": key, "count": {"$sum": 1}, "label": {"$first": f"${field}"}}},
                    {"$sort": {"count": -1}},
                    {"$limit": limit * 3 if field == "catalog_category" else limit},
                ]
            else:
                # Sin $sum: solo etiquetas para navegar (mucho más barato + cacheable).
                pipeline = [
                    {"$match": match},
                    {"$group": {"_id": key, "label": {"$first": f"${field}"}}},
                    {"$sort": {"label": 1}},
                    {"$limit": limit * 3 if field == "catalog_category" else limit},
                ]
            rows = []
            for row in self.collection.aggregate(pipeline):
                item = {"value": row.get("label") or row["_id"]}
                if include_counts:
                    item["count"] = int(row.get("count") or 0)
                rows.append(item)
            if field != "catalog_category":
                return rows
            from retail.relevance import fold

            merged: dict[str, dict[str, Any]] = {}
            for row in rows:
                normalized = fold(str(row["value"]))
                current = merged.get(normalized)
                if current is None:
                    merged[normalized] = dict(row)
                    continue
                if include_counts:
                    current["count"] = int(current.get("count") or 0) + int(row.get("count") or 0)
                candidate = str(row["value"])
                visible = str(current["value"])
                if (candidate[:1].isupper(), any(ord(char) > 127 for char in candidate)) > (
                    visible[:1].isupper(), any(ord(char) > 127 for char in visible)
                ):
                    current["value"] = candidate
            if include_counts:
                return sorted(merged.values(), key=lambda row: (-int(row.get("count") or 0), str(row["value"])))[:limit]
            return sorted(merged.values(), key=lambda row: str(row["value"]).casefold())[:limit]

        result: dict[str, list[dict[str, Any]]] = {}
        if "categories" in wanted:
            result["categories"] = top("catalog_category", fold_case=True)
        if "stores" in wanted:
            result["stores"] = top("store", base_match=category_filter if category else None)
        if "brands" in wanted:
            result["brands"] = top(
                "brand",
                fold_case=True,
                base_match=store_filter if store else category_filter if category else None,
            )
        return result

    def explore_categories(
        self,
        limit: int = 40,
        *,
        include_counts: bool = False,
        sample_size: int = 8000,
    ) -> list[dict[str, Any]]:
        """Lista para «Explora rápido».

        Rankea por popularidad aproximada con ``$sample`` + ``$sum`` sobre la
        muestra (rápido), no el ``$group+$sum`` completo del catálogo (~4s).

        Por defecto omite ``count``; con ``include_counts=True`` (admin) lo
        incluye. Siempre entrega ``icon`` con el mismo mapeo que la UI.
        """
        from retail.relevance import category_icon_kind, fold

        field = "catalog_category"
        match = {field: {"$nin": [None, ""]}, "price": {"$gt": 0}}
        size = max(200, int(sample_size))
        # $sample primero = cursor pseudoaleatorio (barato); luego filtramos.
        pipeline = [
            {"$sample": {"size": size}},
            {"$match": match},
            {
                "$group": {
                    "_id": {"$toLower": f"${field}"},
                    "count": {"$sum": 1},
                    "label": {"$first": f"${field}"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": max(limit * 4, limit)},
        ]
        merged: dict[str, dict[str, Any]] = {}
        for row in self.collection.aggregate(pipeline):
            label = str(row.get("label") or row.get("_id") or "").strip()
            if not label:
                continue
            normalized = fold(label)
            current = merged.get(normalized)
            sample_count = int(row.get("count") or 0)
            if current is None:
                merged[normalized] = {"value": label, "count": sample_count}
                continue
            current["count"] = int(current.get("count") or 0) + sample_count
            candidate = label
            visible = str(current["value"])
            if (candidate[:1].isupper(), any(ord(char) > 127 for char in candidate)) > (
                visible[:1].isupper(),
                any(ord(char) > 127 for char in visible),
            ):
                current["value"] = candidate

        ranked = sorted(
            merged.values(),
            key=lambda row: (-int(row.get("count") or 0), str(row["value"]).casefold()),
        )[:limit]
        rows: list[dict[str, Any]] = []
        for item in ranked:
            value = item["value"]
            entry: dict[str, Any] = {
                "value": value,
                "label": value,
                "icon": category_icon_kind(value),
            }
            if include_counts:
                entry["count"] = int(item.get("count") or 0)
            rows.append(entry)
        return rows

    def backfill_categories(self, mapping: dict[str, str]) -> int:
        """Copia la categoría del catálogo a productos guardados antes de tenerla."""
        touched = 0
        for catalog_id, category in mapping.items():
            if not category:
                continue
            result = self.collection.update_many(
                {"catalog_id": catalog_id, "catalog_category": {"$in": [None, ""]}},
                {"$set": {"catalog_category": category}},
            )
            touched += result.modified_count
        return touched

    def recent_searches(self, limit: int = 12) -> list[dict[str, Any]]:
        rows = []
        for item in self.searches.find().sort("created_at", -1).limit(limit):
            rows.append(
                {
                    "id": str(item["_id"]),
                    "query": item.get("query"),
                    "source": item.get("source"),
                    "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
                    "offer_count": item.get("offer_count"),
                    "comparable_count": item.get("comparable_count"),
                }
            )
        return rows

    def count(self, **filters: Any) -> int:
        return self.collection.count_documents(filters)

    def recent_alerts(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = []
        for item in self.alerts.find().sort("created_at", -1).limit(limit):
            created = item.get("created_at")
            rows.append(
                {
                    "id": str(item["_id"]),
                    "day": item.get("day"),
                    "catalog_id": item.get("catalog_id"),
                    "query": item.get("query"),
                    "rule": item.get("rule"),
                    "name": item.get("name"),
                    "store": item.get("store"),
                    "price": item.get("price"),
                    "saving": item.get("saving") or 0,
                    "category": item.get("category"),
                    "compare_code": item.get("compare_code"),
                    "message": item.get("message"),
                    "url": item.get("url"),
                    "store_title": (item.get("extra") or {}).get("store_title"),
                    "display_store": (item.get("extra") or {}).get("display_store"),
                    "seller": (item.get("extra") or {}).get("seller"),
                    "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                }
            )
        return rows

    def alert_exists(self, alert: Any) -> bool:
        """True si esa oferta ya se guardó antes (hoy o un día anterior)."""
        identity = self._alert_identity_query(alert)
        if not identity:
            return False
        return self.alerts.count_documents(identity, limit=1) > 0

    @staticmethod
    def _alert_identity_query(alert: Any) -> dict[str, Any]:
        compare_code = getattr(alert, "compare_code", None)
        extra = getattr(alert, "extra", None) or {}
        product_id = extra.get("product_id")
        if compare_code:
            return {"compare_code": compare_code}
        if product_id:
            return {"store": getattr(alert, "store", None), "extra.product_id": product_id}
        name = getattr(alert, "name", None)
        if not name:
            return {}
        return {"store": getattr(alert, "store", None), "name": name}

    @staticmethod
    def _deal_identity_key(item: dict[str, Any]) -> str:
        code = str(item.get("compare_code") or "").strip()
        if code:
            return f"c:{code}"
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        product_id = str(extra.get("product_id") or item.get("product_id") or "").strip()
        store = str(item.get("store") or "").strip().lower()
        if store and product_id:
            return f"p:{store}|{product_id}"
        name = str(item.get("name") or "").strip().casefold()
        return f"n:{store}|{name}"

    def _deal_keys_seen_before(self, day: str, items: list[dict[str, Any]]) -> set[str]:
        """Identidades que ya tuvieron oferta en un día anterior a `day`."""
        codes: list[str] = []
        pairs: list[tuple[str, str]] = []
        names: list[tuple[str, str]] = []
        for item in items:
            code = str(item.get("compare_code") or "").strip()
            if code:
                codes.append(code)
                continue
            extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
            product_id = str(extra.get("product_id") or item.get("product_id") or "").strip()
            store = str(item.get("store") or "").strip()
            if store and product_id:
                pairs.append((store, product_id))
                continue
            name = str(item.get("name") or "").strip()
            if store or name:
                names.append((store, name))

        prior: set[str] = set()
        if codes:
            for doc in self.alerts.find(
                {"day": {"$lt": day}, "compare_code": {"$in": codes}},
                {"compare_code": 1},
            ):
                found = str(doc.get("compare_code") or "").strip()
                if found:
                    prior.add(f"c:{found}")
        for index in range(0, len(pairs), 150):
            chunk = pairs[index : index + 150]
            query = {
                "day": {"$lt": day},
                "$or": [{"store": store, "extra.product_id": product_id} for store, product_id in chunk],
            }
            for doc in self.alerts.find(query, {"store": 1, "extra.product_id": 1}):
                store = str(doc.get("store") or "").strip().lower()
                product_id = str((doc.get("extra") or {}).get("product_id") or "").strip()
                if store and product_id:
                    prior.add(f"p:{store}|{product_id}")
        for index in range(0, len(names), 150):
            chunk = names[index : index + 150]
            query = {
                "day": {"$lt": day},
                "$or": [{"store": store, "name": name} for store, name in chunk],
            }
            for doc in self.alerts.find(query, {"store": 1, "name": 1}):
                store = str(doc.get("store") or "").strip().lower()
                name = str(doc.get("name") or "").strip().casefold()
                prior.add(f"n:{store}|{name}")
        return prior

    @staticmethod
    def public_run_alert(item: dict[str, Any]) -> dict[str, Any]:
        """Fila pública de una oferta contada en `batch_runs.alert_count`.

        El contador no guarda canal (correo, Telegram, oferta real). Solo se
        copia `channel` si ya venía en el documento. No se inventa.
        """
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        raw_channel = item.get("channel") or item.get("via") or extra.get("channel") or extra.get("via")
        channel = str(raw_channel).strip() if isinstance(raw_channel, str) and str(raw_channel).strip() else None
        previous = item.get("previous_price")
        if previous in (None, "") and extra.get("previous_price") not in (None, ""):
            previous = extra.get("previous_price")
        created = item.get("created_at")
        return {
            "id": str(item.get("_id") or item.get("id") or ""),
            "name": item.get("name") or item.get("query") or "",
            "store": item.get("store") or "",
            "store_title": extra.get("store_title") or "",
            "display_store": extra.get("display_store") or "",
            "seller": extra.get("seller") or "",
            "price": item.get("price"),
            "previous_price": previous,
            "median": extra.get("median"),
            "second_store": extra.get("second_store") or None,
            "second_price": extra.get("second_price"),
            "rule": item.get("rule") or "",
            "rule_label": _alert_rule_label(item.get("rule")),
            "channel": channel,
            "saving": int(item.get("saving") or 0),
            "message": item.get("message") or "",
            "url": item.get("url") or "",
            "product_id": extra.get("product_id") or item.get("product_id") or "",
            "category": item.get("category") or "",
            "query": item.get("query") or "",
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        }

    def alerts_for_batch_run(self, run_id: str, *, limit: int = 2000) -> dict[str, Any] | None:
        """Ofertas guardadas con `run` = id de la corrida. Es lo que cuenta `alert_count`."""
        from bson import ObjectId
        from bson.errors import InvalidId

        key = str(run_id or "").strip()
        if not key:
            return None
        try:
            oid = ObjectId(key)
        except (InvalidId, TypeError):
            return None
        run = self.batch_runs.find_one({"_id": oid})
        if not run:
            return None
        # `alert_count` es len(detect_offers). Los seguidos (`watch_*`) se guardan
        # con el mismo id de corrida pero no entran en ese número.
        query = {"run": str(run["_id"]), "rule": {"$not": {"$regex": r"^watch_"}}}
        total = int(self.alerts.count_documents(query))
        cap = max(1, min(int(limit), 2000))
        rows = [
            self.public_run_alert(item)
            for item in self.alerts.find(query).sort([("saving", -1), ("name", 1)]).limit(cap)
        ]
        return {
            "run_id": str(run["_id"]),
            "grupo": run.get("grupo") or None,
            "tienda": run.get("tienda") or None,
            "started_at": _json_time(run.get("started_at")),
            "alert_count": int(run.get("alert_count") or 0),
            "total": total,
            "truncated": total > len(rows),
            "items": rows,
        }

    def save_alerts(self, alerts: list[Any], run: str | None = None) -> int:
        if not alerts:
            return 0
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        now = _now()
        documents = []
        for alert in alerts:
            documents.append(
                {
                    "day": day,
                    "run": run,
                    "created_at": now,
                    "catalog_id": getattr(alert, "catalog_id", None),
                    "query": getattr(alert, "query", None),
                    "rule": getattr(alert, "rule", None),
                    "name": getattr(alert, "name", None),
                    "store": getattr(alert, "store", None),
                    "price": getattr(alert, "price", None),
                    "previous_price": getattr(alert, "previous_price", None),
                    "message": getattr(alert, "message", None),
                    "url": getattr(alert, "url", None),
                    "compare_code": getattr(alert, "compare_code", None),
                    "saving": int(getattr(alert, "saving", 0) or 0),
                    "reference_price": getattr(alert, "reference_price", None),
                    "analysis_reference_price": getattr(alert, "analysis_reference_price", None),
                    "discount": float(getattr(alert, "discount", 0) or 0),
                    "category": getattr(alert, "category", None),
                    "extra": getattr(alert, "extra", None),
                }
            )
        self.alerts.insert_many(documents)
        return len(documents)

    @staticmethod
    def _deal_reference(item: dict[str, Any]) -> tuple[int | None, int | None]:
        extra = item.get("extra") or {}
        rule = str(item.get("rule") or "")
        current = item.get("price")
        reference = item.get("reference_price")
        if "below_median" in rule:
            reference = item.get("price_normal") or reference
        elif "cross_store_gap" in rule:
            reference = extra.get("second_total") or extra.get("second_price") or reference
            current = extra.get("comparison_price") or current
            if extra.get("comparison_basis") == "landed_price" and not extra.get("comparison_price"):
                current = int(current or 0) + int(extra.get("shipping_cost") or 0)
        elif "price_drop" in rule:
            reference = item.get("previous_price") or extra.get("previous_price") or reference
        elif "common_discount" in rule:
            reference = item.get("price_normal") or extra.get("previous_price") or reference
        try:
            return int(reference) if reference is not None else None, int(current) if current is not None else None
        except (TypeError, ValueError):
            return None, None

    @classmethod
    def _deal_saving(cls, item: dict[str, Any]) -> int:
        reference, current = cls._deal_reference(item)
        if reference and reference > 0 and current and current > 0:
            return max(reference - current, 0)
        if "below_median" in str(item.get("rule") or ""):
            return 0
        if "reference_price" in item:
            return 0
        return max(0, int(item.get("saving") or 0))

    @classmethod
    def _deal_discount(cls, item: dict[str, Any]) -> float:
        extra = item.get("extra") or {}
        rule = str(item.get("rule") or "")
        if extra.get("gap_percent") is not None:
            percent = float(extra["gap_percent"])
            return round(percent, 1) if percent > 0 else 0.0
        reference, current = cls._deal_reference(item)
        if reference and reference > 0 and current and 0 < current < reference:
            saving = reference - current
            return round(100 * saving / reference, 1)
        if "below_median" in rule:
            return 0.0
        if reference is not None or "reference_price" in item:
            return 0.0
        saving = max(0, int(item.get("saving") or 0))
        price = int(item.get("price") or 0)
        fallback_reference = price + saving
        if price > 0 and saving > 0 and fallback_reference > 0:
            return round(100 * saving / fallback_reference, 1)
        return 0.0

    @staticmethod
    def _sort_deals(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
        key = {
            "saving": lambda row: (-(row.get("saving") or 0), -(row.get("discount") or 0)),
            "price": lambda row: (row.get("price") is None, row.get("price") or 0),
            "price_desc": lambda row: (-(row.get("price") or 0),),
            "name": lambda row: ((row.get("name") or "").lower(),),
            "gap": lambda row: (-(row.get("gap_percent") or 0), -(row.get("saving") or 0)),
        }.get(sort, lambda row: (-(row.get("discount") or 0), -(row.get("saving") or 0)))
        rows.sort(key=key)
        return rows

    def deals(
        self,
        *,
        day: str | None = None,
        category: str | None = None,
        store: str | None = None,
        text: str | None = None,
        rule: str | None = None,
        min_saving: int = 0,
        min_discount: float = 0,
        min_price: int | None = None,
        max_price: int | None = None,
        sort: str = "discount",
        page: int = 1,
        size: int = 80,
    ) -> dict[str, Any]:
        """Alertas nuevas de un día: sin repetir producto ni traer las de días previos."""
        chosen = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        query: dict[str, Any] = {"day": chosen}
        if category:
            query["category"] = category
        if store:
            query["store"] = store
        if rule:
            query["rule"] = {"$regex": re.escape(rule.strip())}
        if min_saving:
            query["saving"] = {"$gte": int(min_saving)}
        if min_price or max_price:
            bounds: dict[str, Any] = {}
            if min_price:
                bounds["$gte"] = int(min_price)
            if max_price:
                bounds["$lte"] = int(max_price)
            query["price"] = bounds
        needle = (text or "").strip()
        if needle:
            query["name"] = {"$regex": re.escape(needle), "$options": "i"}
        raw = list(self.alerts.find(query).limit(4000))
        prior = self._deal_keys_seen_before(chosen, raw) if raw else set()
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            key = self._deal_identity_key(item)
            if key in seen or key in prior:
                continue
            seen.add(key)
            extra = item.get("extra") or {}
            gap = extra.get("gap_percent")
            reference, _comparison_price = self._deal_reference(item)
            row = {
                "id": str(item["_id"]),
                "day": item.get("day"),
                "catalog_id": item.get("catalog_id"),
                "query": item.get("query"),
                "category": item.get("category"),
                "rule": item.get("rule"),
                "name": item.get("name"),
                "store": item.get("store"),
                "price": item.get("price"),
                "previous_price": item.get("previous_price") or extra.get("previous_price"),
                "reference_price": reference,
                "analysis_reference_price": item.get("analysis_reference_price") or (
                    extra.get("median") if "below_median" in str(item.get("rule") or "") else None
                ),
                "analysis_discount_pct": (
                    round(abs(float(extra["percent_vs_median"])), 1)
                    if "below_median" in str(item.get("rule") or "")
                    and extra.get("percent_vs_median") is not None
                    and float(extra["percent_vs_median"]) < 0
                    else 0
                ),
                "saving": self._deal_saving(item),
                "discount": self._deal_discount(item),
                "gap_percent": round(float(gap), 1) if gap else 0,
                "message": item.get("message"),
                "url": item.get("url"),
                "compare_code": item.get("compare_code"),
                "product_id": extra.get("product_id"),
                "level": extra.get("level"),
                "store_title": extra.get("store_title"),
                "display_store": extra.get("display_store"),
                "seller": extra.get("seller"),
                "created_at": _json_time(item.get("created_at")),
                "updated_at": _json_time(item.get("created_at")),
            }
            if min_discount and (row.get("discount") or 0) < float(min_discount):
                continue
            rows.append(row)
        self._sort_deals(rows, sort)
        page = max(1, int(page))
        size = max(1, min(int(size), 240))
        start = (page - 1) * size
        return {
            "total": len(rows),
            "page": page,
            "size": size,
            "total_saving": sum(item.get("saving") or 0 for item in rows),
            "items": rows[start : start + size],
        }

    def deal_days(self, limit: int = 14) -> list[str]:
        return sorted(self.alerts.distinct("day"), reverse=True)[:limit]

    def deal_facets(self, day: str) -> dict[str, list[str]]:
        rules: set[str] = set()
        for item in self.alerts.distinct("rule", {"day": day}):
            if item:
                rules.update(part for part in str(item).split("+") if part)
        return {
            "categories": sorted(item for item in self.alerts.distinct("category", {"day": day}) if item),
            "stores": sorted(item for item in self.alerts.distinct("store", {"day": day}) if item),
            "rules": sorted(rules),
        }

    def iter_stored_products(self, *, page_size: int = 200, after_id: Any = None):
        """Productos ya guardados, sin historial ni miniaturas (el barrido básico).

        Cada página se lee y el cursor se cierra antes de entregarla. El barrido
        espera segundos por producto; un cursor abierto más de unos minutos
        expira y Mongo responde CursorNotFound.

        `after_id` retoma después de ese `_id` (continuar una corrida fallida).
        """
        size = max(1, int(page_size))
        projection = {
            "store": 1,
            "product_id": 1,
            "sku_id": 1,
            "name": 1,
            "brand": 1,
            "url": 1,
            "last_search_query": 1,
            "catalog_query": 1,
            "query": 1,
            "catalog_category": 1,
            "category": 1,
            "batch_grupo": 1,
            "catalog_group": 1,
            "group": 1,
            "grupo": 1,
            "groups": 1,
        }
        last_id = None
        if after_id is not None and str(after_id).strip():
            try:
                from bson import ObjectId

                last_id = after_id if isinstance(after_id, ObjectId) else ObjectId(str(after_id))
            except Exception:
                last_id = after_id
        while True:
            query: dict[str, Any] = {} if last_id is None else {"_id": {"$gt": last_id}}
            cursor = self.collection.find(query, projection).sort("_id", 1).limit(size)
            try:
                batch = list(cursor)
            finally:
                close = getattr(cursor, "close", None)
                if close is not None:
                    close()
            if not batch:
                return
            last_id = batch[-1].get("_id")
            for item in batch:
                yield item
            if last_id is None:
                return

    def product_id_at_offset(self, offset: int) -> Any | None:
        """`_id` del producto en la posición dada (0 = primero). Para retomar sin cursor."""
        skip = max(0, int(offset))
        found = self.collection.find({}, {"_id": 1}).sort("_id", 1).skip(skip).limit(1)
        for item in found:
            return item.get("_id")
        return None

    def set_basic_scrape_cursor(self, after_id: Any | None) -> None:
        key = "batch_cursor:scraping_basico"
        if after_id is None or not str(after_id).strip():
            self.app_settings.delete_one({"_id": key})
            return
        self.save_app_setting(
            key,
            {
                "after_id": str(after_id),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def clear_basic_scrape_cursor(self) -> None:
        self.set_basic_scrape_cursor(None)

    def basic_scrape_cursor(self) -> str | None:
        found = self.get_app_setting("batch_cursor:scraping_basico") or {}
        value = str(found.get("after_id") or "").strip()
        return value or None

    def latest_basic_scrape_run(self) -> dict[str, Any] | None:
        return self.batch_runs.find_one(
            {"job": "scraping_basico"},
            sort=[("started_at", -1)],
        )

    def find_running_basic_scrape(self) -> dict[str, Any] | None:
        return self.batch_runs.find_one(
            {"job": "scraping_basico", "status": "running"},
            sort=[("started_at", -1)],
        )

    def latest_batch_run_by_job(self, job: str) -> dict[str, Any] | None:
        key = (job or "").strip()
        if not key:
            return None
        item = self.batch_runs.find_one({"job": key}, sort=[("started_at", -1)])
        if not item:
            return None
        return self._public_batch_run(item)

    def find_running_store_batch(self, store_id: str) -> dict[str, Any] | None:
        key = (store_id or "").strip().lower()
        if not key:
            return None
        return self.batch_runs.find_one(
            {"tienda": key, "status": "running"},
            sort=[("started_at", -1)],
        )

    def category_search_items(self, store: str) -> list[dict[str, Any]]:
        """Hojas del árbol de categorías de una tienda, como consultas de scrape."""
        key = (store or "").strip().lower()
        if not key:
            return []
        rows = list(
            self.categories.find(
                {"store": key},
                {"_id": 0, "id": 1, "name": 1, "parent_id": 1, "path": 1},
            )
        )
        if not rows:
            return []
        parent_ids = {row.get("parent_id") for row in rows if row.get("parent_id")}
        leaves = [row for row in rows if row.get("id") not in parent_ids] if parent_ids else rows
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in sorted(leaves, key=lambda item: str(item.get("name") or "").casefold()):
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            ident = str(row.get("id") or folded)
            items.append(
                {
                    "id": f"cat-{key}-{ident}",
                    "query": name,
                    "category": str(row.get("path") or name),
                    "from_category_tree": True,
                }
            )
        return items

    def recent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        rows = []
        for item in self.batch_runs.find().sort("started_at", -1).limit(limit):
            rows.append(self._public_batch_run(item))
        return rows

    def latest_batch_runs_by_grupo(self) -> dict[str, dict[str, Any]]:
        """Última corrida por grupo. Las de una tienda (campo `tienda`) no entran."""
        pipeline = [
            {
                "$match": {
                    "grupo": {"$type": "string", "$ne": ""},
                    "scope": {"$nin": ["tienda", "basico"]},
                    "job": {"$ne": "scraping_basico"},
                    "$or": [
                        {"tienda": {"$exists": False}},
                        {"tienda": {"$in": [None, ""]}},
                    ],
                }
            },
            {"$sort": {"started_at": -1}},
            {"$group": {"_id": "$grupo", "doc": {"$first": "$$ROOT"}}},
        ]
        out: dict[str, dict[str, Any]] = {}
        for row in self.batch_runs.aggregate(pipeline):
            grupo = str(row.get("_id") or "").strip().lower()
            doc = row.get("doc") or {}
            if not grupo:
                continue
            out[grupo] = self._public_batch_run(doc)
        return out

    def latest_batch_runs_by_tienda(self) -> dict[str, dict[str, Any]]:
        """Última corrida por tienda (botón admin), sin mezclarla con el cron de grupo."""
        pipeline = [
            {
                "$match": {
                    "tienda": {"$type": "string", "$ne": ""},
                    "scope": {"$ne": "basico"},
                    "job": {"$ne": "scraping_basico"},
                }
            },
            {"$sort": {"started_at": -1}},
            {"$group": {"_id": "$tienda", "doc": {"$first": "$$ROOT"}}},
        ]
        out: dict[str, dict[str, Any]] = {}
        for row in self.batch_runs.aggregate(pipeline):
            tienda = str(row.get("_id") or "").strip().lower()
            doc = row.get("doc") or {}
            if not tienda:
                continue
            out[tienda] = self._public_batch_run(doc)
        return out

    def _public_batch_run(self, item: dict[str, Any]) -> dict[str, Any]:
        searches = item.get("searches") or []
        status = item.get("status") or "unknown"
        if status == "error":
            status = "failed"
        stores = item.get("stores") or []
        return {
            "id": str(item["_id"]),
            "started_at": _json_time(item.get("started_at")),
            "finished_at": _json_time(item.get("finished_at")),
            "status": status,
            "phase": item.get("phase"),
            "catalog": item.get("catalog"),
            "source": item.get("source"),
            "grupo": item.get("grupo"),
            "tienda": item.get("tienda") or None,
            "groups": list(item.get("groups") or []),
            "scope": item.get("scope"),
            "stores": list(stores) if stores else [],
            "stores_total": len(stores) if stores else 0,
            "items": item.get("items"),
            "processed": item.get("processed") or 0,
            "current_query": item.get("current_query"),
            "current_id": item.get("current_id"),
            "current_index": item.get("current_index"),
            "last_error": item.get("last_error"),
            "saved_upserted": item.get("saved_upserted") or 0,
            "saved_modified": item.get("saved_modified") or 0,
            "skipped": int(item.get("skipped") or 0),
            "alert_count": item.get("alert_count") or 0,
            "failed": sum(1 for row in searches if row.get("error")),
            "without_price": sum(1 for row in searches if not row.get("error") and not row.get("offers")),
        }

    def stats_overview(self) -> dict[str, Any]:
        runs = self.recent_runs(1)
        return {
            "products": self.count(),
            "searches": self.searches.count_documents({}),
            "alerts": self.alerts.count_documents({}),
            "watches": self.watches.count_documents({}),
            "categories": self.categories.count_documents({}),
            "last_run": runs[0] if runs else None,
        }

    def product_detail(self, store: str, product_id: str) -> dict[str, Any] | None:
        item = self.collection.find_one({"store": store, "product_id": product_id})
        if item is None:
            return None
        item.pop("_id", None)
        return item

    def save_ficha_fields(self, store: str, product_id: str, fields: dict[str, Any]) -> None:
        clean = {key: value for key, value in fields.items() if value not in (None, "", {})}
        if not store or not product_id or not clean:
            return
        self.collection.update_one({"store": store, "product_id": product_id}, {"$set": clean})

    def set_entity_overrides(
        self,
        products: list[tuple[str, str]],
        overrides: list[str | None],
    ) -> dict[str, int]:
        """Fija o limpia agrupaciones manuales de productos concretos."""
        from pymongo import UpdateOne

        operations = []
        for (store, product_id), override in zip(products, overrides):
            query = {"store": store, "product_id": product_id}
            if override:
                update = {"$set": {
                    "entity_override": override,
                    "compare_code": override,
                    "entity_id": override,
                    "entity_confidence": 1.0,
                    "entity_match_method": "manual",
                }}
            else:
                from retail.compare import compare_code

                document = self.collection.find_one(query, {"thumbnail": 0, "price_history": 0})
                if document:
                    document.pop("entity_override", None)
                    automatic = compare_code(Product.from_dict(document))
                    confidence = 1.0 if automatic.startswith("ean:") else 0.9 if automatic.startswith("id:") else 0.65
                    update = {
                        "$set": {
                            "compare_code": automatic,
                            "entity_id": automatic,
                            "entity_confidence": confidence,
                        },
                        "$unset": {"entity_override": "", "entity_match_method": ""},
                    }
                else:
                    update = {"$unset": {"entity_override": "", "entity_match_method": ""}}
            operations.append(UpdateOne(query, update))
        if not operations:
            return {"matched": 0, "modified": 0}
        result = self.collection.bulk_write(operations, ordered=False)
        return {"matched": int(result.matched_count), "modified": int(result.modified_count)}

    def related_candidates(
        self,
        *,
        text: str | None = None,
        catalog_id: str | None = None,
        category_id: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        only_comparable: bool = False,
        limit: int = 48,
    ) -> list[dict[str, Any]]:
        """Candidatos ya guardados. El texto usa el índice; el resto tiene tope de tiempo."""
        projection = {
            "store": 1,
            "product_id": 1,
            "name": 1,
            "brand": 1,
            "url": 1,
            "price": 1,
            "price_normal": 1,
            "price_internet": 1,
            "price_cmr": 1,
            "price_all_payment": 1,
            "price_card": 1,
            "payment_card_name": 1,
            "installment_count": 1,
            "installment_total": 1,
            "financial_cae": 1,
            "payment_conditions": 1,
            "condition": 1,
            "condition_confidence": 1,
            "shipping_cost": 1,
            "shipping_free_threshold": 1,
            "shipping_region": 1,
            "pickup_available": 1,
            "stock": 1,
            "availability": 1,
            "low_stock": 1,
            "only_extreme_sizes": 1,
            "variants": 1,
            "entity_id": 1,
            "entity_confidence": 1,
            "entity_override": 1,
            "entity_match_method": 1,
            "discount_percent": 1,
            "category": 1,
            "category_id": 1,
            "catalog_id": 1,
            "catalog_category": 1,
            "compare_code": 1,
            "image_url": 1,
            "image_urls": 1,
            "thumbnail.mime": 1,
            "specifications": 1,
        }
        seen: dict[tuple[str, str], dict[str, Any]] = {}

        def take(cursor) -> None:
            for item in cursor:
                key = (str(item.get("store") or ""), str(item.get("product_id") or ""))
                if not key[1] or key in seen or not item.get("name"):
                    continue
                item.pop("_id", None)
                specs = item.pop("specifications", None) or {}
                item["comparison_fields"] = sum(1 for value in specs.values() if value not in (None, "", [], {})) if isinstance(specs, dict) else 0
                thumb = item.pop("thumbnail", None) or {}
                item["has_thumb"] = bool(thumb.get("mime") or item.pop("image_url", None) or item.pop("image_urls", None))
                seen[key] = item
                if len(seen) >= limit:
                    return

        query = " ".join(str(text or "").split())
        if query:
            try:
                text_filter: dict[str, Any] = {"$text": {"$search": query}}
                if only_comparable:
                    text_filter["specifications"] = {"$type": "object", "$ne": {}}
                take(
                    self.collection.find(
                        text_filter,
                        {**projection, "score": {"$meta": "textScore"}},
                    )
                    .sort([("score", {"$meta": "textScore"})])
                    .limit(limit)
                    .max_time_ms(1200)
                )
            except Exception:
                pass
        clauses: list[dict[str, Any]] = []
        if catalog_id:
            clauses.append({"catalog_id": catalog_id})
        if category_id:
            clauses.append({"category_id": category_id})
        if category:
            clauses.append({"category": category})
            clauses.append({"catalog_category": category})
        if brand:
            clauses.append({"brand": brand})
        if clauses and len(seen) < limit:
            try:
                related_filter: dict[str, Any] = {"$or": clauses}
                if only_comparable:
                    related_filter["specifications"] = {"$type": "object", "$ne": {}}
                take(
                    self.collection.find(related_filter, projection)
                    .sort("updated_at", -1)
                    .limit(limit)
                    .max_time_ms(1200)
                )
            except Exception:
                pass
        return list(seen.values())

    def by_compare_code(self, code: str, limit: int = 30) -> list[dict[str, Any]]:
        rows = []
        for item in self.collection.find({"compare_code": code}).sort("price", 1).limit(limit):
            item.pop("_id", None)
            rows.append(item)
        return rows

    @staticmethod
    def _public_product_review(item: dict[str, Any] | None, user_id: str | None = None) -> dict[str, Any] | None:
        if not item:
            return None
        return {
            "id": str(item.get("_id") or ""),
            "rating": int(item.get("rating") or 0),
            "comment": str(item.get("comment") or ""),
            "author": str(item.get("author") or "Usuario"),
            "created_at": _json_time(item.get("created_at")),
            "updated_at": _json_time(item.get("updated_at")),
            "mine": bool(user_id and str(item.get("user_id") or "") == str(user_id)),
        }

    def product_review_summary(
        self,
        store: str,
        product_id: str,
        *,
        user_id: str | None = None,
        limit: int = 3,
        skip: int = 0,
    ) -> dict[str, Any]:
        match = {"store": store, "product_id": product_id}
        totals = list(self.product_reviews.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "count": {"$sum": 1}, "average": {"$avg": "$rating"}}},
        ]))
        total = totals[0] if totals else {}
        comment_match = {**match, "comment": {"$nin": ["", None]}}
        comment_count = self.product_reviews.count_documents(comment_match)
        cursor = (
            self.product_reviews.find(comment_match)
            .sort([("updated_at", -1), ("_id", -1)])
            .skip(skip)
            .limit(limit)
        )
        reviews = [self._public_product_review(item, user_id) for item in cursor]
        mine = self.product_reviews.find_one({**match, "user_id": user_id}) if user_id else None
        return {
            "average": round(float(total.get("average") or 0), 1),
            "count": int(total.get("count") or 0),
            "comment_count": int(comment_count),
            "reviews": [item for item in reviews if item],
            "mine": self._public_product_review(mine, user_id),
        }

    def save_product_review(
        self,
        store: str,
        product_id: str,
        user_id: str,
        author: str,
        rating: int,
        comment: str,
    ) -> dict[str, Any]:
        key = {"store": store, "product_id": product_id, "user_id": user_id}
        now = _now()
        self.product_reviews.update_one(
            key,
            {
                "$set": {
                    "author": author or "Usuario",
                    "rating": int(rating),
                    "comment": comment,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return self._public_product_review(self.product_reviews.find_one(key), user_id) or {}

    @staticmethod
    def _public_user(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if not item:
            return None
        created = item.get("created_at")
        approved = item.get("approved_at")
        return {
            "id": str(item.get("_id") or item.get("id") or ""),
            "email": item.get("email"),
            "name": item.get("name") or "",
            "role": item.get("role") or "user",
            "status": item.get("status") or "pending",
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
            "approved_at": approved.isoformat() if hasattr(approved, "isoformat") else approved,
        }

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.users.find_one({"email": email})

    def find_user_by_confirmation_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.users.find_one({"confirmation_token_hash": token_hash})

    def find_user_by_password_reset_token_hash(self, token_hash: str) -> dict[str, Any] | None:
        return self.users.find_one({"password_reset_token_hash": token_hash})

    def find_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            found = self.users.find_one({"_id": ObjectId(user_id)})
        except (InvalidId, TypeError):
            return None
        return found

    def catalog_analysis(self, *, group_by: str = "catalog_category", limit: int = 50) -> list[dict[str, Any]]:
        """Agregaciones simples para análisis de catálogo.

        Devuelve una lista con estadísticas por `group_by` (por defecto
        `catalog_category`) con: conteo, medianas aproximadas, precios min/max y tiendas.
        """
        pipeline = [
            {"$match": {group_by: {"$exists": True, "$ne": None}}},
            {
                "$group": {
                    "_id": f"${group_by}",
                    "count": {"$sum": 1},
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "max_price": {"$max": "$price"},
                    "stores": {"$addToSet": "$store"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": limit},
        ]
        try:
            cursor = list(self.collection.aggregate(pipeline))
        except Exception as exc:
            print(f"catalog_analysis: error en agregación: {exc}")
            return []
        results: list[dict[str, Any]] = []
        for doc in cursor:
            results.append(
                {
                    group_by: doc.get("_id"),
                    "count": int(doc.get("count") or 0),
                    "avg_price": int(round(doc.get("avg_price") or 0)),
                    "min_price": int(doc.get("min_price") or 0),
                    "max_price": int(doc.get("max_price") or 0),
                    "stores": doc.get("stores") or [],
                }
            )
        return results

    def insert_user(self, data: dict[str, Any]) -> dict[str, Any]:
        document = dict(data)
        document.setdefault("created_at", _now())
        result = self.users.insert_one(document)
        document["_id"] = result.inserted_id
        return document

    def update_user(self, user_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            key = {"_id": ObjectId(user_id)}
        except (InvalidId, TypeError):
            return None
        self.users.update_one(key, {"$set": fields})
        return self.users.find_one(key)

    def update_user_fields(
        self, user_id: str, fields: dict[str, Any], *, unset: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        """Actualiza una cuenta y permite limpiar campos de conexión obsoletos."""
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            key = {"_id": ObjectId(user_id)}
        except (InvalidId, TypeError):
            return None
        update: dict[str, Any] = {"$set": fields}
        if unset:
            update["$unset"] = {name: "" for name in unset}
        self.users.update_one(key, update)
        return self.users.find_one(key)

    def list_users(self) -> list[dict[str, Any]]:
        rows = []
        for item in self.users.find().sort("created_at", -1):
            public = self._public_user(item)
            if public:
                rows.append(public)
        return rows

    def get_app_setting(self, key: str) -> dict[str, Any] | None:
        found = self.app_settings.find_one({"_id": str(key)})
        if not found:
            return None
        return {name: value for name, value in found.items() if name != "_id"}

    def save_app_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        document = {**dict(value), "updated_at": _now()}
        self.app_settings.update_one({"_id": str(key)}, {"$set": document}, upsert=True)
        return {name: value for name, value in document.items() if name != "updated_at"}

    def product_short_code(self, store: str, product_id: str) -> str:
        """Código numérico estable para una ficha interna."""
        from pymongo import ReturnDocument

        clean_store = str(store or "").strip().lower()
        clean_product = str(product_id or "").strip()
        if not clean_store or not clean_product:
            return ""
        key = {"store": clean_store, "product_id": clean_product}
        found = self.short_links.find_one(key, {"code": 1})
        if found and found.get("code"):
            return str(found["code"])
        counter = self.app_settings.find_one_and_update(
            {"_id": "short_link_counter"},
            {"$inc": {"value": 1}, "$set": {"updated_at": _now()}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        ) or {}
        offset = max(
            100_000_000,
            int(os.environ.get("SHORT_LINK_OFFSET", "237000000") or 237000000),
        )
        code = str(offset + int(counter.get("value") or 1))
        document = self.short_links.find_one_and_update(
            key,
            {
                "$setOnInsert": {
                    **key,
                    "code": code,
                    "created_at": _now(),
                    "clicks": 0,
                },
                "$set": {"updated_at": _now()},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        ) or {}
        return str(document.get("code") or code)

    def resolve_product_short_link(
        self, code: str, *, record_click: bool = True
    ) -> dict[str, Any] | None:
        clean = str(code or "").strip()
        if not clean.isdigit() or not (6 <= len(clean) <= 18):
            return None
        if record_click:
            from pymongo import ReturnDocument

            found = self.short_links.find_one_and_update(
                {"code": clean},
                {"$inc": {"clicks": 1}, "$set": {"last_clicked_at": _now()}},
                return_document=ReturnDocument.AFTER,
            )
        else:
            found = self.short_links.find_one({"code": clean})
        if not found:
            return None
        return {
            "code": clean,
            "store": str(found.get("store") or ""),
            "product_id": str(found.get("product_id") or ""),
            "clicks": int(found.get("clicks") or 0),
        }

    def list_notification_users(self) -> list[dict[str, Any]]:
        """Cuentas aprobadas con los campos mínimos para alertas personales."""
        projection = {
            "email": 1, "status": 1, "telegram_chat_id": 1,
            "telegram_username": 1, "telegram": 1, "notification_preferences": 1,
            "push_subscriptions": 1,
        }
        return list(self.users.find({"status": "approved"}, projection))

    @staticmethod
    def _user_has_telegram(item: dict[str, Any]) -> bool:
        """Misma idea que los chats de cuenta en alertas: si hay id o usuario, hay chat."""
        for field in ("telegram_chat_id", "telegram_username"):
            if str(item.get(field) or "").strip():
                return True
        telegram = item.get("telegram")
        if isinstance(telegram, str) and telegram.strip():
            return True
        if isinstance(telegram, dict):
            return any(str(telegram.get(field) or "").strip() for field in ("chat_id", "username", "id"))
        return False

    @staticmethod
    def admin_user_public(item: dict[str, Any] | None, *, price_alerts: int = 0) -> dict[str, Any] | None:
        """Vista de admin. Nunca incluye hash, token ni el chat de Telegram."""
        public = ProductRepository._public_user(item)
        if not public or item is None:
            return None
        try:
            count = max(0, int(price_alerts or 0))
        except (TypeError, ValueError):
            count = 0
        return {
            "id": public["id"],
            "email": public.get("email") or "",
            "name": public.get("name") or "",
            "role": public.get("role") or "user",
            "status": public.get("status") or "pending",
            "created_at": public.get("created_at"),
            "has_telegram": ProductRepository._user_has_telegram(item),
            "price_alerts": count,
        }

    def _price_alert_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        alerts = getattr(self, "price_alerts", None)
        if alerts is None:
            return counts
        try:
            pipeline = [
                {"$match": {"active": {"$ne": False}}},
                {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
            ]
            for row in alerts.aggregate(pipeline):
                key = str(row.get("_id") or "")
                if key:
                    counts[key] = int(row.get("n") or 0)
        except Exception:
            return {}
        return counts

    def list_admin_users(self) -> list[dict[str, Any]]:
        counts = self._price_alert_counts()
        rows = []
        projection = {"password_hash": 0, "password": 0, "token": 0, "session": 0}
        for item in self.users.find({}, projection).sort("created_at", -1):
            user_id = str(item.get("_id") or item.get("id") or "")
            public = self.admin_user_public(item, price_alerts=counts.get(user_id, 0))
            if public:
                rows.append(public)
        return rows

    def ensure_bootstrap_admin(self) -> dict[str, Any] | None:
        from retail.auth import admin_email, admin_password, hash_password

        email = admin_email()
        password = admin_password()
        if not email or not password:
            return None
        found = self.find_user_by_email(email)
        fields = {
            "name": "Administrador",
            "role": "admin",
            "status": "approved",
            "approved_at": _now(),
        }
        if found:
            if not found.get("password_hash") or os.environ.get("RETAIL_FORCE_ADMIN_PASSWORD", "").lower() in {"1", "true", "yes"}:
                fields["password_hash"] = hash_password(password)
            updated = self.update_user(str(found.get("_id") or found.get("id")), fields)
            return self._public_user(updated or found)
        fields["password_hash"] = hash_password(password)
        created = self.insert_user({"email": email, **fields})
        return self._public_user(created)

    def list_watches(self, active_only: bool = False, user_id: str | None = None) -> list[dict[str, Any]]:
        query: dict[str, Any] = {}
        if active_only:
            query["active"] = True
        if user_id:
            query["user_id"] = user_id
        rows = []
        for item in self.watches.find(query).sort("created_at", -1):
            item["id"] = str(item.pop("_id"))
            created = item.get("created_at")
            item["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
            rows.append(item)
        return rows

    def save_watch(self, data: dict[str, Any]) -> dict[str, Any]:
        document = {
            "query": str(data.get("query") or "").strip(),
            "compare_code": data.get("compare_code"),
            "name": data.get("name"),
            "store": data.get("store"),
            "product_id": data.get("product_id"),
            "url": data.get("url"),
            "target_price": data.get("target_price"),
            "drop_percent": data.get("drop_percent"),
            "watch_changes": bool(data.get("watch_changes", not data.get("target_price") and not data.get("drop_percent"))),
            "active": bool(data.get("active", True)),
            "user_id": data.get("user_id"),
            "email": data.get("email"),
            "updated_at": _now(),
        }
        if data.get("last_seen_price") is not None:
            document["last_seen_price"] = int(data["last_seen_price"])
        key = {
            "user_id": document["user_id"],
            "compare_code": document["compare_code"],
            "query": document["query"],
        }
        self.watches.update_one(key, {"$set": document, "$setOnInsert": {"created_at": _now()}}, upsert=True)
        found = self.watches.find_one(key) or {}
        found["id"] = str(found.pop("_id", ""))
        created = found.get("created_at")
        found["created_at"] = created.isoformat() if hasattr(created, "isoformat") else created
        return found

    def delete_watch(self, watch_id: str, user_id: str | None = None) -> bool:
        from bson import ObjectId
        from bson.errors import InvalidId

        try:
            query: dict[str, Any] = {"_id": ObjectId(watch_id)}
        except (InvalidId, TypeError):
            return False
        if user_id:
            query["user_id"] = user_id
        return self.watches.delete_one(query).deleted_count > 0

    def get_price_alert(self, user_id: str, store: str, product_id: str) -> dict[str, Any] | None:
        found = self.price_alerts.find_one(
            {"user_id": user_id, "store": store, "product_id": product_id, "active": True}
        )
        if not found:
            return None
        return self._public_price_alert(found)

    def save_price_alert(self, data: dict[str, Any]) -> dict[str, Any]:
        document = {
            "user_id": str(data.get("user_id") or ""),
            "email": str(data.get("email") or "").strip(),
            "store": str(data.get("store") or "").strip().lower(),
            "product_id": str(data.get("product_id") or "").strip(),
            "name": data.get("name") or "",
            "url": data.get("url") or "",
            "active": True,
            "updated_at": _now(),
        }
        key = {
            "user_id": document["user_id"],
            "store": document["store"],
            "product_id": document["product_id"],
        }
        self.price_alerts.update_one(
            key,
            {"$set": document, "$setOnInsert": {"created_at": _now()}},
            upsert=True,
        )
        found = self.price_alerts.find_one(key) or {}
        return self._public_price_alert(found)

    def delete_price_alert(self, user_id: str, store: str, product_id: str) -> bool:
        result = self.price_alerts.delete_one(
            {"user_id": user_id, "store": store, "product_id": product_id}
        )
        return result.deleted_count > 0

    def price_alerts_for(self, keys: list[tuple[str, str]]) -> list[dict[str, Any]]:
        wanted = [(store, product_id) for store, product_id in keys if store and product_id]
        if not wanted:
            return []
        rows: list[dict[str, Any]] = []
        for start in range(0, len(wanted), 200):
            chunk = wanted[start : start + 200]
            query = {
                "active": True,
                "$or": [{"store": store, "product_id": product_id} for store, product_id in chunk],
            }
            for item in self.price_alerts.find(query):
                public = dict(item)
                public.pop("_id", None)
                rows.append(public)
        return rows

    def claim_price_alert_send(
        self,
        user_id: str,
        store: str,
        product_id: str,
        previous_price: int,
        price: int,
        *,
        channel: str = "email",
    ) -> bool:
        """Comparte la ventana por producto/precio con los demás tipos de aviso."""
        if not user_id or not store or not product_id:
            return False
        # Los envíos anteriores a esta regla incluían el precio de origen en
        # su clave. Respetarlos aunque ahora el precio anterior sea distinto.
        if self.price_alert_sends.find_one({
            "user_id": str(user_id),
            "store": store,
            "product_id": product_id,
            "price": int(price),
            "created_at": {"$gt": _now() - timedelta(days=NOTIFICATION_COOLDOWN_DAYS)},
        }, {"_id": 1}):
            return False
        product = self.collection.find_one(
            {"store": store, "product_id": product_id}, {"compare_code": 1},
        ) or {}
        entity_key = str(product.get("compare_code") or f"product:{store}:{product_id}")
        recipient = "global" if channel.startswith("webhook:") else user_id
        return self.claim_user_notification_send(recipient, channel, entity_key, price)

    def claim_user_notification_send(
        self,
        user_id: str,
        channel: str,
        entity_key: str,
        price: int | None,
        *,
        cooldown_days: int = NOTIFICATION_COOLDOWN_DAYS,
    ) -> bool:
        """Reserva atómicamente producto/precio por destinatario y canal durante 5 días."""
        from pymongo.errors import DuplicateKeyError

        if not user_id or not channel or not entity_key:
            return False
        now = _now()
        cutoff = now - timedelta(days=max(1, int(cooldown_days)))
        price = int(price) if price is not None else None
        key = {
            "user_id": str(user_id),
            "channel": str(channel),
            "entity_key": str(entity_key),
        }
        try:
            result = self.user_notification_sends.update_one(
                {
                    **key,
                    "$nor": [
                        {"recent_sends": {"$elemMatch": {"price": price, "sent_at": {"$gt": cutoff}}}},
                        {"last_price": price, "last_sent_at": {"$gt": cutoff}},
                    ],
                },
                [{"$set": {
                    **{field: {"$literal": value} for field, value in key.items()},
                    "created_at": {"$ifNull": ["$created_at", now]},
                    "last_sent_at": now,
                    "last_price": price,
                    # Conservar todos los precios de la ventana evita repetir
                    # A después de notificar B. También incorpora el historial
                    # antiguo, que solo guardaba el último precio.
                    "recent_sends": {"$setUnion": [
                        {"$filter": {
                            "input": {"$concatArrays": [
                                {"$ifNull": ["$recent_sends", []]},
                                [{"price": "$last_price", "sent_at": "$last_sent_at"}],
                            ]},
                            "as": "send",
                            "cond": {"$gt": ["$$send.sent_at", cutoff]},
                        }},
                        [{"price": price, "sent_at": now}],
                    ]},
                }}],
                upsert=True,
            )
        except DuplicateKeyError:
            return False
        return bool(result.upserted_id is not None or result.modified_count)

    @staticmethod
    def _public_price_alert(item: dict[str, Any]) -> dict[str, Any]:
        created = item.get("created_at")
        return {
            "id": str(item.get("_id") or item.get("id") or ""),
            "user_id": item.get("user_id"),
            "email": item.get("email") or "",
            "store": item.get("store"),
            "product_id": item.get("product_id"),
            "name": item.get("name") or "",
            "active": bool(item.get("active", True)),
            "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
        }

    def mark_watch_notified(self, watch_id: Any, price: int) -> None:
        from bson import ObjectId

        key = watch_id if isinstance(watch_id, ObjectId) else ObjectId(str(watch_id))
        self.watches.update_one(
            {"_id": key},
            {"$set": {"last_notified_at": _now(), "last_notified_price": price, "last_seen_price": price}},
        )

    def mark_watch_checked(self, watch_id: Any, price: int) -> None:
        from bson import ObjectId

        key = watch_id if isinstance(watch_id, ObjectId) else ObjectId(str(watch_id))
        self.watches.update_one(
            {"_id": key},
            {"$set": {"last_checked_at": _now(), "last_seen_price": int(price)}},
        )
