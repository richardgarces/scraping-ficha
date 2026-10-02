"""Estadísticas diarias de productos scrapeados / actualizados."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from retail.scrape_stats import (
    apply_scrape_hit,
    classify_write,
    record_product_writes,
    summarize_scrape_rows,
)


class _Days:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def update_one(self, filt, update, upsert=False):
        day = filt["day"]
        doc = self.docs.get(day)
        if doc is None:
            assert upsert
            doc = {"day": day, "scraped": 0, "price_updated": 0, "discount_updated": 0}
            self.docs[day] = doc
        for field, value in update["$inc"].items():
            doc[field] = int(doc.get(field) or 0) + int(value)


def test_classify_write_counts_first_sighting_as_scraped_only():
    assert classify_write(None, 10000, 12000) == {
        "scraped": True,
        "price_updated": False,
        "discount_updated": False,
    }


def test_classify_write_detects_price_and_discount_changes():
    previous = (10000, "2026-09-30", 12000)
    both = classify_write(previous, 9000, 11000)
    assert both["scraped"] is True
    assert both["price_updated"] is True
    assert both["discount_updated"] is True

    price_only = classify_write(previous, 9500, 12000)
    assert price_only["price_updated"] is True
    assert price_only["discount_updated"] is False

    discount_only = classify_write(previous, 10000, 15000)
    assert discount_only["price_updated"] is False
    assert discount_only["discount_updated"] is True

    same = classify_write(previous, 10000, 12000)
    assert same["price_updated"] is False
    assert same["discount_updated"] is False


def test_record_product_writes_increments_day_bucket():
    buckets = _Days()
    previous = {
        ("falabella", "1"): (10000, "2026-09-30", 12000),
        ("falabella", "2"): (5000, "2026-09-30", None),
    }
    products = [
        SimpleNamespace(store="falabella", product_id="1", price=9000, price_normal=12000),
        SimpleNamespace(store="falabella", product_id="2", price=5000, price_normal=7000),
        SimpleNamespace(store="paris", product_id="9", price=3000, price_normal=3000),
    ]
    when = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    counts = record_product_writes(previous, products, when=when, collection=buckets)
    assert counts == {"scraped": 3, "price_updated": 1, "discount_updated": 1}
    day = buckets.docs["2026-10-02"]
    assert day["scraped"] == 3
    assert day["price_updated"] == 1
    assert day["discount_updated"] == 1


def test_summarize_scrape_rows_fills_window():
    now = datetime(2026, 10, 2, 18, 0, tzinfo=timezone.utc)
    rows = [
        {"day": "2026-10-02", "scraped": 10, "price_updated": 2, "discount_updated": 1},
        {"day": "2026-09-28", "scraped": 4, "price_updated": 1, "discount_updated": 0},
        {"day": "2026-09-01", "scraped": 99, "price_updated": 9, "discount_updated": 9},
    ]
    stats = summarize_scrape_rows(rows, now=now)
    assert stats["timezone"] == "America/Santiago"
    assert len(stats["by_day"]) == 30
    assert stats["by_day"][-1] == {
        "day": "2026-10-02",
        "scraped": 10,
        "price_updated": 2,
        "discount_updated": 1,
    }
    assert stats["totals"]["scraped"]["today"] == 10
    assert stats["totals"]["scraped"]["days_7"] == 14
    assert stats["totals"]["price_updated"]["days_7"] == 3
    assert stats["totals"]["discount_updated"]["today"] == 1
    # Fuera de la ventana de 30 días (hoy inclusive).
    assert stats["totals"]["scraped"]["days_30"] == 14


def test_apply_scrape_hit_skips_empty():
    buckets = _Days()
    assert apply_scrape_hit(collection=buckets) is None
    assert buckets.docs == {}


def test_stats_page_mentions_scrape_section():
    from pathlib import Path

    page = Path("retail/web/static/estadisticas.html").read_text(encoding="utf-8")
    script = Path("retail/web/static/estadisticas.js").read_text(encoding="utf-8")
    assert "Productos scrapeados" in page
    assert 'id="scrapes-body"' in page
    assert "renderScrapes" in script
    assert 'estadisticas.js?v=7' in page
