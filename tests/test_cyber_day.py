"""Cyber Day: seed, state machine, progreso y notify on change."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CYBER_GROUP_ID,
    SEED_PATH,
    CyberDayError,
    _offer_change_covers_best,
    _prev_best_price_patch,
    _price_move_label,
    _rank_matches,
    append_best_price_observation,
    as_cron_group,
    continue_run,
    create_list,
    cyber_match_accepted,
    day_evolution_report,
    dedupe_items,
    delete_list,
    detect_changes,
    ensure_cyber_category,
    ensure_seed,
    export_csv,
    export_json,
    ficha_path,
    history_collection,
    import_products,
    is_cyber_group,
    list_all_lists,
    load_seed_items,
    normalize_import_row,
    notify_cyber_change,
    offer_signature,
    parse_products_payload,
    price_direction,
    process_one,
    product_row_view,
    products_count,
    progress_view,
    query_best_price_change,
    repair_duplicates,
    restart_run,
    start_run,
    status_payload,
    stop_run,
    summarize_match_stats,
    update_item,
)


NOW = datetime(2026, 10, 6, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def repo(mongo_uri, monkeypatch):
    from retail.mongo import ProductRepository

    repository = ProductRepository(mongo_uri, database=f"test_cyber_{uuid4().hex}")
    monkeypatch.setattr("retail.cyber_day._now", lambda: NOW)
    try:
        yield repository
    finally:
        repository.client.drop_database(repository.db.name)
        repository.close()


def test_seed_file_has_100_queries():
    items = load_seed_items()
    assert SEED_PATH.is_file()
    assert CYBER_GROUP_ID == "cyber_junio2026"
    assert is_cyber_group("cyber_junio2026")
    assert len(items) == 100
    assert items[0]["query"] == "iPhone 17 / 17 Pro / 17 Pro Max"
    assert items[0]["category"] == "Celulares"
    assert items[99]["query"] == "Smartwatch Garmin"
    assert items[99]["category"] == "Wearables"
    categories = {item["category"] for item in items}
    assert "Gaming" in categories and "Línea blanca" in categories


def test_ensure_cyber_category_registers_group(repo):
    meta = ensure_cyber_category(repo)
    assert meta["ok"] is True
    assert meta["id"] == "cyber_junio2026"
    row = repo.get_store_category("cyber_junio2026")
    assert row is not None
    assert row["title"] == "Cyber Junio 2026"
    assert row.get("query_list") is True
    assert len(row.get("store_ids") or []) > 0


def test_restart_from_mid_lap(repo):
    ensure_seed(repo)
    start_run(repo)
    from retail.cyber_day import load_run, save_run

    run = load_run(repo)
    run["cursor"] = 50
    run["processed"] = 50
    save_run(repo, run)
    stop_run(repo)
    restarted = restart_run(repo)
    assert restarted["run"]["status"] == "running"
    assert restarted["run"]["cursor"] == 0
    assert restarted["run"]["lap"] == 1


def test_ensure_seed_loads_when_empty(repo):
    first = ensure_seed(repo)
    assert first["seeded"] is True
    assert first["total"] == 100
    second = ensure_seed(repo)
    assert second["seeded"] is False
    assert second["total"] == 100
    payload = status_payload(repo)
    assert payload["products_count"] == 100
    assert payload["run"]["import_required"] is False


def test_state_machine_start_stop_continue(repo):
    ensure_seed(repo)
    started = start_run(repo)
    assert started["run"]["status"] == "running"
    assert started["run"]["lap"] == 1
    assert started["run"]["cursor"] == 0
    assert started["run"]["percent"] == 0.0

    # Idempotente: segundo start no falla (cron «Iniciar ahora»).
    again = start_run(repo)
    assert again["run"]["status"] == "running"

    stopped = stop_run(repo)
    assert stopped["run"]["status"] == "stopped"

    # Simula avance parcial
    from retail.cyber_day import load_run, save_run

    run = load_run(repo)
    run["cursor"] = 40
    run["processed"] = 40
    save_run(repo, run)

    cont = continue_run(repo)
    assert cont["run"]["status"] == "running"
    assert cont["run"]["cursor"] == 40
    assert cont["run"]["processed"] == 40
    assert cont["run"]["percent"] == 40.0


def test_progress_percent_and_eta():
    run = {
        "status": "running",
        "lap": 2,
        "cursor": 25,
        "processed": 25,
        "total": 100,
        "lap_started_at": NOW,
        "heartbeat_at": NOW,
    }
    # Elapsed artificial vía monkeypatch no hace falta: elapsed=0 si now==lap_started
    view = progress_view(run, product_total=100)
    assert view["percent"] == 25.0
    assert view["lap"] == 2
    assert view["processed"] == 25


def test_rank_matches_prefers_lowest_price_not_largest_discount():
    """Charge/Boombox con descuento CLP enorme no debe tapar un Go más barato."""
    docs = [
        {
            "store": "ripley",
            "product_id": "charge6",
            "name": "PARLANTE BLUETOOTH JBL CHARGE 6",
            "brand": "JBL",
            "price": 139990,
            "price_normal": 229990,
        },
        {
            "store": "ripley",
            "product_id": "boombox",
            "name": "PARLANTE BLUETOOTH JBL BOOMBOX 4",
            "brand": "JBL",
            "price": 349990,
            "price_normal": 549990,
        },
        {
            "store": "falabella",
            "product_id": "go-essential",
            "name": "Parlante Go Essential 2 Azul",
            "brand": "JBL",
            "price": 21990,
            "price_normal": 36990,
        },
        {
            "store": "lider",
            "product_id": "onthego",
            "name": "Parlante Bluetooth JBL ON the go essential",
            "brand": "JBL",
            "price": 234990,
            "price_normal": 329990,
        },
    ]
    ranked = _rank_matches(docs, 3)
    assert [d["product_id"] for d in ranked] == ["go-essential", "charge6", "onthego"]
    summary = summarize_match_stats(ranked)
    assert summary["last_price"] == 21990
    assert summary["best_store"] == "falabella"


def test_cyber_match_accepted_requires_brand_and_product_type():
    query = "JBL parlante Bluetooth"
    assert cyber_match_accepted(query, {
        "store": "falabella",
        "product_id": "go",
        "name": "Parlante Go Essential 2 Azul",
        "brand": "JBL",
        "price": 21990,
        "price_normal": 36990,
    })
    assert cyber_match_accepted(query, {
        "store": "falabella",
        "product_id": "go-bt",
        "name": "Parlante Bluetooth GO5",
        "brand": "JBL",
        "price": 39990,
        "price_normal": 59990,
    })
    # Sin marca JBL (Barbie) o sin «parlante» (audífonos): no competir por mejor precio.
    assert not cyber_match_accepted(query, {
        "store": "ripley",
        "product_id": "barbie",
        "name": "PARLANTE BLUETOOTH BARBIE MINI",
        "brand": "BARBIE",
        "price": 6990,
    })
    assert not cyber_match_accepted(query, {
        "store": "ripley",
        "product_id": "tunes",
        "name": "AUDÍFONOS JBL TUNE 520BT BLUETOOTH",
        "brand": "JBL",
        "price": 19990,
    })
    assert not cyber_match_accepted(query, {
        "store": "knasta",
        "product_id": "agg",
        "name": "Parlante Bluetooth JBL GO 4",
        "brand": "JBL",
        "price": 19990,
    })


def test_detect_changes_skips_first_sighting_then_notifies():
    matches = [
        {
            "store": "falabella",
            "product_id": "p1",
            "name": "iPhone",
            "price": 900000,
            "price_normal": 1000000,
        }
    ]
    current, changes, summary = detect_changes({}, matches, query="iPhone")
    assert current["falabella:p1"] == offer_signature(900000, 1000000, 0)
    assert changes == []
    assert summary["last_price"] == 900000
    assert summary["stores_scraped"] == 1
    assert summary["max_price_normal"] == 1000000
    assert summary["min_price_normal"] == 1000000
    assert summary["max_offer_price"] == 900000
    assert summary["best_offer_url"] == ficha_path("falabella", "p1")
    assert summary["best_store"] == "falabella"

    matches[0]["price"] = 850000
    current2, changes2, _ = detect_changes(current, matches, query="iPhone")
    assert len(changes2) == 1
    assert changes2[0]["previous_price"] == 900000
    assert changes2[0]["price"] == 850000
    assert changes2[0]["query"] == "iPhone"
    assert "falabella:p1" in current2

    # Subida también genera cambio (no solo bajadas)
    matches[0]["price"] = 920000
    _, changes_up, _ = detect_changes(current2, matches, query="iPhone")
    assert len(changes_up) == 1
    assert changes_up[0]["previous_price"] == 850000
    assert changes_up[0]["price"] == 920000


def test_query_best_price_change_up_and_down():
    item = {"last_price": 100000}
    matches = [{
        "store": "paris",
        "product_id": "tv-1",
        "name": "TV",
        "price": 90000,
        "image_url": "https://example.com/a.jpg",
    }]
    summary = summarize_match_stats(matches)
    drop = query_best_price_change(item, matches, summary, query="TV OLED")
    assert drop is not None
    assert drop["previous_price"] == 100000
    assert drop["price"] == 90000
    assert drop["kind"] == "best_price"
    assert "bajó" in drop["message"]
    assert _price_move_label(100000, 90000) == "bajó"

    rise = query_best_price_change(
        {"last_price": 90000},
        [{**matches[0], "price": 110000}],
        {"last_price": 110000, "best_offer_url": "/producto?store=paris&id=tv-1"},
        query="TV OLED",
    )
    assert rise is not None
    assert rise["price"] == 110000
    assert "subió" in rise["message"]
    assert _price_move_label(90000, 110000) == "subió"

    # Match nuevo más barato: detect_changes no emite, pero sí el mejor precio
    item2 = {
        "last_price": 100000,
        "last_matches": {"falabella:old": offer_signature(100000, 0, 0)},
    }
    new_matches = [
        {"store": "falabella", "product_id": "old", "name": "TV", "price": 100000},
        {"store": "ripley", "product_id": "new", "name": "TV Ripley", "price": 80000},
    ]
    summary2 = summarize_match_stats(new_matches)
    best = query_best_price_change(item2, new_matches, summary2, query="TV")
    assert best is not None
    assert best["price"] == 80000
    assert best["store"] == "ripley"
    sigs, offer_changes, _ = detect_changes(item2["last_matches"], new_matches, query="TV")
    assert offer_changes == []  # ripley es primera observación
    assert not _offer_change_covers_best(offer_changes, best)
    assert "ripley:new" in sigs


def test_notify_cyber_change_reaches_all_subscribed_users(repo, monkeypatch):
    """Push/Telegram Cyber van a usuarios finales suscritos, no solo admins."""
    sent_tg: list[str] = []
    sent_push: list[str] = []
    admin_tg = {"n": 0}

    users = [
        {
            "_id": "admin-1",
            "role": "admin",
            "status": "approved",
            "telegram_chat_id": "111",
            "notification_preferences": {"channels": ["telegram", "push"]},
            "push_subscriptions": [{"endpoint": "https://push.example/admin"}],
        },
        {
            "_id": "user-2",
            "role": "user",
            "status": "approved",
            "telegram_chat_id": "222",
            "notification_preferences": {"channels": ["telegram", "push"]},
            "push_subscriptions": [{"endpoint": "https://push.example/user"}],
        },
        {
            "_id": "user-3",
            "role": "user",
            "status": "approved",
            "telegram_chat_id": "333",
            "notification_preferences": {"channels": ["telegram"]},
            # sin push
        },
    ]

    monkeypatch.setattr(
        "retail.price_alerts.notify_price_changes",
        lambda *_a, **_k: 0,
    )
    monkeypatch.setattr(repo, "list_notification_users", lambda: users)
    monkeypatch.setattr(
        "retail.batch.alerts.bind_user_chats",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "retail.batch.alerts._telegram_text",
        lambda *_a, **_k: admin_tg.__setitem__("n", admin_tg["n"] + 1) or True,
    )
    monkeypatch.setattr(
        "retail.batch.alerts.send_to_user",
        lambda user, *_a, **_k: sent_tg.append(str(user.get("_id"))) or True,
    )
    push_payloads: list[dict] = []

    def capture_push(user, payload, **_k):
        sent_push.append(str(user.get("_id")))
        push_payloads.append(dict(payload))
        return True

    monkeypatch.setattr("retail.web_push.send_user_push", capture_push)
    monkeypatch.setattr(
        "retail.batch.rules.load_rules",
        lambda: {"channels": ["telegram", "push", "email"]},
    )
    monkeypatch.setattr(
        repo,
        "claim_user_notification_send",
        lambda *_a, **_k: True,
    )

    change = {
        "store": "falabella",
        "product_id": "iphone-x",
        "name": "iPhone",
        "previous_price": 800000,
        "price": 700000,
        "query": "iPhone",
        "url": "https://www.falabella.com/product/iphone-x",
        "image_url": "",
    }
    total = notify_cyber_change(repo, change)
    assert admin_tg["n"] == 1
    assert set(sent_tg) == {"admin-1", "user-2", "user-3"}
    assert set(sent_push) == {"admin-1", "user-2"}
    assert total >= 1 + len(sent_tg) + len(sent_push)
    assert push_payloads
    assert push_payloads[0].get("short_url")
    assert "producto" in push_payloads[0]["short_url"] or "/o/" in push_payloads[0]["short_url"]


def test_price_direction_streak_and_patch():
    """Verde/rojo = primera; azul/naranjo = misma dirección otra vez."""
    assert price_direction(100, None) is None
    assert price_direction(100, 100) is None
    assert price_direction(90, 100) == "down"
    assert price_direction(110, 100) == "up"
    assert price_direction(80, 90, last_delta_direction="down", delta_streak=2) == "down_again"
    assert price_direction(120, 110, last_delta_direction="up", delta_streak=2) == "up_again"
    # Dirección real manda si el estado guardado no coincide
    assert price_direction(80, 90, last_delta_direction="up", delta_streak=3) == "down"

    first_drop = _prev_best_price_patch(
        {"last_price": 100, "best_store": "falabella"},
        90,
        "paris",
    )
    assert first_drop == {
        "prev_best_price": 100,
        "last_delta_direction": "down",
        "delta_streak": 1,
        "prev_best_store": "falabella",
    }
    # Segunda baja misma tienda: racha 2, no pisa prev_best_store
    second_drop = _prev_best_price_patch(
        {
            "last_price": 90,
            "best_store": "paris",
            "last_delta_direction": "down",
            "delta_streak": 1,
            "prev_best_store": "falabella",
        },
        80,
        "paris",
    )
    assert second_drop["last_delta_direction"] == "down"
    assert second_drop["delta_streak"] == 2
    assert second_drop["prev_best_price"] == 90
    assert "prev_best_store" not in second_drop

    # Nueva tienda gana la baja: actualiza prev a la ganadora anterior
    third_drop = _prev_best_price_patch(
        {
            "last_price": 80,
            "best_store": "paris",
            "last_delta_direction": "down",
            "delta_streak": 2,
            "prev_best_store": "falabella",
        },
        70,
        "ripley",
    )
    assert third_drop["delta_streak"] == 3
    assert third_drop["prev_best_store"] == "paris"

    rebound_up = _prev_best_price_patch(
        {
            "last_price": 70,
            "best_store": "ripley",
            "last_delta_direction": "down",
            "delta_streak": 3,
            "prev_best_store": "paris",
        },
        95,
        "ripley",
    )
    assert rebound_up["last_delta_direction"] == "up"
    assert rebound_up["delta_streak"] == 1
    assert rebound_up["prev_best_store"] is None

    again_up = _prev_best_price_patch(
        {"last_price": 95, "last_delta_direction": "up", "delta_streak": 1},
        110,
    )
    assert again_up["delta_streak"] == 2
    assert again_up["last_delta_direction"] == "up"
    assert again_up["prev_best_store"] is None

    unchanged = _prev_best_price_patch(
        {
            "last_price": 110,
            "last_delta_direction": "up",
            "delta_streak": 2,
            "prev_best_price": 95,
            "prev_best_store": "paris",
        },
        110,
    )
    assert unchanged == {}

    view = product_row_view({
        "last_price": 80,
        "prev_best_price": 90,
        "last_delta_direction": "down",
        "delta_streak": 2,
        "best_store": "paris",
        "prev_best_store": "falabella",
    })
    assert view["price_direction"] == "down_again"
    assert view["last_delta_direction"] == "down"
    assert view["delta_streak"] == 2
    assert view["best_store"] == "paris"
    assert view["prev_best_store"] == "falabella"
    assert view["prev_best_store_title"]


def test_match_stats_todo_medio_and_product_row_view():
    matches = [
        {
            "store": "falabella",
            "product_id": "iphone-a",
            "price": 1499990,
            "price_all_payment": 1349990,
            "price_normal": 1599990,
        },
        {
            "store": "paris",
            "product_id": "iphone-b",
            "price": 1399990,
            "price_normal": 1499990,
        },
        {
            "store": "falabella",
            "product_id": "iphone-c",
            "price": 1550000,
            # sin price_normal → no entra en min/max normal
        },
    ]
    stats = summarize_match_stats(matches)
    assert stats["stores_scraped"] == 2
    assert stats["last_price"] == 1349990  # todo medio de falabella-a
    assert stats["max_price_normal"] == 1599990
    assert stats["min_price_normal"] == 1499990
    assert stats["max_offer_price"] == 1550000
    assert stats["best_offer_url"] == "/producto?store=falabella&id=iphone-a"
    assert stats["best_store"] == "falabella"

    row = product_row_view({
        "n": 1,
        "query": "iPhone 17 / 17 Pro / 17 Pro Max",
        "category": "Celulares",
        "last_match_count": 3,
        "last_matches": {
            "falabella:iphone-a": offer_signature(1349990, 1599990, 0),
            "paris:iphone-b": offer_signature(1399990, 1499990, 0),
            "falabella:iphone-c": offer_signature(1550000, 0, 0),
        },
    })
    assert row["stores_scraped"] == 2
    assert row["max_price_normal"] == 1599990
    assert row["min_price_normal"] == 1499990
    assert row["max_offer_price"] == 1550000
    assert row["last_price"] == 1349990
    assert row["best_offer_url"] == "/producto?store=falabella&id=iphone-a"
    assert row["best_store"] == "falabella"
    assert row["best_store_title"]
    # Sin normal en firma → None (UI muestra —)
    empty_normals = product_row_view({
        "query": "x",
        "last_matches": {"ripley:z": offer_signature(1000, 0, 0)},
    })
    assert empty_normals["max_price_normal"] is None
    assert empty_normals["min_price_normal"] is None


def test_notify_on_change_mocked(repo, monkeypatch):
    ensure_seed(repo)
    start_run(repo)
    sent = {"n": 0}

    def fake_collect(repo, query, **_kwargs):
        return [{
            "store": "falabella",
            "product_id": "iphone-x",
            "name": query,
            "price": 800000,
            "price_normal": 999000,
            "catalog_id": "cat-1",
        }]

    def fake_refresh(repo, matches, **_kwargs):
        return matches

    def fake_notify(repo, change):
        sent["n"] += 1
        return 1

    monkeypatch.setattr("retail.cyber_day.collect_query_matches", fake_collect)
    monkeypatch.setattr("retail.cyber_day.refresh_top_matches", fake_refresh)
    monkeypatch.setattr("retail.cyber_day.notify_cyber_change", fake_notify)

    first = process_one(repo, delay=0)
    assert first["ok"] is True
    assert first["changed"] == 0
    assert sent["n"] == 0
    assert first.get("history_recorded") is True
    assert history_collection(repo).count_documents({"n": first.get("n") or 1}) == 1

    # Segunda observación con precio distinto
    def fake_collect_drop(repo, query, **_kwargs):
        return [{
            "store": "falabella",
            "product_id": "iphone-x",
            "name": query,
            "price": 700000,
            "price_normal": 999000,
            "catalog_id": "cat-1",
        }]

    monkeypatch.setattr("retail.cyber_day.collect_query_matches", fake_collect_drop)
    # Rewind cursor: process_one avanzó; volver a item 0
    from retail.cyber_day import load_run, save_run

    run = load_run(repo)
    run["cursor"] = 0
    run["processed"] = 0
    save_run(repo, run)

    second = process_one(repo, delay=0)
    assert second["ok"] is True
    assert second["changed"] == 1
    assert sent["n"] == 1
    assert second.get("history_recorded") is True
    assert history_collection(repo).count_documents({"n": first.get("n") or 1}) == 2

    from retail.cyber_day import products_collection

    stored = products_collection(repo).find_one({"n": first.get("n") or 1})
    assert stored is not None
    assert stored.get("last_price") == 700000
    assert stored.get("prev_best_price") == 800000
    assert stored.get("last_delta_direction") == "down"
    assert stored.get("delta_streak") == 1
    view = product_row_view({**stored, "id": str(stored["_id"])})
    assert view["price_direction"] == "down"

    # Tercera observación: subida → también notifica
    def fake_collect_rise(repo, query, **_kwargs):
        return [{
            "store": "falabella",
            "product_id": "iphone-x",
            "name": query,
            "price": 750000,
            "price_normal": 999000,
            "catalog_id": "cat-1",
        }]

    monkeypatch.setattr("retail.cyber_day.collect_query_matches", fake_collect_rise)
    run = load_run(repo)
    run["cursor"] = 0
    run["processed"] = 0
    save_run(repo, run)
    sent["n"] = 0
    third = process_one(repo, delay=0)
    assert third["ok"] is True
    assert third["changed"] == 1
    assert sent["n"] == 1
    stored2 = products_collection(repo).find_one({"n": first.get("n") or 1})
    assert stored2.get("last_price") == 750000
    assert stored2.get("last_delta_direction") == "up"


def test_append_best_price_observation_dedupes_same_day(repo):
    ensure_seed(repo)
    summary = {
        "last_price": 100000,
        "last_price_normal": 120000,
        "best_store": "falabella",
    }
    matches = [{
        "store": "falabella",
        "product_id": "abc",
        "name": "TV",
        "price": 100000,
        "price_normal": 120000,
    }]
    at = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
    first = append_best_price_observation(
        repo,
        list_id=CYBER_GROUP_ID,
        n=1,
        query="TV OLED",
        summary=summary,
        matches=matches,
        at=at,
    )
    assert first is not None
    assert first["day"] == "2026-10-06"
    again = append_best_price_observation(
        repo,
        list_id=CYBER_GROUP_ID,
        n=1,
        query="TV OLED",
        summary=summary,
        matches=matches,
        at=datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc),
    )
    assert again is None
    changed = append_best_price_observation(
        repo,
        list_id=CYBER_GROUP_ID,
        n=1,
        query="TV OLED",
        summary={**summary, "last_price": 90000, "best_store": "ripley"},
        matches=[{
            "store": "ripley",
            "product_id": "xyz",
            "name": "TV",
            "price": 90000,
            "price_normal": 120000,
        }],
        at=datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc),
    )
    assert changed is not None
    report = day_evolution_report(repo, 1, list_id=CYBER_GROUP_ID, day="2026-10-06")
    assert report["ok"] is True
    assert report["timezone"] == "America/Santiago"
    assert len(report["observations"]) == 2
    assert report["stats"]["min"] == 90000
    assert report["stats"]["current"] == 90000
    assert report["stats"]["change"] == -10000
    assert report["stats"]["min_store"] == "ripley"
    assert report["stats"]["max_store"] == "falabella"
    assert report["extremes"]["menor_valor"]["value"] == 90000
    assert report["extremes"]["menor_valor"]["store"] == "ripley"
    assert report["extremes"]["mayor_valor"]["value"] == 100000
    assert report["extremes"]["mayor_descuento"]["value"] == 30000
    assert report["extremes"]["menor_descuento"]["value"] == 20000
    assert all(obs.get("store_title") for obs in report["observations"])


def test_parse_import_json_and_csv():
    rows = parse_products_payload(
        '{"items":[{"n":1,"query":"TV OLED","category":"TV"}]}',
        filename="x.json",
    )
    assert rows[0]["query"] == "TV OLED"
    assert rows[0]["category"] == "TV"
    csv_text = "n,query,category\n1,AirPods Pro,Audio\n"
    rows2 = parse_products_payload(csv_text, filename="x.csv")
    assert rows2[0]["query"] == "AirPods Pro"
    assert normalize_import_row({"name": "Solo nombre"}, 0)["query"] == "Solo nombre"


def test_import_replaces_list(repo):
    ensure_seed(repo)
    result = import_products(
        repo,
        [normalize_import_row({"n": 1, "query": "Solo uno", "category": "Audio"}, 0)],
        source="test",
    )
    assert result["imported"] == 1
    assert status_payload(repo)["products_count"] == 1


def test_dedupe_and_repair_duplicates(repo):
    items = load_seed_items()
    doubled = items + [{**item, "n": item["n"]} for item in items]
    assert len(doubled) == 200
    assert len(dedupe_items(doubled)) == 100
    import_products(repo, items, source="seed-a")
    # Simula seed×2 sin clear (como race viejo).
    coll = repo.cyber_day_products
    for item in items:
        coll.insert_one({**item, "source": "dup"})
    assert coll.count_documents({}) == 200
    repaired = repair_duplicates(repo)
    assert repaired["repaired"] is True
    assert repaired["total"] == 100
    assert status_payload(repo)["products_count"] == 100


def test_update_item_query_while_running(repo, monkeypatch):
    ensure_seed(repo)
    start_run(repo)
    assert status_payload(repo)["run"]["status"] == "running"

    monkeypatch.setattr(
        "retail.cyber_day.catalog_matches_for_query",
        lambda *_a, **_k: [{
            "store": "falabella",
            "product_id": "nuevo-1",
            "price": 500000,
            "price_all_payment": 499990,
            "price_normal": 600000,
        }],
    )
    result = update_item(repo, 1, query="iPhone 17 Pro Max 256GB")
    assert result["message"] == "Query actualizada"
    assert result["run"]["status"] == "running"
    updated = result["updated"]
    assert updated["query"] == "iPhone 17 Pro Max 256GB"
    assert updated["last_price"] == 499990
    assert updated["stores_scraped"] == 1

    row = next(r for r in result["products"] if r["n"] == 1)
    assert row["query"] == "iPhone 17 Pro Max 256GB"

    with pytest.raises(CyberDayError, match="vacía"):
        update_item(repo, 1, query="   ")


def test_export_csv_and_json(repo):
    ensure_seed(repo)
    csv_text = export_csv(repo)
    header = csv_text.splitlines()[0]
    assert "n,query,category" in header
    assert "stores_scraped" in header
    assert "max_price_normal" in header
    assert "best_store" in header
    assert "best_offer_url" in header
    assert csv_text.count("\n") >= 100
    payload = export_json(repo)
    assert payload["id"] == "cyber_junio2026"
    assert len(payload["items"]) == 100
    assert payload["items"][0]["query"]
    assert "stores_scraped" in payload["items"][0]
    assert "best_store" in payload["items"][0]
    assert "best_offer_url" in payload["items"][0]


def test_as_cron_group_shows_queries_not_store_catalog(repo):
    ensure_seed(repo)
    start_run(repo)
    row = as_cron_group(repo)
    assert row["query_list"] is True
    assert row["store_count"] == 100
    assert row["query_count"] == 100
    assert row["status"] == "running"
    assert row["progress"]["items"] == 100


def test_create_list_independent_run(repo):
    ensure_seed(repo)
    start_run(repo, list_id="cyber_junio2026")
    created = create_list(repo, name="Cyber Prueba", slug="cyber_prueba", use_seed=True)
    assert created["ok"] is True
    assert created["list_id"] == "cyber_prueba"
    assert products_count(repo, "cyber_prueba") == 100
    assert products_count(repo, "cyber_junio2026") == 100
    # La lista nueva arranca idle; la oficial sigue running.
    assert created["run"]["status"] == "idle"
    assert status_payload(repo, list_id="cyber_junio2026")["run"]["status"] == "running"
    slugs = {item["slug"] for item in list_all_lists(repo)}
    assert "cyber_junio2026" in slugs and "cyber_prueba" in slugs


def test_import_preserves_list_identity(repo):
    created = create_list(repo, name="Cyber Oct 2026", slug="cyber_oct2026", use_seed=False)
    assert created["list_id"] == "cyber_oct2026"
    result = import_products(
        repo,
        [
            normalize_import_row({"n": 1, "query": "TV OLED", "category": "TV"}, 0),
            normalize_import_row({"n": 2, "query": "AirPods", "category": "Audio"}, 1),
        ],
        source="reimport-test",
        list_id="cyber_oct2026",
    )
    assert result["imported"] == 2
    assert result["list_id"] == "cyber_oct2026"
    assert result["list_name"] == "Cyber Oct 2026"
    meta = next(item for item in list_all_lists(repo) if item["slug"] == "cyber_oct2026")
    assert meta["name"] == "Cyber Oct 2026"
    assert products_count(repo, "cyber_oct2026") == 2


def test_delete_list_blocks_running_and_last(repo):
    ensure_seed(repo)
    created = create_list(repo, name="Cyber Borrar", slug="cyber_borrar", use_seed=True)
    assert created["list_id"] == "cyber_borrar"
    start_run(repo, list_id="cyber_borrar")
    with pytest.raises(CyberDayError, match="Pará la lista"):
        delete_list(repo, "cyber_borrar")
    stop_run(repo, list_id="cyber_borrar")
    deleted = delete_list(repo, "cyber_borrar")
    assert deleted["deleted"] == "cyber_borrar"
    slugs = {item["slug"] for item in list_all_lists(repo)}
    assert "cyber_borrar" not in slugs
    assert "cyber_junio2026" in slugs
    with pytest.raises(CyberDayError, match="única lista"):
        delete_list(repo, "cyber_junio2026")
