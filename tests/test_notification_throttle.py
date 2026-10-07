"""Regla de throttle 5 días + excepción por nueva bajada (sin Mongo)."""

from datetime import datetime, timedelta, timezone

from retail.notification_throttle import should_send_price_notification

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)


def test_allows_first_send_without_history():
    assert should_send_price_notification(
        last_sent_at=None, last_notified_price=None, new_price=1000, now=NOW,
    )


def test_blocks_same_or_higher_price_inside_five_days():
    last = NOW - timedelta(days=2)
    assert not should_send_price_notification(
        last_sent_at=last, last_notified_price=1000, new_price=1000, now=NOW,
    )
    assert not should_send_price_notification(
        last_sent_at=last, last_notified_price=1000, new_price=1200, now=NOW,
    )


def test_allows_further_drop_inside_five_days():
    assert should_send_price_notification(
        last_sent_at=NOW - timedelta(days=1),
        last_notified_price=1000,
        new_price=999,
        now=NOW,
    )


def test_allows_again_after_exactly_five_days_even_same_price():
    assert not should_send_price_notification(
        last_sent_at=NOW - timedelta(days=5, microseconds=-1),
        last_notified_price=1000,
        new_price=1000,
        now=NOW,
    )
    assert should_send_price_notification(
        last_sent_at=NOW - timedelta(days=5),
        last_notified_price=1000,
        new_price=1000,
        now=NOW,
    )


def test_missing_prices_inside_window_blocks():
    assert not should_send_price_notification(
        last_sent_at=NOW - timedelta(days=1),
        last_notified_price=1000,
        new_price=None,
        now=NOW,
    )
    assert not should_send_price_notification(
        last_sent_at=NOW - timedelta(days=1),
        last_notified_price=None,
        new_price=900,
        now=NOW,
    )
