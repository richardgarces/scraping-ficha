"""Tests del boost de prioridad para productos en Siguiendo."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


class _Cursor(list):
    def limit(self, _n: int) -> "_Cursor":
        return self


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs = list(docs or [])
        self.updates: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def find(self, query: dict[str, Any] | None = None, projection: dict | None = None):
        query = query or {}
        rows = []
        for doc in self.docs:
            if self._match(doc, query):
                rows.append(dict(doc))
        return _Cursor(rows)

    def update_one(self, filt: dict[str, Any], update: dict[str, Any], upsert: bool = False):
        self.updates.append((filt, update, upsert))
        catalog_id = filt.get("catalog_id")
        payload = dict(update.get("$set") or {})
        for index, doc in enumerate(self.docs):
            if doc.get("catalog_id") == catalog_id:
                self.docs[index] = {**doc, **payload}
                return
        if upsert:
            self.docs.append(payload)

    @staticmethod
    def _match(doc: dict[str, Any], query: dict[str, Any]) -> bool:
        if "$or" in query:
            return any(FakeCollection._match(doc, clause) for clause in query["$or"])
        for key, expected in query.items():
            if key == "$expr":
                # Ofertas del día: price_normal > price
                return int(doc.get("price_normal") or 0) > int(doc.get("price") or 0)
            if key == "updated_at" and isinstance(expected, dict):
                value = doc.get("updated_at")
                if value is None:
                    return False
                if "$gte" in expected and value < expected["$gte"]:
                    return False
                if "$lt" in expected and value >= expected["$lt"]:
                    return False
                continue
            if key == "catalog_id" and isinstance(expected, dict) and "$nin" in expected:
                if doc.get("catalog_id") in expected["$nin"]:
                    return False
                continue
            if key == "price" and isinstance(expected, dict) and "$gt" in expected:
                if not (int(doc.get("price") or 0) > expected["$gt"]):
                    return False
                continue
            if key == "active":
                if isinstance(expected, dict) and "$ne" in expected:
                    if doc.get("active", True) == expected["$ne"]:
                        return False
                elif doc.get("active") != expected:
                    return False
                continue
            if key == "status":
                if doc.get("status") != expected:
                    return False
                continue
            if doc.get(key) != expected:
                return False
        return True


class FakeRepo:
    def __init__(self) -> None:
        self.watches = FakeCollection()
        self.price_alerts = FakeCollection()
        self.collection = FakeCollection()
        self.scrape_priorities = FakeCollection()
        self.users = FakeCollection()
        self.settings: dict[str, dict[str, Any]] = {}

    def save_app_setting(self, key: str, value: dict[str, Any]) -> dict[str, Any]:
        self.settings[key] = dict(value)
        return value


def test_boost_prioritizes_price_alerts_from_approved_users():
    from retail.scrape_priority_boost import (
        WATCH_SCORE,
        boost_watched_and_offer_priorities,
        following_boost_setting_key,
    )

    repo = FakeRepo()
    repo.users.docs = [
        {"_id": "u-ok", "status": "approved"},
        {"_id": "u-pending", "status": "pending"},
    ]
    repo.price_alerts.docs = [
        {"user_id": "u-ok", "store": "lider", "product_id": "sku-1", "active": True},
        {"user_id": "u-pending", "store": "lider", "product_id": "sku-pending", "active": True},
        {"user_id": "u-ok", "store": "paris", "product_id": "sku-2", "active": False},
    ]
    repo.collection.docs = [
        {"store": "lider", "product_id": "sku-1", "catalog_id": "CAT-TV"},
        {"store": "lider", "product_id": "sku-pending", "catalog_id": "CAT-SKIP"},
    ]

    metrics = boost_watched_and_offer_priorities(repo, now=NOW)

    assert metrics["price_alerts"] == 1
    assert metrics["following_products"] == 1
    assert metrics["following_boosted"] == 1
    assert metrics["watches"] == 0
    assert len(repo.scrape_priorities.updates) == 1
    filt, update, upsert = repo.scrape_priorities.updates[0]
    assert filt == {"catalog_id": "CAT-TV"}
    assert upsert is True
    assert update["$set"]["score"] == WATCH_SCORE
    assert update["$set"]["tier"] == "high"
    assert update["$set"]["next_due_at"] == NOW
    assert update["$set"]["boost_reason"] == "siguiendo"
    key = following_boost_setting_key(NOW)
    assert key in repo.settings
    assert repo.settings[key]["following_boosted"] == 1


def test_boost_merges_watches_and_alerts_without_duplicate_catalog_writes():
    from retail.scrape_priority_boost import boost_watched_and_offer_priorities

    repo = FakeRepo()
    repo.users.docs = [{"_id": "u1", "status": "approved"}]
    repo.watches.docs = [
        {
            "user_id": "u1",
            "store": "hites",
            "product_id": "111",
            "catalog_id": "CAT-SAME",
            "active": True,
        }
    ]
    repo.price_alerts.docs = [
        {"user_id": "u1", "store": "hites", "product_id": "111", "active": True},
        {"user_id": "u1", "store": "hites", "product_id": "222", "active": True},
    ]
    repo.collection.docs = [
        {"store": "hites", "product_id": "111", "catalog_id": "CAT-SAME"},
        {"store": "hites", "product_id": "222", "catalog_id": "CAT-SAME"},
    ]

    metrics = boost_watched_and_offer_priorities(repo, now=NOW, persist_metrics=False)

    assert metrics["watches"] == 1
    assert metrics["price_alerts"] == 2
    assert metrics["following_products"] == 2
    assert metrics["following_boosted"] == 1
    assert metrics["catalogs"] == 1
    assert len(repo.scrape_priorities.updates) == 1


def test_boost_is_idempotent_on_second_run():
    from retail.scrape_priority_boost import boost_watched_and_offer_priorities

    repo = FakeRepo()
    repo.users.docs = [{"_id": "u1", "status": "approved"}]
    repo.price_alerts.docs = [
        {"user_id": "u1", "store": "lider", "product_id": "a", "active": True},
    ]
    repo.collection.docs = [
        {"store": "lider", "product_id": "a", "catalog_id": "CAT-A"},
    ]

    first = boost_watched_and_offer_priorities(repo, now=NOW, persist_metrics=False)
    second = boost_watched_and_offer_priorities(repo, now=NOW, persist_metrics=False)

    assert first["following_boosted"] == second["following_boosted"] == 1
    assert len(repo.scrape_priorities.docs) == 1
    assert repo.scrape_priorities.docs[0]["catalog_id"] == "CAT-A"


def test_following_beats_generic_offer_candidate_score():
    from retail.scrape_priority_boost import (
        OFFER_CANDIDATE_SCORE,
        WATCH_SCORE,
        boost_watched_and_offer_priorities,
    )

    repo = FakeRepo()
    repo.users.docs = [{"_id": "u1", "status": "approved"}]
    repo.price_alerts.docs = [
        {"user_id": "u1", "store": "lider", "product_id": "followed", "active": True},
    ]
    repo.collection.docs = [
        {
            "store": "lider",
            "product_id": "followed",
            "catalog_id": "CAT-FOLLOW",
            "price": 1000,
            "price_normal": 2000,
            "updated_at": NOW,
        },
        {
            "store": "paris",
            "product_id": "offer-only",
            "catalog_id": "CAT-OFFER",
            "price": 5000,
            "price_normal": 9000,
            "updated_at": NOW,
        },
    ]

    metrics = boost_watched_and_offer_priorities(repo, now=NOW, persist_metrics=False)
    by_id = {doc["catalog_id"]: doc for doc in repo.scrape_priorities.docs}

    assert by_id["CAT-FOLLOW"]["score"] == WATCH_SCORE
    assert by_id["CAT-OFFER"]["score"] == OFFER_CANDIDATE_SCORE
    assert metrics["following_boosted"] == 1
    assert metrics["offer_boosted"] == 1
