"""Non-destructive identity-model projection for legacy product documents."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import unicodedata
from typing import Any

from retail.compare import extract_ean, extract_manufacturer_codes
from retail.models import Product

COLLECTIONS = (
    "catalog_products",
    "product_variants",
    "sellers",
    "offers",
    "price_observations",
    "promotion_conditions",
    "shipping_quotes",
    "product_matches",
)

_VARIANT_FIELDS = {
    "capacity": ("capacity", "capacidad", "almacenamiento"),
    "size": ("size", "talla", "tamano"),
    "color": ("color", "colour"),
    "pack": ("pack", "packaging", "contenido", "formato"),
    "version": ("version", "versionproducto"),
}
_QUANTITY_FIELDS = ("quantity", "cantidad", "contenido neto", "contenido")
_UNIT_FIELDS = ("unit", "unidad", "unidad de medida")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", "", text)


def _stable_id(prefix: str, *values: Any) -> str:
    encoded = json.dumps(values, ensure_ascii=True, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _spec_value(specs: Any, keys: tuple[str, ...]) -> Any:
    if not isinstance(specs, dict):
        return None
    wanted = {_fold(key) for key in keys}
    return next(
        (value for key, value in specs.items() if _fold(key) in wanted and value not in (None, "")),
        None,
    )


def _first_value(document: dict[str, Any], specs: Any, *keys: str) -> Any:
    for key in keys:
        value = document.get(key)
        if value not in (None, ""):
            return value
    return _spec_value(specs, tuple(keys))


def _quantity(value: Any) -> tuple[int | float | None, str | None]:
    if isinstance(value, bool) or value in (None, ""):
        return None, None
    raw = str(value).strip()
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)\s*([^\d].*)?", raw)
    if not match:
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None, None
        unit = None
    else:
        try:
            number = Decimal(match.group(1).replace(",", "."))
        except InvalidOperation:
            return None, None
        unit = (match.group(2) or "").strip() or None
    if not number.is_finite() or number <= 0:
        return None, unit
    numeric: int | float = int(number) if number == number.to_integral_value() else float(number)
    return numeric, unit


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    return int(number) if number == number.to_integral_value() else float(number)


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _source_key(document: dict[str, Any]) -> tuple[str, str]:
    return (
        str(document.get("store") or "").strip().lower(),
        str(document.get("product_id") or document.get("sku_id") or "").strip(),
    )


def _score(document: dict[str, Any]) -> float | None:
    try:
        value = float(document.get("entity_confidence"))
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value <= 1.0 else None


def _method(document: dict[str, Any]) -> str:
    if document.get("entity_override") or document.get("entity_match_method") == "manual":
        return "manual"
    raw = str(document.get("entity_match_method") or "").strip().lower()
    if raw in {"ai", "llm", "semantic_ai"}:
        return "ai"
    return "deterministic"


def _product_id(document: dict[str, Any], gtin: str | None) -> str:
    if gtin:
        return f"gtin:{gtin}"
    override = str(document.get("entity_override") or "").strip()
    if override:
        return _stable_id("product:manual", override)
    store, external_id = _source_key(document)
    return _stable_id("product:legacy", store, external_id)


def _variant_attributes(
    document: dict[str, Any],
    specs: Any,
    raw_variant: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = raw_variant if raw_variant is not None else document
    attributes: dict[str, Any] = {}
    for field, aliases in _VARIANT_FIELDS.items():
        value = _first_value(source, specs, field, *aliases)
        if value not in (None, ""):
            attributes[field] = value
    return attributes


def _variant_records(
    document: dict[str, Any],
    product_id: str,
    specs: Any,
) -> list[dict[str, Any]]:
    raw_variants = document.get("variants")
    records: list[dict[str, Any]] = []
    if isinstance(raw_variants, list) and raw_variants:
        for raw in raw_variants:
            if not isinstance(raw, dict):
                continue
            attributes = _variant_attributes(document, specs, raw)
            name = str(raw.get("name") or raw.get("title") or raw.get("value") or "").strip() or None
            sku = str(raw.get("sku") or raw.get("sku_id") or raw.get("id") or "").strip() or None
            if not attributes and not name and not sku:
                continue
            identity = attributes or ({"name": name} if name else {"sku": sku})
            identity_key = _stable_id("variant-key", product_id, identity)
            records.append({
                "_id": _stable_id("variant", product_id, identity_key),
                "product_id": product_id,
                "identity_key": identity_key,
                **attributes,
                **({"name": name} if name else {}),
                **({"sku": sku} if sku else {}),
                **({"stock": raw["stock"]} if raw.get("stock") is not None else {}),
                **({"available": raw["available"]} if isinstance(raw.get("available"), bool) else {}),
            })
    else:
        attributes = _variant_attributes(document, specs)
        if attributes:
            identity_key = _stable_id("variant-key", product_id, attributes)
            records.append({
                "_id": _stable_id("variant", product_id, identity_key),
                "product_id": product_id,
                "identity_key": identity_key,
                **attributes,
            })
    return records


def _observation(
    document: dict[str, Any],
    offer_id: str,
    product_id: str,
    point: dict[str, Any],
    *,
    current: bool,
) -> dict[str, Any] | None:
    timestamp_value = (
        point.get("scraped_at")
        or point.get("observed_at")
        or (
            document.get("scraped_at") or document.get("updated_at")
            if current
            else None
        )
    )
    observed_at = _timestamp(timestamp_value)
    price = _number(
        point.get("price")
        if point.get("price") not in (None, "")
        else point.get("price_offer")
    )
    if current and price is None:
        price = _number(
            document.get("price_all_payment")
            or document.get("price_internet")
            or document.get("price")
        )
    if observed_at is None or price is None or price <= 0:
        return None
    basis = point.get("price_basis")
    if not basis and current:
        basis = "all_payment" if document.get("price_all_payment") or document.get("price_internet") else "published"
    basis = str(basis or "unknown")
    currency = str(point.get("currency") or document.get("currency") or "CLP").upper()
    normal = _number(point.get("price_normal") or (document.get("price_normal") if current else None))
    stock = point.get("stock") if "stock" in point else (document.get("stock") if current else None)
    identity = (offer_id, observed_at.isoformat(), price, normal, basis, currency, stock)
    timestamp_source = (
        "scraped_at" if point.get("scraped_at") or (current and document.get("scraped_at"))
        else "observed_at" if point.get("observed_at")
        else "updated_at"
    )
    row = {
        "_id": _stable_id("observation", *identity),
        "offer_id": offer_id,
        "product_id": product_id,
        "observed_at": observed_at,
        "price": price,
        "currency": currency,
        "price_basis": basis,
        "timestamp_source": timestamp_source,
    }
    if normal is not None:
        row["price_normal"] = normal
    if stock is not None:
        row["stock"] = stock
        row["stock_verified"] = bool(document.get("stock_verified")) if current else bool(point.get("stock_verified"))
    return row


def _time_field(document: dict[str, Any], *keys: str) -> datetime | str | None:
    for key in keys:
        value = document.get(key)
        if value not in (None, ""):
            return _timestamp(value) or str(value)
    return None


def _promotion_records(
    document: dict[str, Any],
    offer_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    card_price = _number(document.get("price_card") or document.get("price_cmr"))
    card_name = document.get("payment_card_name")
    payment_terms = document.get("payment_conditions")
    if card_price is not None or card_name or payment_terms:
        candidates.append({
            "type": "card",
            "card_name": card_name,
            "price": card_price,
            "terms": payment_terms,
            "valid_from": _time_field(document, "promotion_valid_from", "valid_from"),
            "valid_to": _time_field(document, "promotion_valid_to", "valid_to"),
        })
    coupon_price = _number(document.get("price_coupon"))
    coupon_code = document.get("coupon_code")
    if coupon_price is not None or coupon_code:
        candidates.append({
            "type": "coupon",
            "coupon_code": coupon_code,
            "price": coupon_price,
            "terms": document.get("coupon_conditions"),
            "valid_from": _time_field(document, "coupon_valid_from", "promotion_valid_from"),
            "valid_to": _time_field(document, "coupon_valid_to", "promotion_valid_to"),
        })
    raw_conditions = document.get("promotion_conditions")
    if isinstance(raw_conditions, list):
        candidates.extend(
            {key: value for key, value in row.items() if key in {
                "type", "card_name", "coupon_code", "price", "terms", "valid_from", "valid_to"
            }}
            for row in raw_conditions
            if isinstance(row, dict) and row.get("type")
        )

    records = []
    for candidate in candidates:
        kind = str(candidate.get("type") or "unknown").strip().lower()
        discriminator = (
            candidate.get("coupon_code")
            or candidate.get("card_name")
            or candidate.get("terms")
            or kind
        )
        record = {
            "_id": _stable_id("promotion", offer_id, kind, discriminator),
            "offer_id": offer_id,
            "type": kind,
            "last_seen_at": now,
        }
        observed_at = _timestamp(document.get("scraped_at") or document.get("updated_at"))
        if observed_at is not None:
            record["observed_at"] = observed_at
        for key in ("card_name", "coupon_code", "terms", "valid_from", "valid_to"):
            value = candidate.get(key)
            if value not in (None, ""):
                record[key] = value
        price = _number(candidate.get("price"))
        if price is not None:
            record["price"] = price
            record["currency"] = str(document.get("currency") or "CLP").upper()
        records.append(record)
    return records


def _shipping_record(
    document: dict[str, Any],
    offer_id: str,
    now: datetime,
) -> dict[str, Any] | None:
    cost = _number(document.get("shipping_cost"))
    delivery_days = next(
        (
            document.get(key) for key in ("shipping_days", "delivery_days", "estimated_delivery_days")
            if document.get(key) not in (None, "")
        ),
        None,
    )
    comuna = next(
        (
            document.get(key) for key in ("shipping_comuna", "comuna", "destination_commune")
            if document.get(key) not in (None, "")
        ),
        None,
    )
    region = document.get("shipping_region")
    if cost is None and delivery_days is None and not document.get("pickup_available"):
        return None
    quote_key = str(comuna or "unknown").strip().lower()
    record = {
        "_id": _stable_id("shipping", offer_id, quote_key),
        "offer_id": offer_id,
        "comuna": str(comuna).strip() if comuna else None,
        "quoted_at": _timestamp(document.get("scraped_at") or document.get("updated_at")),
        "last_seen_at": now,
        "currency": str(document.get("currency") or "CLP").upper(),
    }
    if cost is not None:
        record["cost"] = cost
    if delivery_days is not None:
        record["delivery_days"] = delivery_days
    if region not in (None, ""):
        record["region"] = region
    if document.get("shipping_free_threshold") is not None:
        record["free_shipping_threshold"] = _number(document.get("shipping_free_threshold"))
    if isinstance(document.get("pickup_available"), bool):
        record["pickup_available"] = document["pickup_available"]
    if document.get("shipping_source"):
        record["source"] = document["shipping_source"]
    return record


def build_product_identity_records(
    document: dict[str, Any],
    *,
    now: datetime | None = None,
    include_history: bool = False,
) -> dict[str, list[dict[str, Any]]]:
    """Build identity-model documents without mutating the legacy product."""
    moment = now or _now()
    store, external_id = _source_key(document)
    if not store or not external_id:
        raise ValueError("A legacy product needs both store and product_id")

    product = Product.from_dict(document)
    gtin = extract_ean(product)
    product_id = _product_id(document, gtin)
    seller_name = str(document.get("seller") or store).strip()
    seller_external_id = str(document.get("seller_id") or "").strip()
    seller_key = seller_external_id or _fold(seller_name) or store
    seller_id = _stable_id("seller", store, seller_key)
    offer_id = _stable_id("offer", store, external_id)
    specs = document.get("specifications")

    raw_quantity = _first_value(document, specs, *_QUANTITY_FIELDS)
    quantity, parsed_unit = _quantity(raw_quantity)
    unit = _first_value(document, specs, *_UNIT_FIELDS) or parsed_unit
    mpn = _first_value(
        document,
        specs,
        "mpn",
        "manufacturer_part_number",
        "part_number",
        "codigo fabricante",
    )
    if not mpn:
        codes = extract_manufacturer_codes(product)
        mpn = codes[0] if codes else None
    model = _first_value(document, specs, "model", "modelo")

    canonical_product: dict[str, Any] = {
        "_id": product_id,
        "name": str(document.get("name") or "").strip(),
        "source_identity": "gtin" if gtin else "manual" if document.get("entity_override") else "legacy_offer",
        "updated_at": moment,
    }
    optional_product_fields = {
        "gtin": gtin,
        "brand": document.get("brand"),
        "mpn": mpn,
        "model": model,
        "category": document.get("catalog_category") or document.get("category"),
        "category_id": document.get("category_id"),
        "unit": unit,
        "quantity": quantity,
        "quantity_raw": raw_quantity if quantity is None and raw_quantity not in (None, "") else None,
    }
    canonical_product.update({
        key: value for key, value in optional_product_fields.items() if value not in (None, "")
    })
    if gtin:
        canonical_product["gtin_normalized"] = gtin
    canonical_product["name_normalized"] = _fold(canonical_product["name"])

    variants = _variant_records(document, product_id, specs)
    selected_variant_id = str(
        document.get("selected_variant_id") or document.get("variant_id") or ""
    ).strip()
    if selected_variant_id:
        selected = next(
            (
                row for row in variants
                if selected_variant_id in {str(row.get("sku") or ""), str(row.get("name") or ""), row["_id"]}
            ),
            None,
        )
    else:
        selected = variants[0] if len(variants) == 1 else None

    seller = {
        "_id": seller_id,
        "store": store,
        "seller_key": seller_key,
        "name": seller_name,
        "updated_at": moment,
    }
    if seller_external_id:
        seller["external_seller_id"] = seller_external_id

    offer = {
        "_id": offer_id,
        "store": store,
        "external_product_id": external_id,
        "seller_id": seller_id,
        "product_id": product_id,
        "title": document.get("name"),
        "url": document.get("url"),
        "condition": document.get("condition"),
        "availability": document.get("availability"),
        "last_seen_at": _timestamp(document.get("scraped_at") or document.get("updated_at")) or moment,
        "updated_at": moment,
    }
    if selected:
        offer["variant_id"] = selected["_id"]

    is_gtin_match = gtin is not None
    is_manual_match = bool(document.get("entity_override"))
    score = 1.0 if is_gtin_match or is_manual_match else _score(document)
    method = _method(document)
    match = {
        "_id": _stable_id("match", offer_id),
        "offer_id": offer_id,
        "product_id": product_id,
        "candidate_key": str(document.get("compare_code") or document.get("entity_id") or "") or None,
        "confidence_score": score,
        "method": method,
        "review_status": "approved" if is_gtin_match or is_manual_match else "pending",
        "updated_at": moment,
    }

    observations: dict[str, dict[str, Any]] = {}
    if include_history:
        history = document.get("price_history")
        if isinstance(history, list):
            for point in history:
                if isinstance(point, dict):
                    row = _observation(document, offer_id, product_id, point, current=False)
                    if row:
                        observations[row["_id"]] = row
    current = _observation(document, offer_id, product_id, {}, current=True)
    if current:
        observations[current["_id"]] = current

    return {
        "catalog_products": [canonical_product],
        "product_variants": variants,
        "sellers": [seller],
        "offers": [offer],
        "price_observations": list(observations.values()),
        "promotion_conditions": _promotion_records(document, offer_id, moment),
        "shipping_quotes": [quote] if (quote := _shipping_record(document, offer_id, moment)) else [],
        "product_matches": [match],
    }


def ensure_product_identity_indexes(db: Any) -> None:
    """Create search, relation, and time-series access indexes for MongoDB 7."""
    db.catalog_products.create_index(
        [("gtin", 1)],
        unique=True,
        partialFilterExpression={"gtin": {"$type": "string"}},
        name="catalog_product_gtin_unique",
    )
    db.catalog_products.create_index(
        [("category", 1), ("brand", 1), ("name_normalized", 1)],
        name="catalog_product_category_brand_name",
    )
    db.catalog_products.create_index(
        [("name", "text"), ("brand", "text"), ("mpn", "text"), ("model", "text")],
        name="catalog_product_text_search",
    )
    db.product_variants.create_index(
        [("product_id", 1), ("identity_key", 1)],
        unique=True,
        name="product_variant_identity_unique",
    )
    db.sellers.create_index(
        [("store", 1), ("seller_key", 1)],
        unique=True,
        name="seller_store_identity_unique",
    )
    db.offers.create_index(
        [("store", 1), ("external_product_id", 1)],
        unique=True,
        name="offer_store_external_product_unique",
    )
    db.offers.create_index(
        [("product_id", 1), ("variant_id", 1)],
        name="offer_product_variant",
    )
    db.offers.create_index(
        [("seller_id", 1), ("last_seen_at", -1)],
        name="offer_seller_last_seen",
    )
    db.price_observations.create_index(
        [("offer_id", 1), ("observed_at", -1)],
        name="price_observation_offer_time",
    )
    db.price_observations.create_index(
        [("product_id", 1), ("observed_at", -1)],
        name="price_observation_product_time",
    )
    db.price_observations.create_index(
        [("observed_at", -1)],
        name="price_observation_time",
    )
    db.promotion_conditions.create_index(
        [("offer_id", 1), ("type", 1), ("valid_from", 1), ("valid_to", 1)],
        name="promotion_offer_validity",
    )
    db.shipping_quotes.create_index(
        [("offer_id", 1), ("comuna", 1)],
        unique=True,
        name="shipping_offer_comuna_unique",
    )
    db.product_matches.create_index(
        [("offer_id", 1)],
        unique=True,
        name="product_match_offer_unique",
    )
    db.product_matches.create_index(
        [("review_status", 1), ("confidence_score", -1), ("updated_at", -1)],
        name="product_match_review_queue",
    )


def sync_product_identity_batch(
    db: Any,
    documents: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    include_history: bool = False,
) -> dict[str, int]:
    """Idempotently project legacy documents to the separated collections."""
    from pymongo import UpdateOne

    moment = now or _now()
    operations: dict[str, list[Any]] = {name: [] for name in COLLECTIONS}
    source_records = [
        build_product_identity_records(document, now=moment, include_history=include_history)
        for document in documents
    ]
    product_identity_by_id: dict[str, dict[str, Any]] = {}
    for records in source_records:
        for collection_name, rows in records.items():
            for row in rows:
                if collection_name == "catalog_products":
                    product_identity_by_id[row["_id"]] = row
                    continue
                if collection_name == "price_observations":
                    operations[collection_name].append(
                        UpdateOne({"_id": row["_id"]}, {"$setOnInsert": row}, upsert=True)
                    )
                    continue
                if collection_name == "product_matches":
                    initial_status = row.pop("review_status")
                    update: dict[str, Any] = {
                        "$set": row,
                        "$setOnInsert": {"review_status": initial_status, "created_at": moment},
                    }
                    if row.get("method") == "manual":
                        update["$set"]["review_status"] = "approved"
                        update["$setOnInsert"].pop("review_status")
                    operations[collection_name].append(UpdateOne({"_id": row["_id"]}, update, upsert=True))
                    continue
                payload = {**row, "updated_at": moment}
                update = {"$set": payload, "$setOnInsert": {"created_at": moment}}
                if collection_name == "promotion_conditions":
                    payload["last_seen_at"] = moment
                if collection_name == "shipping_quotes":
                    payload["last_seen_at"] = moment
                if collection_name == "offers":
                    payload["last_seen_at"] = row.get("last_seen_at") or moment
                operations[collection_name].append(UpdateOne({"_id": row["_id"]}, update, upsert=True))

    for product_id, row in product_identity_by_id.items():
        timestamps = {
            "updated_at": moment,
            "last_seen_at": moment,
        }
        if row.get("source_identity") in {"gtin", "manual"}:
            update = {
                "$setOnInsert": {**row, "created_at": moment},
                "$max": {"last_seen_at": moment},
                "$set": {"updated_at": moment},
            }
        else:
            update = {
                "$set": {**row, **timestamps},
                "$setOnInsert": {"created_at": moment},
            }
        operations["catalog_products"].append(
            UpdateOne({"_id": product_id}, update, upsert=True)
        )

    totals: dict[str, int] = {}
    for collection_name, rows in operations.items():
        if not rows:
            totals[collection_name] = 0
            continue
        result = db[collection_name].bulk_write(rows, ordered=False)
        totals[collection_name] = result.upserted_count + result.modified_count + result.matched_count
    return totals
