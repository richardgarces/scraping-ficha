"""Cyber Day: seed, state machine, progreso y notify on change."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from retail.cyber_day import (
    CYBER_GROUP_ID,
    SEED_PATH,
    CyberDayError,
    as_cron_group,
    continue_run,
    create_list,
    dedupe_items,
    delete_list,
    detect_changes,
    ensure_cyber_category,
    ensure_seed,
    export_csv,
    export_json,
    ficha_path,
    import_products,
    is_cyber_group,
    list_all_lists,
    load_seed_items,
    normalize_import_row,
    offer_signature,
    parse_products_payload,
    process_one,
    product_row_view,
    products_count,
    progress_view,
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

    matches[0]["price"] = 850000
    current2, changes2, _ = detect_changes(current, matches, query="iPhone")
    assert len(changes2) == 1
    assert changes2[0]["previous_price"] == 900000
    assert changes2[0]["price"] == 850000
    assert changes2[0]["query"] == "iPhone"
    assert "falabella:p1" in current2


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

    from retail.cyber_day import products_collection

    stored = products_collection(repo).find_one({"n": first.get("n") or 1})
    assert stored is not None
    assert stored.get("last_price") == 700000
    assert stored.get("prev_best_price") == 800000
    view = product_row_view({**stored, "id": str(stored["_id"])})
    assert view["price_direction"] == "down"


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
    assert "best_offer_url" in header
    assert csv_text.count("\n") >= 100
    payload = export_json(repo)
    assert payload["id"] == "cyber_junio2026"
    assert len(payload["items"]) == 100
    assert payload["items"][0]["query"]
    assert "stores_scraped" in payload["items"][0]
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
