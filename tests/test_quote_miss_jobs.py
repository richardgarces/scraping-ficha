"""Scrape async on-miss para cotizaciones."""
from __future__ import annotations

from datetime import datetime, timezone

from retail.quote_miss_jobs import (
    SEARCHING_LABEL,
    apply_pending_searching,
    enqueue_miss_jobs,
)
from retail.shopping_list import _empty_cell


class _FakeColl:
    def __init__(self):
        self.docs: list[dict] = []

    def create_index(self, *args, **kwargs):
        return None

    def find_one(self, filt, projection=None):
        for doc in self.docs:
            if self._match(doc, filt):
                return {k: doc[k] for k in (projection or doc) if k in doc} if projection else doc
        return None

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return type("R", (), {"inserted_id": doc.get("_id")})()

    def find(self, filt, projection=None):
        return [doc for doc in self.docs if self._match(doc, filt)]

    @staticmethod
    def _match(doc, filt):
        for key, value in (filt or {}).items():
            if key == "created_at" and isinstance(value, dict):
                continue
            if key == "status" and isinstance(value, dict) and "$in" in value:
                if doc.get("status") not in value["$in"]:
                    return False
                continue
            if doc.get(key) != value:
                return False
        return True


class _FakeRepo:
    def __init__(self):
        self.quote_miss_jobs = _FakeColl()
        self.db = type("DB", (), {"quote_miss_jobs": self.quote_miss_jobs})()


def test_empty_cell_searching_label():
    cell = _empty_cell(reason="searching")
    assert cell["empty_reason"] == "searching"
    assert "buscando" in cell["label"].lower()


def test_enqueue_miss_jobs_marks_searching_and_dedupes():
    repo = _FakeRepo()
    quote = {
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": ""},
        ],
    }
    matches = {
        "0": {
            "jumbo": {"empty_reason": "no_catalog", "empty_label": "sin producto en catálogo"},
            "lider": {"empty_reason": "no_match", "empty_label": "sin match suficiente"},
            "alvi": {"store": "alvi", "product_id": "x", "auto": True},
        }
    }
    updated, created = enqueue_miss_jobs(repo, "q1", quote, matches)
    assert created == 2
    assert updated["0"]["jumbo"]["empty_reason"] == "searching"
    assert updated["0"]["jumbo"]["empty_label"] == SEARCHING_LABEL
    assert updated["0"]["lider"]["empty_reason"] == "searching"
    assert updated["0"]["alvi"]["product_id"] == "x"
    assert len(repo.quote_miss_jobs.docs) == 2

    again, created2 = enqueue_miss_jobs(repo, "q1", quote, matches)
    assert created2 == 0
    assert again["0"]["jumbo"]["empty_reason"] == "searching"


def test_apply_pending_searching_keeps_cells():
    repo = _FakeRepo()
    now = datetime.now(timezone.utc)
    repo.quote_miss_jobs.docs.append({
        "_id": "1",
        "quote_id": "q1",
        "line_index": 0,
        "store": "jumbo",
        "status": "pending",
        "created_at": now,
    })
    matches = {
        "0": {
            "jumbo": {"empty_reason": "no_catalog", "empty_label": "sin producto en catálogo"},
            "alvi": {"store": "alvi", "product_id": "1"},
        }
    }
    out = apply_pending_searching(repo, "q1", matches)
    assert out["0"]["jumbo"]["empty_reason"] == "searching"
    assert out["0"]["alvi"]["product_id"] == "1"
