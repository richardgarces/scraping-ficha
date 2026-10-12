"""Persistent, independently reviewed audits of search-to-offer matching."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId

from retail.search_stats import is_legacy_user_search

LABELS = ("exact", "variant", "not_equivalent", "uncertain")
FREQUENCY_BUCKETS = ("low", "medium", "high")
SEARCH_WINDOW_DAYS = 30
SEARCH_SAMPLE_SIZE = 300
OFFERS_PER_SEARCH = 3
MATCHING_AUDIT_SETTING_KEY = "matching_audit"


def matching_audit_status(repo: Any) -> dict[str, Any]:
    if repo is None or not hasattr(repo, "get_app_setting"):
        raise RuntimeError("MongoDB no está disponible para consultar la auditoría.")
    setting = repo.get_app_setting(MATCHING_AUDIT_SETTING_KEY) or {}
    return {
        "enabled": setting.get("enabled") is True,
        "source": "database" if "enabled" in setting else "default",
    }


def save_matching_audit_enabled(enabled: bool, repo: Any) -> dict[str, Any]:
    if not isinstance(enabled, bool):
        raise ValueError("Indica si la auditoría de matching queda activada.")
    if repo is None or not hasattr(repo, "save_app_setting"):
        raise RuntimeError("MongoDB no está disponible para guardar la auditoría.")
    repo.save_app_setting(MATCHING_AUDIT_SETTING_KEY, {"enabled": enabled})
    return {"enabled": enabled, "source": "database"}


def _object_id(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError) as exc:
        raise ValueError("Identificador de auditoría inválido.") from exc


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def frequency_buckets(counts: dict[str, int]) -> dict[str, str]:
    """Place tied frequencies in the same tercile; ties may leave a bucket empty."""
    if not counts:
        return {}
    ordered = sorted(counts.values())
    low_cut = ordered[max(0, (len(ordered) + 2) // 3 - 1)]
    high_cut = ordered[max(0, (2 * len(ordered) + 2) // 3 - 1)]
    return {
        query: "low" if count <= low_cut else "medium" if count <= high_cut else "high"
        for query, count in counts.items()
    }


def _primary_value(values: list[str], fallback: str) -> str:
    counts = Counter(value for value in values if value)
    if not counts:
        return fallback
    highest = max(counts.values())
    return next(value for value in values if value and counts[value] == highest)


def _stratified_queries(
    candidates: list[dict[str, Any]], sample_size: int, rng: random.Random
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    strata: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        key = "|".join((
            str(candidate["category"]),
            str(candidate["store"]),
            str(candidate["frequency_bucket"]),
        ))
        strata[key].append(candidate)

    target = min(max(0, int(sample_size)), len(candidates))
    if target == 0:
        return [], {}
    allocations: dict[str, int] = {}
    remainders: list[tuple[float, str]] = []
    for key, rows in strata.items():
        exact = target * len(rows) / len(candidates)
        allocations[key] = int(exact)
        remainders.append((exact - allocations[key], key))
    remaining = target - sum(allocations.values())
    for _fraction, key in sorted(remainders, key=lambda item: (-item[0], item[1]))[:remaining]:
        allocations[key] += 1

    selected: list[dict[str, Any]] = []
    for key in sorted(strata):
        rows = strata[key]
        selected.extend(rng.sample(rows, allocations[key]))
    rng.shuffle(selected)
    return selected, {key: value for key, value in allocations.items() if value}


def _offer_snapshot(product: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "store", "product_id", "sku_id", "name", "brand", "url",
        "catalog_category", "category", "price", "price_normal",
        "price_all_payment", "price_card", "price_coupon", "coupon_code",
        "payment_card_name", "payment_conditions", "condition",
        "shipping_cost", "shipping_free_threshold", "shipping_region",
        "stock", "stock_verified", "availability", "updated_at",
    )
    return {key: product.get(key) for key in fields if key in product}


def _load_search_candidates(
    repo: Any, *, cutoff: datetime
) -> tuple[list[dict[str, Any]], int]:
    events = repo.searches.find(
        {"created_at": {"$gte": cutoff}, "relation_status": "complete"},
        {
            "_id": 1, "query": 1, "query_normalized": 1, "created_at": 1,
            "background": 1, "last_batch_run": 1, "batch_grupo": 1,
            "batch_tienda": 1, "catalog_id": 1, "watch_query": 1,
            "basic_scrape": 1,
        },
    ).sort("created_at", -1)

    latest: dict[str, dict[str, Any]] = {}
    frequencies: Counter[str] = Counter()
    for event in events:
        if not is_legacy_user_search(event):
            continue
        query = " ".join(str(event.get("query") or "").split()).strip()
        normalized = str(event.get("query_normalized") or "").strip().casefold()
        if not query or not normalized:
            continue
        frequencies[normalized] += 1
        latest.setdefault(normalized, {**event, "query": query, "normalized": normalized})

    buckets = frequency_buckets(dict(frequencies))
    search_ids = [event["_id"] for event in latest.values()]
    if not search_ids:
        return [], 0

    relations: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    cursor = repo.search_results.find(
        {"search_id": {"$in": search_ids}},
        {"search_id": 1, "product_id": 1, "position": 1},
    ).sort([("search_id", 1), ("position", 1)])
    for relation in cursor:
        offers = relations[relation["search_id"]]
        if len(offers) < OFFERS_PER_SEARCH:
            offers.append(relation)

    product_ids = {
        relation["product_id"]
        for offers in relations.values()
        for relation in offers
        if relation.get("product_id") is not None
    }
    products = {
        row["_id"]: row
        for row in repo.collection.find(
            {"_id": {"$in": list(product_ids)}},
            {
                "store": 1, "product_id": 1, "sku_id": 1, "name": 1,
                "brand": 1, "url": 1, "catalog_category": 1, "category": 1,
                "price": 1, "price_normal": 1, "price_all_payment": 1,
                "price_card": 1, "price_coupon": 1, "coupon_code": 1,
                "payment_card_name": 1, "payment_conditions": 1,
                "condition": 1, "shipping_cost": 1,
                "shipping_free_threshold": 1, "shipping_region": 1,
                "stock": 1, "stock_verified": 1, "availability": 1,
                "updated_at": 1,
            },
        )
    }

    candidates: list[dict[str, Any]] = []
    for normalized, event in latest.items():
        found = []
        seen_products: set[Any] = set()
        for relation in relations.get(event["_id"], []):
            product = products.get(relation.get("product_id"))
            if not product or not product.get("store") or not product.get("product_id"):
                continue
            if product["_id"] in seen_products:
                continue
            seen_products.add(product["_id"])
            found.append({
                "position": int(relation.get("position") or 0),
                "offer": _offer_snapshot(product),
            })
        if not found:
            continue
        found.sort(key=lambda row: row["position"])
        categories = [
            str(row["offer"].get("catalog_category") or row["offer"].get("category") or "").strip()
            for row in found
        ]
        stores = [str(row["offer"].get("store") or "").strip().lower() for row in found]
        candidates.append({
            "search_id": event["_id"],
            "query": event["query"],
            "query_normalized": normalized,
            "search_created_at": _utc(event.get("created_at")),
            "frequency_count": frequencies[normalized],
            "frequency_bucket": buckets[normalized],
            "category": _primary_value(categories, "sin-categoria"),
            "store": _primary_value(stores, "sin-tienda"),
            "offers": found[:OFFERS_PER_SEARCH],
        })
    return candidates, len(frequencies)


def create_matching_audit_run(
    repo: Any,
    *,
    created_by: str,
    seed: int | None = None,
    search_count: int = SEARCH_SAMPLE_SIZE,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Freeze a stratified query/offer sample and persist its audit run."""
    moment = _utc(now) or datetime.now(timezone.utc)
    random_seed = int(seed if seed is not None else random.SystemRandom().getrandbits(63))
    requested_search_count = min(SEARCH_SAMPLE_SIZE, max(1, int(search_count)))
    rng = random.Random(random_seed)
    run = {
        "created_at": moment,
        "created_by": str(created_by or "")[:160],
        "search_window_days": SEARCH_WINDOW_DAYS,
        "search_count_requested": requested_search_count,
        "seed": random_seed,
        "status": "building",
        "strata": {},
    }
    run_id = repo.matching_audit_runs.insert_one(run).inserted_id
    try:
        candidates, recent_query_count = _load_search_candidates(
            repo,
            cutoff=moment - timedelta(days=SEARCH_WINDOW_DAYS),
        )
        selected, strata = _stratified_queries(
            candidates,
            requested_search_count,
            rng,
        )
        items = []
        for candidate in selected:
            for offer in candidate["offers"]:
                snapshot = offer["offer"]
                items.append({
                    "run_id": run_id,
                    "search_id": candidate["search_id"],
                    "product_id": snapshot.get("product_id"),
                    "query": candidate["query"],
                    "query_normalized": candidate["query_normalized"],
                    "search_created_at": candidate["search_created_at"],
                    "category": candidate["category"],
                    "store": snapshot.get("store") or candidate["store"],
                    "frequency_count_30d": candidate["frequency_count"],
                    "frequency_bucket": candidate["frequency_bucket"],
                    "position": offer["position"],
                    "offer": snapshot,
                    "reviewer_ids": [],
                    "status": "awaiting_reviews",
                    "created_at": moment,
                })
        if items:
            repo.matching_audit_items.insert_many(items, ordered=False)
        run_update = {
            "status": "open" if items else "empty",
            "completed_build_at": datetime.now(timezone.utc),
            "recent_query_count": recent_query_count,
            "eligible_query_count": len(candidates),
            "queries_with_results": len(candidates),
            "sampled_search_count": len(selected),
            "comparison_count": len(items),
            "strata_allocations": strata,
        }
        repo.matching_audit_runs.update_one({"_id": run_id}, {"$set": run_update})
        return {"run_id": str(run_id), **run, **run_update}
    except Exception as exc:
        repo.matching_audit_runs.update_one(
            {"_id": run_id},
            {"$set": {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}"[:500],
                "completed_build_at": datetime.now(timezone.utc),
            }},
        )
        raise


def _valid_label(label: str) -> str:
    clean = str(label or "").strip().lower()
    if clean not in LABELS:
        raise ValueError("Etiqueta inválida.")
    return clean


def _find_audit_item(repo: Any, run_id: str | ObjectId, item_id: str | ObjectId) -> dict[str, Any]:
    run_oid = _object_id(run_id)
    item_oid = _object_id(item_id)
    item = repo.matching_audit_items.find_one({"_id": item_oid, "run_id": run_oid})
    if not item:
        raise LookupError("Comparación no encontrada en esta auditoría.")
    return item


def record_matching_review(
    repo: Any,
    *,
    run_id: str | ObjectId,
    item_id: str | ObjectId,
    reviewer_id: str,
    label: str,
    note: str = "",
) -> dict[str, Any]:
    """Reserve one of exactly two independent reviewer slots and save a label."""
    from pymongo.errors import DuplicateKeyError

    run_oid = _object_id(run_id)
    item = _find_audit_item(repo, run_oid, item_id)
    reviewer = str(reviewer_id or "").strip()[:160]
    if not reviewer:
        raise ValueError("No se pudo identificar al revisor.")
    clean_label = _valid_label(label)
    if repo.matching_audit_reviews.find_one({
        "run_id": run_oid, "item_id": item["_id"], "reviewer_id": reviewer,
    }):
        raise ValueError("Ya registraste una etiqueta para esta comparación.")

    reservation = repo.matching_audit_items.update_one(
        {
            "_id": item["_id"],
            "status": {"$nin": ["agreed", "arbitrated"]},
            "reviewer_ids": {"$ne": reviewer},
            "$expr": {"$lt": [{"$size": {"$ifNull": ["$reviewer_ids", []]}}, 2]},
        },
        {"$addToSet": {"reviewer_ids": reviewer}},
    )
    if reservation.matched_count != 1:
        raise ValueError("La comparación ya tiene dos revisores o está resuelta.")
    review = {
        "run_id": run_oid,
        "item_id": item["_id"],
        "reviewer_id": reviewer,
        "label": clean_label,
        "note": str(note or "").strip()[:500],
        "created_at": datetime.now(timezone.utc),
    }
    try:
        repo.matching_audit_reviews.insert_one(review)
    except Exception as exc:
        repo.matching_audit_items.update_one(
            {"_id": item["_id"]}, {"$pull": {"reviewer_ids": reviewer}}
        )
        if isinstance(exc, DuplicateKeyError):
            raise ValueError("Ya registraste una etiqueta para esta comparación.") from None
        raise

    reviews = list(repo.matching_audit_reviews.find(
        {"run_id": run_oid, "item_id": item["_id"]},
    ).sort("created_at", 1))
    update: dict[str, Any]
    if len(reviews) < 2:
        update = {"status": "awaiting_second_review"}
    elif reviews[0]["label"] == reviews[1]["label"]:
        update = {
            "status": "agreed",
            "final_label": reviews[0]["label"],
            "resolved_at": datetime.now(timezone.utc),
        }
    else:
        update = {"status": "disagreement"}
    repo.matching_audit_items.update_one(
        {
            "_id": item["_id"],
            "$expr": {"$eq": [{"$size": {"$ifNull": ["$reviewer_ids", []]}}, len(reviews)]},
            "status": {"$nin": ["agreed", "arbitrated"]},
        },
        {"$set": update},
    )
    return {"ok": True, "status": update["status"], "label": clean_label}


def arbitrate_matching_item(
    repo: Any,
    *,
    run_id: str | ObjectId,
    item_id: str | ObjectId,
    arbitrator_id: str,
    label: str,
    note: str = "",
) -> dict[str, Any]:
    run_oid = _object_id(run_id)
    item = _find_audit_item(repo, run_oid, item_id)
    if item.get("status") != "disagreement":
        raise ValueError("Solo se pueden arbitrar desacuerdos entre dos revisores.")
    arbitrator = str(arbitrator_id or "").strip()[:160]
    if not arbitrator or arbitrator in item.get("reviewer_ids", []):
        raise ValueError("El árbitro debe ser distinto de los dos revisores.")
    clean_label = _valid_label(label)
    now = datetime.now(timezone.utc)
    changed = repo.matching_audit_items.update_one(
        {"_id": item["_id"], "status": "disagreement"},
        {"$set": {
            "status": "arbitrated",
            "final_label": clean_label,
            "arbitrator_id": arbitrator,
            "arbitration_note": str(note or "").strip()[:500],
            "resolved_at": now,
        }},
    )
    if changed.matched_count != 1:
        raise ValueError("El desacuerdo ya fue arbitrado por otra persona.")
    return {"ok": True, "status": "arbitrated", "final_label": clean_label}


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Multiclass nominal Cohen's kappa; None when no pairs or chance is 1."""
    if len(labels_a) != len(labels_b) or not labels_a:
        return None
    if any(label not in LABELS for label in (*labels_a, *labels_b)):
        raise ValueError("Kappa recibió etiquetas fuera del esquema.")
    count = len(labels_a)
    observed = sum(left == right for left, right in zip(labels_a, labels_b)) / count
    counts_a = Counter(labels_a)
    counts_b = Counter(labels_b)
    expected = sum(counts_a[label] * counts_b[label] for label in LABELS) / (count * count)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return (observed - expected) / (1 - expected)


def matching_audit_metrics(repo: Any, run_id: str | ObjectId) -> dict[str, Any]:
    run_oid = _object_id(run_id)
    items = list(repo.matching_audit_items.find({"run_id": run_oid}))
    reviews = list(repo.matching_audit_reviews.find({"run_id": run_oid}))
    by_item: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        by_item[review["item_id"]].append(review)
    paired_reviews: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for item in items:
        pair = by_item[item["_id"]]
        if len(pair) != 2:
            continue
        ordered = sorted(pair, key=lambda row: row["reviewer_id"])
        reviewer_pair = (ordered[0]["reviewer_id"], ordered[1]["reviewer_id"])
        paired_reviews[reviewer_pair].append((ordered[0]["label"], ordered[1]["label"]))
    kappas = []
    for labels in paired_reviews.values():
        value = cohen_kappa(
            [pair[0] for pair in labels],
            [pair[1] for pair in labels],
        )
        if value is not None:
            kappas.append((value, len(labels)))
    kappa = (
        sum(value * count for value, count in kappas) / sum(count for _, count in kappas)
        if kappas else None
    )
    double_reviewed_count = sum(len(labels) for labels in paired_reviews.values())
    concluded = [
        item for item in items
        if item.get("final_label") in LABELS and item["final_label"] != "uncertain"
    ]
    exact = sum(item["final_label"] == "exact" for item in concluded)
    return {
        "run_id": str(run_oid),
        "comparison_count": len(items),
        "review_count": len(reviews),
        "double_reviewed_count": double_reviewed_count,
        "resolved_count": sum(item.get("final_label") in LABELS for item in items),
        "uncertain_count": sum(item.get("final_label") == "uncertain" for item in items),
        "exact_count": exact,
        "precision_exact": exact / len(concluded) if concluded else None,
        "precision_denominator": len(concluded),
        "cohen_kappa": kappa,
        "kappa_denominator": double_reviewed_count,
        "kappa_reviewer_pair_count": len(kappas),
        "disagreement_count": sum(item.get("status") == "disagreement" for item in items),
    }


def matching_audit_csv_rows(repo: Any, run_id: str | ObjectId) -> list[dict[str, Any]]:
    run_oid = _object_id(run_id)
    items = list(repo.matching_audit_items.find({"run_id": run_oid}).sort(
        [("category", 1), ("store", 1), ("query_normalized", 1), ("position", 1)]
    ))
    reviews = list(repo.matching_audit_reviews.find({"run_id": run_oid}))
    by_item: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        by_item[review["item_id"]].append(review)
    rows = []
    for item in items:
        labels_by_reviewer = {
            review["reviewer_id"]: review
            for review in by_item[item["_id"]]
        }
        reviewers = sorted(labels_by_reviewer)
        first = labels_by_reviewer[reviewers[0]] if reviewers else {}
        second = labels_by_reviewer[reviewers[1]] if len(reviewers) > 1 else {}
        offer = item.get("offer") or {}
        rows.append({
            "search_id": str(item.get("search_id") or ""),
            "query": item.get("query") or "",
            "category": item.get("category") or "",
            "store": item.get("store") or "",
            "frequency_count_30d": item.get("frequency_count_30d", ""),
            "frequency_bucket": item.get("frequency_bucket") or "",
            "offer_id": offer.get("product_id") or "",
            "offer_name": offer.get("name") or "",
            "offer_url": offer.get("url") or "",
            "offer_price_all_payment": offer.get("price_all_payment", ""),
            "offer_price_card": offer.get("price_card", ""),
            "offer_payment_conditions": offer.get("payment_conditions") or "",
            "offer_shipping_cost": offer.get("shipping_cost", ""),
            "offer_updated_at": offer.get("updated_at", ""),
            "reviewer_1": first.get("reviewer_id", ""),
            "label_1": first.get("label", ""),
            "note_1": first.get("note", ""),
            "reviewer_2": second.get("reviewer_id", ""),
            "label_2": second.get("label", ""),
            "note_2": second.get("note", ""),
            "final_label": item.get("final_label", ""),
            "arbitrator": item.get("arbitrator_id", ""),
            "arbitration_note": item.get("arbitration_note", ""),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea una muestra estratificada de auditoría de matching.")
    parser.add_argument("--seed", type=int, help="Semilla opcional para reproducir la selección.")
    parser.add_argument("--search-count", type=int, default=SEARCH_SAMPLE_SIZE)
    args = parser.parse_args(argv)
    if not 1 <= args.search_count <= SEARCH_SAMPLE_SIZE:
        parser.error(f"--search-count debe estar entre 1 y {SEARCH_SAMPLE_SIZE}.")

    from retail.mongo import ProductRepository

    with ProductRepository() as repo:
        if not matching_audit_status(repo)["enabled"]:
            parser.error("La auditoría está desactivada; habilítala en Configurar.")
        result = create_matching_audit_run(
            repo,
            created_by="cli",
            seed=args.seed,
            search_count=args.search_count,
        )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
