"""Regresiones con Mongo real: ejecutar con mongod instalado (base temporal)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from retail.mongo import ProductRepository


NOW = datetime(2026, 9, 27, 12, tzinfo=timezone.utc)


@pytest.fixture
def repo(mongo_uri, monkeypatch):
    repository = ProductRepository(mongo_uri, database=f"test_notifications_{uuid4().hex}")
    monkeypatch.setattr("retail.mongo._now", lambda: NOW)
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_same_product_price_expires_after_exactly_five_days(repo, monkeypatch):
    assert repo.claim_user_notification_send("u1", "email", "product:lider:p1", 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5, microseconds=-1))
    assert not repo.claim_user_notification_send("u1", "email", "product:lider:p1", 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5))
    assert repo.claim_user_notification_send("u1", "email", "product:lider:p1", 1000)
    assert not repo.claim_user_notification_send("u1", "email", "product:lider:p1", 1000)


def test_price_round_trip_keeps_each_prices_original_expiration(repo, monkeypatch):
    assert repo.claim_user_notification_send("u1", "telegram", "tv", 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=1))
    assert repo.claim_user_notification_send("u1", "telegram", "tv", 1200)
    assert not repo.claim_user_notification_send("u1", "telegram", "tv", 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5))
    assert repo.claim_user_notification_send("u1", "telegram", "tv", 1000)
    assert not repo.claim_user_notification_send("u1", "telegram", "tv", 1200)
    history = repo.user_notification_sends.find_one()["recent_sends"]
    assert len(history) == 2


def test_other_prices_products_users_and_channels_are_independent(repo):
    assert repo.claim_user_notification_send("u1", "email", "tv", 1000)
    assert repo.claim_user_notification_send("u1", "email", "tv", 999)
    assert repo.claim_user_notification_send("u1", "email", "tv", 1100)
    assert repo.claim_user_notification_send("u1", "email", "phone", 1000)
    assert repo.claim_user_notification_send("u2", "email", "tv", 1000)
    assert repo.claim_user_notification_send("u1", "push", "tv", 1000)
    assert not repo.claim_user_notification_send("u1", "email", "tv", 1000)


def test_existing_last_price_survives_first_send_at_another_price(repo, monkeypatch):
    repo.user_notification_sends.insert_one({
        "user_id": "u1", "channel": "email", "entity_key": "tv",
        "last_price": 1000, "last_sent_at": NOW - timedelta(days=4),
    })
    assert not repo.claim_user_notification_send("u1", "email", "tv", 1000)
    assert repo.claim_user_notification_send("u1", "email", "tv", 1200)
    assert not repo.claim_user_notification_send("u1", "email", "tv", 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=1))
    assert repo.claim_user_notification_send("u1", "email", "tv", 1000)


@pytest.mark.parametrize("existing", [False, True])
def test_simultaneous_workers_only_claim_once(repo, existing):
    if existing:
        repo.user_notification_sends.insert_one({
            "user_id": "u1", "channel": "email", "entity_key": "tv",
            "last_price": 1000, "last_sent_at": NOW - timedelta(days=6),
        })
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(
            lambda _: repo.claim_user_notification_send("u1", "email", "tv", 1000), range(16),
        ))
    assert sum(outcomes) == 1


def test_price_changes_ignore_previous_price_and_share_offer_history(repo):
    repo.collection.insert_one({"store": "lider", "product_id": "p1", "compare_code": "tv"})
    assert repo.claim_price_alert_send("u1", "lider", "p1", 2000, 1000)
    assert not repo.claim_price_alert_send("u1", "lider", "p1", 1200, 1000)
    assert not repo.claim_user_notification_send("u1", "email", "tv", 1000)
    assert repo.claim_user_notification_send("u1", "telegram", "tv", 900)
    assert not repo.claim_price_alert_send("u1", "lider", "p1", 1000, 900, channel="telegram")


def test_legacy_price_change_sends_block_any_previous_price_for_five_days(repo, monkeypatch):
    repo.price_alert_sends.insert_one({
        "user_id": "u1", "store": "lider", "product_id": "p1",
        "previous_price": 2000, "price": 1000, "created_at": NOW - timedelta(days=4),
    })
    assert not repo.claim_price_alert_send("u1", "lider", "p1", 1200, 1000)
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=1))
    assert repo.claim_price_alert_send("u1", "lider", "p1", 2000, 1000)


def test_global_email_and_each_webhook_use_same_price_history(repo, monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    deliveries = []
    monkeypatch.setattr(alerts, "_email", lambda payload: deliveries.append("email") or True)
    monkeypatch.setattr(alerts, "_telegram", lambda payload: deliveries.append("telegram") or True)
    monkeypatch.setattr(alerts, "_webhook_targets", lambda: ["https://one.example", "https://two.example"])
    monkeypatch.setattr(alerts, "_post_webhook", lambda url, payload: deliveries.append(url))
    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV", store="lider",
        price=1000, previous_price=2000, message="50%", url=None, compare_code="tv",
        extra={"percent": 50, "product_id": "p1"},
    )
    channels = ["email", "telegram", "webhook"]
    assert len(alerts.dispatch_alerts([deal], channels, repo=repo)) == 4
    assert alerts.dispatch_alerts([deal], channels, repo=repo) == []
    assert len(deliveries) == 4
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5))
    assert len(alerts.dispatch_alerts([deal], channels, repo=repo)) == 4


def test_price_change_and_offer_do_not_send_duplicate_email(repo, monkeypatch):
    from retail.batch import alerts
    from retail.batch.rules import Alert
    from retail.price_alerts import notify_price_changes

    deliveries = []
    user = {"id": "u1", "email": "ana@example.com", "notification_preferences": {
        "channels": ["email"], "kinds": ["common"],
    }}
    repo.collection.insert_one({"store": "lider", "product_id": "p1", "compare_code": "tv"})
    repo.price_alerts.insert_one({"user_id": "u1", "store": "lider", "product_id": "p1", "active": True})
    monkeypatch.setattr(repo, "find_user_by_id", lambda _: user)
    send_email = lambda *args, **kwargs: deliveries.append(args) or True
    monkeypatch.setattr("retail.price_alerts.send_email", send_email)
    monkeypatch.setattr(alerts, "send_email", send_email)
    monkeypatch.setattr(alerts, "_webhook_targets", lambda: [])
    monkeypatch.setattr(alerts, "send_to_user", lambda *args, **kwargs: False)
    change = {"store": "lider", "product_id": "p1", "name": "TV", "previous_price": 2000, "price": 1000}
    assert notify_price_changes(repo, [change]) == 1
    assert notify_price_changes(repo, [{**change, "previous_price": 1200}]) == 0
    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV", store="lider",
        price=1000, previous_price=2000, message="50%", url=None, compare_code="tv",
        extra={"percent": 50, "product_id": "p1"},
    )
    assert alerts.dispatch_user_alerts([deal], [user], repo=repo) == 0
    assert len(deliveries) == 1


def test_webhook_deduplicates_across_subscribers_and_global_offers(repo):
    channel = "webhook:https://example.com/notifications"
    assert repo.claim_price_alert_send("u1", "lider", "p1", 2000, 1000, channel=channel)
    assert not repo.claim_price_alert_send("u2", "lider", "p1", 1200, 1000, channel=channel)
    assert not repo.claim_user_notification_send("global", channel, "product:lider:p1", 1000)
    assert repo.claim_price_alert_send("u2", "lider", "p1", 1200, 1000, channel="email")


def test_real_offers_share_history_with_batch_telegram(repo, monkeypatch, tmp_path):
    from retail.batch import alerts

    deliveries = []
    card = {"store": "lider", "product_id": "p1", "name": "TV", "price": 1000, "gap_percent": 50}
    monkeypatch.setattr(repo, "real_offers", lambda **kwargs: {"items": [card]})
    monkeypatch.setattr(alerts, "_secret", lambda *args: "token")
    monkeypatch.setattr(alerts, "destination_chats", lambda: ["99"])
    monkeypatch.setattr(alerts, "_telegram_text", lambda *args, **kwargs: deliveries.append(args) or True)
    assert repo.claim_user_notification_send("global", "telegram", "product:lider:p1", 1000)
    assert alerts.notify_real_offers(repo, title="Ofertas", state_path=tmp_path / "state.json") == 0
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5))
    assert alerts.notify_real_offers(repo, title="Ofertas", state_path=tmp_path / "state.json") == 1
    assert not repo.claim_user_notification_send("global", "telegram", "product:lider:p1", 1000)
    assert len(deliveries) == 1


def test_predictive_alerts_share_product_key_and_ignore_new_forecast_generation(repo, monkeypatch):
    from retail.batch import alerts
    from retail import predictive_alerts

    deliveries = []
    user = {"id": "u1", "email": "ana@example.com", "notification_preferences": {
        "channels": ["email"], "kinds": ["predictive"],
    }}
    repo.collection.insert_one({"store": "lider", "product_id": "p1", "price": 1000})
    forecast = {"store": "lider", "product_id": "p1", "model": "timesfm", "forecast_key": "lider:p1"}
    repo.forecasts.insert_one({**forecast, "generated_at": NOW})
    monkeypatch.setattr(repo, "list_notification_users", lambda: [user])
    monkeypatch.setattr(predictive_alerts, "predictive_validation_status", lambda _: {"enabled": True})
    monkeypatch.setattr(predictive_alerts, "anticipated_drop_validation_status", lambda _: {"enabled": False})
    monkeypatch.setattr(predictive_alerts, "predictive_message", lambda *args, **kwargs: ("buy_now", "Oferta"))
    monkeypatch.setattr(alerts, "send_email", lambda *args, **kwargs: deliveries.append(args) or True)
    assert repo.claim_user_notification_send("u1", "email", "product:lider:p1", 1000)
    assert predictive_alerts.dispatch_predictive_alerts(repo)["sent"] == 0
    monkeypatch.setattr("retail.mongo._now", lambda: NOW + timedelta(days=5))
    assert predictive_alerts.dispatch_predictive_alerts(repo)["sent"] == 1
    repo.forecasts.insert_one({**forecast, "generated_at": NOW + timedelta(days=5)})
    assert predictive_alerts.dispatch_predictive_alerts(repo)["sent"] == 0
    assert len(deliveries) == 1
