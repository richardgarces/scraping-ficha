"""Lista Cyber alertas_usuarios: sync, dedupe, notify y process_one por ancla."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CyberDayError,
    delete_list,
    ensure_default_list,
    import_products,
    list_all_lists,
    process_one,
    product_row_view,
    start_run,
    update_item,
)
from retail.user_alert_list import (
    USER_ALERTS_LIST_ID,
    add_user_alert,
    alert_key_for_product,
    backfill_from_price_alerts,
    collect_user_alert_matches,
    ensure_user_alerts_list,
    is_user_alerts_list,
    notify_user_alert_change,
    remove_user_alert,
    user_can_activate_alert,
)


NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(mongo_uri, monkeypatch):
    from retail.mongo import ProductRepository

    repository = ProductRepository(mongo_uri, database=f"test_ual_{uuid4().hex}")
    monkeypatch.setattr("retail.cyber_day._now", lambda: NOW)
    monkeypatch.setattr("retail.user_alert_list._now", lambda: NOW)
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_ensure_bootstrap_and_system_flags(repo):
    ensure_default_list(repo)
    meta = ensure_user_alerts_list(repo)
    assert meta["slug"] == USER_ALERTS_LIST_ID
    slugs = {row["slug"] for row in list_all_lists(repo)}
    assert USER_ALERTS_LIST_ID in slugs
    row = next(r for r in list_all_lists(repo) if r["slug"] == USER_ALERTS_LIST_ID)
    assert row["system"] is True
    assert row["is_user_alert"] is True
    assert is_user_alerts_list(USER_ALERTS_LIST_ID)


def test_delete_and_import_blocked(repo):
    ensure_user_alerts_list(repo)
    with pytest.raises(CyberDayError, match="sistema"):
        delete_list(repo, USER_ALERTS_LIST_ID)
    with pytest.raises(CyberDayError, match="import destructivo"):
        import_products(
            repo,
            [{"n": 1, "query": "TV", "category": "x", "order": 0}],
            list_id=USER_ALERTS_LIST_ID,
        )


def test_sync_two_users_one_row_and_last_leave_deletes(repo):
    ensure_user_alerts_list(repo)
    doc = {
        "name": "iPhone 15",
        "compare_code": "CMP-IPHONE-15",
        "category": "Celulares",
        "store": "falabella",
        "product_id": "sku-a",
    }
    u1 = {"id": "u1", "email": "a@example.com", "name": "Ana"}
    u2 = {"id": "u2", "email": "b@example.com", "name": "Bob"}
    r1 = add_user_alert(repo, u1, store="falabella", product_id="sku-a", document=doc)
    assert r1["ok"] and r1["created"] and r1["watcher_count"] == 1
    r2 = add_user_alert(
        repo,
        u2,
        store="ripley",
        product_id="sku-b",
        document={**doc, "store": "ripley", "product_id": "sku-b"},
    )
    assert r2["ok"] and not r2.get("created")
    assert r2["watcher_count"] == 2
    assert r2["alert_key"] == "CMP-IPHONE-15"

    coll = repo.cyber_day_products
    rows = list(coll.find({"list_id": USER_ALERTS_LIST_ID}))
    assert len(rows) == 1
    assert rows[0]["first_watcher_label"] == "Ana"
    assert rows[0]["watcher_count"] == 2

    view = product_row_view({**rows[0], "id": str(rows[0]["_id"])})
    assert view["watcher_count"] == 2
    assert view["first_watcher_label"] == "Ana"
    assert view["is_user_alert"] is True

    remove_user_alert(repo, u1, store="falabella", product_id="sku-a", document=doc)
    row = coll.find_one({"list_id": USER_ALERTS_LIST_ID, "alert_key": "CMP-IPHONE-15"})
    assert row["watcher_count"] == 1
    assert row["first_watcher_label"] == "Bob"

    remove_user_alert(repo, u2, store="ripley", product_id="sku-b", document=doc)
    assert coll.count_documents({"list_id": USER_ALERTS_LIST_ID}) == 0


def test_update_user_alert_query_keeps_prices(repo):
    """Editar Query en Alertas usuarios solo cambia la etiqueta; no borra precios."""
    ensure_user_alerts_list(repo)
    doc = {
        "name": "Galaxy S25 Ultra",
        "compare_code": "CMP-S25U",
        "category": "Celulares",
        "store": "falabella",
        "product_id": "sku-s25",
    }
    add_user_alert(
        repo,
        {"id": "u1", "email": "a@example.com", "name": "Admin"},
        store="falabella",
        product_id="sku-s25",
        document=doc,
    )
    coll = repo.cyber_day_products
    row = coll.find_one({"list_id": USER_ALERTS_LIST_ID, "alert_key": "CMP-S25U"})
    assert row is not None
    coll.update_one(
        {"_id": row["_id"]},
        {
            "$set": {
                "last_price": 999990,
                "last_match_count": 3,
                "best_store": "falabella",
                "stores_scraped": 2,
                "resolved": True,
            }
        },
    )
    result = update_item(
        repo,
        int(row["n"]),
        query="Samsung Galaxy S25 Ultra 512GB",
        list_id=USER_ALERTS_LIST_ID,
    )
    assert result["message"] == "Query actualizada"
    updated = result["updated"]
    assert updated["query"] == "Samsung Galaxy S25 Ultra 512GB"
    assert updated["last_price"] == 999990
    assert updated["last_match_count"] == 3
    assert updated["best_store"] == "falabella"
    fresh = coll.find_one({"_id": row["_id"]})
    assert fresh["query"] == "Samsung Galaxy S25 Ultra 512GB"
    assert fresh["name"] == "Samsung Galaxy S25 Ultra 512GB"
    assert fresh["alert_key"] == "CMP-S25U"
    assert fresh["last_price"] == 999990


def test_dedupe_by_store_product_when_no_compare_code(repo):
    ensure_user_alerts_list(repo)
    doc = {"name": "Mouse", "store": "paris", "product_id": "m1"}
    key = alert_key_for_product(doc, store="paris", product_id="m1")
    assert key == "paris:m1"
    add_user_alert(repo, {"id": "u1", "email": "a@x.com"}, store="paris", product_id="m1", document=doc)
    again = add_user_alert(
        repo, {"id": "u1", "email": "a@x.com"}, store="paris", product_id="m1", document=doc,
    )
    assert again.get("already") is True
    assert repo.cyber_day_products.count_documents({"list_id": USER_ALERTS_LIST_ID}) == 1


def test_user_can_activate_without_email_if_push(repo):
    ok, _ = user_can_activate_alert({
        "id": "u1",
        "notification_preferences": {"channels": ["push"], "kinds": ["watch"]},
        "push_subscriptions": [{"endpoint": "https://push.example/1"}],
    })
    assert ok is True
    bad, detail = user_can_activate_alert({
        "id": "u2",
        "notification_preferences": {"channels": ["email"], "kinds": ["watch"]},
    })
    assert bad is False
    assert "correo" in detail.lower() or "canal" in detail.lower()


def test_notify_respects_channel_prefs(repo, monkeypatch):
    ensure_user_alerts_list(repo)
    item = {
        "query": "TV",
        "watchers": [
            {"user_id": "push-only", "email": "p@x.com", "display_name": "Push"},
            {"user_id": "email-only", "email": "e@x.com", "display_name": "Mail"},
            {"user_id": "no-channels", "email": "n@x.com", "display_name": "None"},
        ],
    }
    users = {
        "push-only": {
            "id": "push-only",
            "status": "approved",
            "email": "p@x.com",
            "notification_preferences": {"channels": ["push"], "kinds": ["watch"]},
            "push_subscriptions": [{"endpoint": "https://push.example/p"}],
        },
        "email-only": {
            "id": "email-only",
            "status": "approved",
            "email": "e@x.com",
            "notification_preferences": {"channels": ["email"], "kinds": ["watch"]},
        },
        "no-channels": {
            "id": "no-channels",
            "status": "approved",
            "email": "n@x.com",
            "notification_preferences": {"channels": [], "kinds": ["common"]},
        },
    }
    monkeypatch.setattr(repo, "find_user_by_id", lambda uid: users.get(str(uid)))
    monkeypatch.setattr(
        "retail.batch.rules.load_rules",
        lambda: {"channels": ["email", "telegram", "push"]},
    )
    monkeypatch.setattr("retail.batch.alerts._secret", lambda *_a, **_k: "")
    monkeypatch.setattr("retail.short_links.attach_short_url", lambda payload, *_a, **_k: payload)
    sent_email: list[str] = []
    sent_push: list[str] = []
    monkeypatch.setattr(
        "retail.batch.alerts.send_email",
        lambda email, *_a, **_k: sent_email.append(email) or True,
    )
    monkeypatch.setattr(
        "retail.web_push.send_user_push",
        lambda user, *_a, **_k: sent_push.append(str(user.get("id"))) or True,
    )
    monkeypatch.setattr(repo, "claim_price_alert_send", lambda *_a, **_k: True)
    monkeypatch.setattr(repo, "claim_user_notification_send", lambda *_a, **_k: True)

    change = {
        "store": "falabella",
        "product_id": "tv-1",
        "name": "TV",
        "previous_price": 500000,
        "price": 400000,
        "query": "TV",
        "url": "/producto/falabella/tv-1",
    }
    total = notify_user_alert_change(repo, change, item=item)
    assert "e@x.com" in sent_email
    assert "p@x.com" not in sent_email
    assert sent_push == ["push-only"]
    assert "no-channels" not in sent_push
    assert total >= 2


def test_collect_user_alert_matches_prefers_anchor(repo, monkeypatch):
    ensure_user_alerts_list(repo)
    anchor = {
        "store": "falabella",
        "product_id": "sku-1",
        "name": "Phone",
        "price": 100,
        "compare_code": "CMP-1",
    }
    peer = {
        "store": "ripley",
        "product_id": "sku-2",
        "name": "Phone",
        "price": 90,
        "compare_code": "CMP-1",
    }
    monkeypatch.setattr(
        repo,
        "product_detail",
        lambda s, p: anchor if (s, p) == ("falabella", "sku-1") else None,
    )
    monkeypatch.setattr(repo, "by_compare_code", lambda code, limit=24: [peer] if code == "CMP-1" else [])
    item = {
        "anchor_store": "falabella",
        "anchor_product_id": "sku-1",
        "compare_code": "CMP-1",
        "query": "Phone",
    }
    matches = collect_user_alert_matches(repo, item)
    keys = {(m["store"], m["product_id"]) for m in matches}
    assert ("falabella", "sku-1") in keys
    assert ("ripley", "sku-2") in keys


def test_process_one_user_alerts_uses_collect_and_watcher_notify(repo, monkeypatch):
    ensure_user_alerts_list(repo)
    doc = {"name": "Notebook", "compare_code": "CMP-NB", "category": "Tech"}
    add_user_alert(
        repo,
        {"id": "u1", "email": "a@x.com", "name": "Ana"},
        store="falabella",
        product_id="nb-1",
        document={**doc, "store": "falabella", "product_id": "nb-1"},
    )
    start_run(repo, list_id=USER_ALERTS_LIST_ID)

    match = {
        "store": "falabella",
        "product_id": "nb-1",
        "name": "Notebook",
        "price": 800000,
        "price_normal": 900000,
        "url": "https://example.com/nb",
    }
    monkeypatch.setattr(
        "retail.user_alert_list.collect_user_alert_matches",
        lambda *_a, **_k: [match],
    )
    monkeypatch.setattr("retail.cyber_day.refresh_top_matches", lambda *_a, **_k: [match])
    monkeypatch.setattr(
        "retail.cyber_day.notify_cyber_change",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("broadcast notify_cyber_change no debe usarse"),
        ),
    )
    notified = {"n": 0}

    def fake_notify(repo_arg, change, *, item=None):
        notified["n"] += 1
        assert item is not None
        return 1

    monkeypatch.setattr("retail.user_alert_list.notify_user_alert_change", fake_notify)

    # Primera pasada: establece historial sin notify.
    first = process_one(repo, delay=0, list_id=USER_ALERTS_LIST_ID)
    assert first.get("ok")
    assert notified["n"] == 0

    # Segunda: baja de precio → notify watchers.
    match2 = {**match, "price": 700000}
    monkeypatch.setattr(
        "retail.user_alert_list.collect_user_alert_matches",
        lambda *_a, **_k: [match2],
    )
    monkeypatch.setattr("retail.cyber_day.refresh_top_matches", lambda *_a, **_k: [match2])
    # Rewind cursor
    from retail.cyber_day import load_run, save_run

    run = load_run(repo, USER_ALERTS_LIST_ID)
    run["cursor"] = 0
    run["processed"] = 0
    save_run(repo, run, list_id=USER_ALERTS_LIST_ID)
    second = process_one(repo, delay=0, list_id=USER_ALERTS_LIST_ID)
    assert second.get("ok")
    assert notified["n"] >= 1

def test_backfill_from_price_alerts(repo):
    ensure_user_alerts_list(repo)
    repo.price_alerts.insert_one({
        "user_id": "u9",
        "email": "u9@x.com",
        "store": "hites",
        "product_id": "h-1",
        "name": "Auriculares",
        "active": True,
    })
    result = backfill_from_price_alerts(repo)
    assert result["ok"]
    assert result["added"] >= 1
    row = repo.cyber_day_products.find_one({"list_id": USER_ALERTS_LIST_ID})
    assert row is not None
    assert row["watcher_count"] >= 1
