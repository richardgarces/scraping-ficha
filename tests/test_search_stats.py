"""Búsquedas de la web: no mezclar el cron y no duplicar el log nuevo."""

from datetime import datetime, timezone

from retail.search_stats import (
    is_legacy_user_search,
    merge_search_rows,
    record_app_search,
    summarize_search_rows,
)


class _Inserts:
    def __init__(self):
        self.docs = []

    def insert_one(self, document):
        self.docs.append(document)


def test_web_log_keeps_query_and_origin_without_batch_fields():
    store = _Inserts()
    when = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    saved = record_app_search("Televisor 50", "203.0.113.8", "cl", when=when, collection=store)
    assert saved["query"] == "Televisor 50"
    assert saved["folded"] == "televisor 50"
    assert saved["ip"] == "203.0.113.8"
    assert saved["country"] == "CL"
    assert saved["origin"] == "web"
    assert "batch" not in saved
    assert record_app_search("  ", collection=store) is None
    assert len(store.docs) == 1


def test_legacy_user_search_drops_cron_and_background():
    assert is_legacy_user_search({"query": "leche"})
    assert not is_legacy_user_search({"query": "leche", "background": True})
    assert not is_legacy_user_search({"query": "leche", "last_batch_run": "abc"})
    assert not is_legacy_user_search({"query": "leche", "basic_scrape": True})
    assert not is_legacy_user_search({"query": "  "})


def test_merge_uses_legacy_only_before_the_web_log():
    cutoff = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    legacy = [
        {"query": "antes", "created_at": datetime(2026, 9, 16, 11, 0, tzinfo=timezone.utc)},
        {"query": "despues", "created_at": datetime(2026, 9, 16, 12, 5, tzinfo=timezone.utc)},
        {"query": "cron", "created_at": datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc), "batch_grupo": "super"},
    ]
    web = [{"query": "despues", "created_at": cutoff, "folded": "despues"}]
    merged = merge_search_rows(legacy, web)
    assert [row["query"] for row in merged] == ["despues", "antes"]


def test_summarize_counts_windows_and_top_queries_in_santiago():
    now = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    rows = [
        {"query": "Leche", "folded": "leche", "created_at": datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)},
        {"query": "leche", "created_at": datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)},
        {"query": "Pan", "created_at": datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)},
        # 02:30 UTC es todavía el 15 en Santiago: no cuenta como hoy.
        {"query": "Arroz", "created_at": datetime(2026, 9, 16, 2, 30, tzinfo=timezone.utc)},
        {"query": "cron", "created_at": datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc), "last_batch_run": "x"},
    ]
    stats = summarize_search_rows(rows, now=now)
    assert stats["timezone"] == "America/Santiago"
    assert stats["totals"]["today"] == 2
    assert stats["totals"]["days_7"] == 4
    assert stats["totals"]["days_30"] == 4
    assert stats["by_day"][-1] == {"day": "2026-09-16", "count": 2}
    assert stats["by_day"][-2]["count"] == 2
    assert stats["top"][0]["query"] == "Leche"
    assert stats["top"][0]["count"] == 2
    assert stats["top"][1]["query"] in {"Pan", "Arroz"}
    assert all(item["query"] != "cron" for item in stats["top"])
