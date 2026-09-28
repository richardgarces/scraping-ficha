from __future__ import annotations

import hashlib
import math
import os
import time
import uuid
from typing import Any

from retail.models import Product
from retail.relevance import fold

DEFAULT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "products")
QUERIES_COLLECTION = os.environ.get("QDRANT_QUERIES_COLLECTION", "search_queries")
VECTOR_SIZE = 384


def embed_text(text: str, dim: int = VECTOR_SIZE) -> list[float]:
    folded = fold(text)
    vector = [0.0] * dim
    pieces = [folded, *folded.split()]
    for raw in pieces:
        padded = f"^{raw}$"
        for size in (2, 3, 4):
            for index in range(len(padded) - size + 1):
                gram = padded[index : index + size]
                digest = hashlib.sha256(gram.encode("utf-8")).digest()
                slot = int.from_bytes(digest[:4], "little") % dim
                sign = 1.0 if digest[4] % 2 == 0 else -1.0
                vector[slot] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _point_id(store: str, product_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{store}:{product_id}"))


def connect_qdrant(url: str = DEFAULT_URL):
    try:
        from qdrant_client import QdrantClient

        client = QdrantIndex(QdrantClient(url=url, timeout=3, check_compatibility=False))
        if client.ping():
            client.ensure_collection()
            return client
    except Exception:
        return None
    return None


class QdrantIndex:
    def __init__(self, client: Any) -> None:
        self.client = client

    def ping(self) -> bool:
        try:
            self.client.get_collections()
            return True
        except Exception:
            return False

    def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        names = {item.name for item in self.client.get_collections().collections}
        if COLLECTION in names:
            return
        self.client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )

    def ensure_queries_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        names = {item.name for item in self.client.get_collections().collections}
        if QUERIES_COLLECTION in names:
            return
        self.client.create_collection(
            collection_name=QUERIES_COLLECTION,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )

    def upsert_search_query(self, query: str, *, digest: str) -> None:
        from qdrant_client.models import PointStruct

        self.ensure_queries_collection()
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"search-query:{digest}"))
        self.client.upsert(
            collection_name=QUERIES_COLLECTION,
            points=[
                PointStruct(
                    id=point_id,
                    vector=embed_text(query),
                    payload={
                        "query": query,
                        "digest": digest,
                        "stored_at": time.time(),
                    },
                )
            ],
        )

    def similar_search_queries(
        self,
        query: str,
        *,
        min_age: float,
        limit: int = 8,
    ) -> list[tuple[float, dict[str, Any]]]:
        from qdrant_client.models import FieldCondition, Filter, Range

        self.ensure_queries_collection()
        query_filter = Filter(
            must=[
                FieldCondition(key="stored_at", range=Range(gte=min_age)),
            ]
        )
        vector = embed_text(query)
        try:
            hits = self.client.query_points(
                collection_name=QUERIES_COLLECTION,
                query=vector,
                query_filter=query_filter,
                limit=limit,
            ).points
        except Exception:
            hits = self.client.search(
                collection_name=QUERIES_COLLECTION,
                query_vector=vector,
                query_filter=query_filter,
                limit=limit,
            )
        return [(float(hit.score or 0.0), dict(hit.payload or {})) for hit in hits]

    def upsert_products(self, products: list[Product], query: str | None = None) -> int:
        from qdrant_client.models import PointStruct

        points = []
        for product in products:
            if not product.product_id:
                continue
            specs = " ".join(
                f"{key} {value}" for key, value in (product.specifications or {}).items()
            )
            text = " ".join(
                str(part) for part in (
                    product.name,
                    product.brand,
                    product.sku_id,
                    product.catalog_category,
                    product.category,
                    product.category_id,
                    specs,
                    product.condition,
                    query,
                ) if part
            )
            points.append(
                PointStruct(
                    id=_point_id(product.store, product.product_id),
                    vector=embed_text(text),
                    payload={
                        "store": product.store,
                        "product_id": product.product_id,
                        "sku_id": product.sku_id,
                        "name": product.name,
                        "brand": product.brand,
                        "category": product.category,
                        "category_id": product.category_id,
                        "catalog_category": product.catalog_category,
                        "price": product.price,
                        "url": product.url,
                        "image_url": product.image_url,
                        "source": product.source,
                        "scraped_at": product.scraped_at,
                        "last_search_query": query,
                        "condition": product.condition,
                        "specifications": product.specifications,
                        "price_all_payment": product.price_all_payment,
                        "price_card": product.price_card,
                        "payment_card_name": product.payment_card_name,
                        "installment_count": product.installment_count,
                        "installment_total": product.installment_total,
                        "financial_cae": product.financial_cae,
                        "payment_conditions": product.payment_conditions,
                        "shipping_cost": product.shipping_cost,
                        "shipping_free_threshold": product.shipping_free_threshold,
                        "shipping_region": product.shipping_region,
                        "pickup_available": product.pickup_available,
                        "stock": product.stock,
                        "availability": product.availability,
                        "variants": product.variants,
                        "low_stock": product.low_stock,
                        "only_extreme_sizes": product.only_extreme_sizes,
                        "entity_id": product.entity_id,
                        "entity_confidence": product.entity_confidence,
                        "entity_override": product.entity_override,
                    },
                )
            )
        if not points:
            return 0
        self.client.upsert(collection_name=COLLECTION, points=points)
        return len(points)

    def category_candidates(
        self,
        query: str,
        *,
        limit: int = 40,
        min_score: float = 0.20,
    ) -> list[dict[str, Any]]:
        """Categorías probables de una consulta a partir de productos cercanos.

        Devuelve categorías agregadas, no productos. El puntaje máximo evita
        que una categoría con muchos ítems mediocres desplace a una coincidencia
        fuerte y ``stores`` permite traducirla rápidamente a grupos de tiendas.
        """
        vector = embed_text(query)
        try:
            hits = self.client.query_points(
                collection_name=COLLECTION,
                query=vector,
                limit=max(1, int(limit)),
                with_payload=True,
            ).points
        except Exception:
            hits = self.client.search(
                collection_name=COLLECTION,
                query_vector=vector,
                limit=max(1, int(limit)),
                with_payload=True,
            )
        aggregated: dict[str, dict[str, Any]] = {}
        for hit in hits:
            score = float(hit.score or 0.0)
            if score < float(min_score):
                continue
            payload = dict(hit.payload or {})
            labels = []
            for field in ("catalog_category", "category"):
                label = str(payload.get(field) or "").strip()
                if label and label.casefold() not in {item.casefold() for item in labels}:
                    labels.append(label)
            for label in labels:
                key = fold(label)
                if not key:
                    continue
                row = aggregated.setdefault(
                    key,
                    {"category": label, "score": score, "hits": 0, "stores": set()},
                )
                row["score"] = max(float(row["score"]), score)
                row["hits"] += 1
                store = str(payload.get("store") or "").strip().lower()
                if store:
                    row["stores"].add(store)
        rows = []
        for row in aggregated.values():
            rows.append({**row, "stores": sorted(row["stores"])})
        rows.sort(key=lambda item: (-float(item["score"]), -int(item["hits"]), fold(item["category"])))
        return rows

    def search(self, query: str, limit: int = 80) -> list[tuple[Product, float]]:
        vector = embed_text(query)
        try:
            hits = self.client.query_points(collection_name=COLLECTION, query=vector, limit=limit).points
        except Exception:
            hits = self.client.search(collection_name=COLLECTION, query_vector=vector, limit=limit)
        results: list[tuple[Product, float]] = []
        for hit in hits:
            payload = dict(hit.payload or {})
            payload.setdefault("product_id", "")
            payload.setdefault("sku_id", "")
            payload.setdefault("name", "")
            results.append((Product.from_dict(payload), float(hit.score or 0.0)))
        return results

    def scores_for(self, query: str, products: list[Product]) -> dict[tuple[str, str], float]:
        found = { (product.store, product.product_id or product.name): score for product, score in self.search(query) }
        extra: dict[tuple[str, str], float] = {}
        query_vector = embed_text(query)
        for product in products:
            key = (product.store, product.product_id or product.name)
            if key in found:
                extra[key] = found[key]
                continue
            specs = " ".join(f"{key} {value}" for key, value in (product.specifications or {}).items())
            text = " ".join(str(part) for part in (product.name, product.brand, product.sku_id, specs, product.condition) if part)
            extra[key] = _cosine(query_vector, embed_text(text))
        return extra


def _cosine(left: list[float], right: list[float]) -> float:
    return float(sum(a * b for a, b in zip(left, right)))
