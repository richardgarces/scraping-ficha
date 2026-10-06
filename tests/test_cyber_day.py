"""Cyber Day: seed, state machine, progreso y notify on change."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CYBER_GROUP_ID,
    SEED_PATH,
    CyberDayError,
    continue_run,
    dedupe_items,
    detect_changes,
    ensure_cyber_category,
    ensure_seed,
    export_csv,
    export_json,
    import_products,
    is_cyber_group,
    load_seed_items,
    normalize_import_row,
    offer_signature,
    parse_products_payload,
    process_one,
    progress_view,
    repair_duplicates,
    restart_run,
    start_run,
    status_payload,
    stop_run,
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

    with pytest.raises(CyberDayError):
        start_run(repo)

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

    matches[0]["price"] = 850000
    current2, changes2, _ = detect_changes(current, matches, query="iPhone")
    assert len(changes2) == 1
    assert changes2[0]["previous_price"] == 900000
    assert changes2[0]["price"] == 850000
    assert changes2[0]["query"] == "iPhone"
    assert "falabella:p1" in current2


def test_notify_on_change_mocked(repo, monkeypatch):
    ensure_seed(repo)
    start_run(repo)
    sent = {"n": 0}

    def fake_collect(repo, query):
        return [{
            "store": "falabella",
            "product_id": "iphone-x",
            "name": query,
            "price": 800000,
            "price_normal": 999000,
            "catalog_id": "cat-1",
        }]

    def fake_refresh(repo, matches):
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

    # Segunda observación con precio distinto
    def fake_collect_drop(repo, query):
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


def test_export_csv_and_json(repo):
    ensure_seed(repo)
    csv_text = export_csv(repo)
    assert "n,query,category" in csv_text.splitlines()[0]
    assert csv_text.count("\n") >= 100
    payload = export_json(repo)
    assert payload["id"] == "cyber_junio2026"
    assert len(payload["items"]) == 100
    assert payload["items"][0]["query"]
