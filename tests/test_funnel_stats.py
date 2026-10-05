"""Funnel search→ficha→follow→alert→lnk y seguimiento sin umbral."""

from datetime import datetime, timezone

from retail.batch.rules import watch_alerts
from retail.funnel_stats import FUNNEL_STEPS, record_funnel_event, summarize_funnel_rows


def _offer(price, previous, stats):
    return {
        "name": "Galaxy S25 512GB",
        "store": "lider",
        "store_title": "Lider",
        "price": price,
        "previous_price": previous,
        "price_delta": price - previous,
        "compare_code": "id:samsung|s25|512gb",
        "price_stats": stats,
    }


def test_watch_any_change_flag_without_threshold():
    result = {
        "groups": [{
            "compare_code": "id:samsung|s25|512gb",
            "offers": [_offer(690000, 700000, {})],
        }]
    }
    watch = {
        "id": "abc",
        "query": "galaxy s25",
        "compare_code": "id:samsung|s25|512gb",
        "any_change": True,
        "last_seen_price": 700000,
    }
    alerts = watch_alerts(result, watch)
    assert len(alerts) == 1
    assert alerts[0].rule == "watch_change"
    assert alerts[0].extra.get("any_change") is True
    assert "bajó" in alerts[0].message


def test_funnel_events_have_no_pii_fields():
    rows = []
    event = record_funnel_event("search", source="web", collection=rows)
    assert event is not None
    assert event["step"] == "search"
    assert "email" not in event
    assert "ip" not in event
    assert "user_id" not in event
    assert "query" not in event
    for step in FUNNEL_STEPS:
        record_funnel_event(step, source="test", collection=rows, when=datetime(2026, 10, 5, 15, tzinfo=timezone.utc))
    summary = summarize_funnel_rows(rows, now=datetime(2026, 10, 5, 15, tzinfo=timezone.utc))
    by_step = {item["step"]: item["today"] for item in summary["steps"]}
    assert by_step["search"] >= 1
    assert by_step["link_click"] >= 1
    assert record_funnel_event("unknown", collection=rows) is None
