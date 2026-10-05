"""Muestreo de pares de identidad (≥80%) para auditoría admin + overrides."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Any

from retail.compare import cluster_offer_rows, identity_match_confidence
from retail.models import Product
from retail.reales import MIN_ENTITY_CONFIDENCE

SAMPLE_POOL = 400
DEFAULT_LIMIT = 20
AUDIT_COLLECTION = "identity_audit_events"


def _pair_key(left: dict[str, Any], right: dict[str, Any]) -> str:
    a = (str(left.get("store") or ""), str(left.get("product_id") or ""))
    b = (str(right.get("store") or ""), str(right.get("product_id") or ""))
    first, second = sorted([a, b])
    return f"{first[0]}:{first[1]}|{second[0]}:{second[1]}"


def _offer_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "store": row.get("store"),
        "product_id": row.get("product_id"),
        "name": row.get("name"),
        "brand": row.get("brand"),
        "price": row.get("price"),
        "url": row.get("url"),
        "entity_override": row.get("entity_override"),
        "entity_match_method": row.get("entity_match_method"),
    }


def sample_identity_pairs(
    docs: list[dict[str, Any]],
    *,
    min_confidence: float = MIN_ENTITY_CONFIDENCE,
    limit: int = DEFAULT_LIMIT,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Pares entre tiendas con confianza de identidad ≥ umbral (default 80%)."""
    if limit < 1:
        return []
    floor = max(0.0, min(1.0, float(min_confidence)))
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in cluster_offer_rows(docs):
        offers = [
            row for row in (group.get("offers") or [])
            if row.get("store") and row.get("product_id")
        ]
        if len(offers) < 2:
            continue
        products = [Product.from_dict(row) for row in offers]
        for index, left in enumerate(offers):
            for right, other in zip(offers[index + 1 :], products[index + 1 :]):
                if left.get("store") == right.get("store"):
                    continue
                confidence, method = identity_match_confidence(products[index], other)
                if confidence < floor:
                    continue
                key = _pair_key(left, right)
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({
                    "pair_id": key,
                    "confidence": round(confidence, 3),
                    "match_method": method,
                    "group_confidence": float(group.get("entity_confidence") or confidence),
                    "left": _offer_summary(left),
                    "right": _offer_summary(right),
                })
    rng = random.Random(seed)
    rng.shuffle(pairs)
    # Prioriza confianza alta pero con muestreo (no solo el top fijo).
    pairs.sort(key=lambda row: (-row["confidence"], row["pair_id"]))
    head = pairs[: max(limit * 3, limit)]
    rng.shuffle(head)
    return head[:limit]


def load_identity_audit_sample(
    repo: Any,
    *,
    min_confidence: float = MIN_ENTITY_CONFIDENCE,
    limit: int = DEFAULT_LIMIT,
    seed: int | None = None,
) -> dict[str, Any]:
    """Carga un lote reciente de avisos y devuelve pares muestreados ≥ umbral."""
    projection = {
        "store": 1,
        "product_id": 1,
        "name": 1,
        "brand": 1,
        "price": 1,
        "url": 1,
        "condition": 1,
        "entity_override": 1,
        "entity_match_method": 1,
        "entity_confidence": 1,
        "compare_code": 1,
        "specifications": 1,
        "updated_at": 1,
    }
    docs = list(
        repo.collection.find(
            {"price": {"$gt": 0}, "name": {"$nin": [None, ""]}},
            projection,
        )
        .sort("updated_at", -1)
        .limit(SAMPLE_POOL)
    )
    pairs = sample_identity_pairs(
        docs,
        min_confidence=min_confidence,
        limit=limit,
        seed=seed,
    )
    return {
        "min_confidence": float(min_confidence),
        "pool_size": len(docs),
        "count": len(pairs),
        "pairs": pairs,
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


def record_identity_audit(
    repo: Any,
    *,
    action: str,
    products: list[tuple[str, str]],
    pair_id: str | None = None,
    confidence: float | None = None,
    note: str = "",
    actor: str = "",
) -> dict[str, Any]:
    """Registra una decisión de auditoría (incorrecto / override) sin PII sensible."""
    now = datetime.now(timezone.utc)
    document = {
        "action": str(action or "").strip().lower()[:40],
        "pair_id": (pair_id or "")[:200],
        "confidence": confidence,
        "products": [
            {"store": store, "product_id": product_id}
            for store, product_id in products
        ],
        "note": str(note or "").strip()[:300],
        "actor": str(actor or "").strip()[:120],
        "created_at": now,
    }
    collection = getattr(repo, "identity_audit_events", None)
    if collection is None:
        collection = repo.db[AUDIT_COLLECTION]
        try:
            repo.identity_audit_events = collection
        except Exception:
            pass
    collection.insert_one(document)
    return {
        "ok": True,
        "action": document["action"],
        "pair_id": document["pair_id"],
        "created_at": now.isoformat(),
    }
