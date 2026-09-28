"""Scraping admin de una sola tienda: puerta admin y filtro de stores."""

from __future__ import annotations

from fastapi.testclient import TestClient

from retail.web.app import app


def test_store_scrape_api_requires_admin():
    client = TestClient(app)
    denied = client.post("/api/admin/store-scrape", json={"tienda": "ahumada"})
    assert denied.status_code == 401
    page = client.get("/cron", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")


def test_products_for_store_keeps_group_queries_and_category_tree(monkeypatch):
    from retail.batch.store_scope import products_for_store

    monkeypatch.setattr("retail.batch.store_scope.normalize_store", lambda store_id: "ahumada")
    monkeypatch.setattr(
        "retail.batch.store_scope.groups_for_store",
        lambda store_id, **kwargs: ["farmacias"],
    )

    def fake_filter(products, group, **kwargs):
        assert group == "farmacias"
        return [item for item in products if item.get("expect") == group]

    monkeypatch.setattr("retail.batch.store_scope.filter_products_for_group", fake_filter)
    monkeypatch.setattr(
        "retail.batch.store_scope.category_catalog_items",
        lambda store_id, **kwargs: [
            {"id": "cat-vit", "query": "vitaminas", "category": "Salud / vitaminas"},
        ],
    )

    groups, kept = products_for_store(
        [
            {"id": "para", "query": "paracetamol", "expect": "farmacias"},
            {"id": "phone", "query": "iphone 16", "expect": "tecnologia"},
        ],
        "ahumada",
    )
    assert groups == ["farmacias"]
    assert [item["id"] for item in kept] == ["para", "cat-vit"]


def test_category_search_items_are_leaves_only():
    from retail.mongo import ProductRepository

    class _Cats:
        def find(self, match, projection):
            assert match["store"] == "falabella"
            return [
                {"id": "dept", "name": "Tecnología", "parent_id": None},
                {"id": "phones", "name": "Celulares", "parent_id": "dept"},
                {"id": "phones-2", "name": "Celulares", "parent_id": "dept"},
                {"id": "blank", "name": "  ", "parent_id": "dept"},
            ]

    items = ProductRepository.category_search_items(type("R", (), {"categories": _Cats()})(), "falabella")
    assert [item["query"] for item in items] == ["Celulares"]
    assert items[0]["id"] == "cat-falabella-phones"


def test_run_batch_tienda_scrapes_only_that_store(monkeypatch):
    from retail.batch import runner

    seen: list[dict] = []
    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {"source": "test"})
    monkeypatch.setattr(runner, "refresh_product_index", lambda: {"count": 1, "backend": "memoria"})
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr(
        "retail.batch.store_scope.products_for_store",
        lambda products, store_id, **kwargs: (
            ["farmacias"],
            [
                {"id": "para", "query": "paracetamol"},
                {"id": "ibu", "query": "ibuprofeno"},
            ],
        ),
    )

    def fake_search(query, **kwargs):
        seen.append({"query": query, "stores": list(kwargs.get("stores") or [])})
        return {
            "offer_count": 0,
            "comparable_count": 0,
            "groups": [],
            "saved": {},
            "warnings": [],
        }

    monkeypatch.setattr(runner, "search_products", fake_search)
    summary = runner.run_batch(persist=False, tienda="ahumada")
    assert summary["stores"] == ["ahumada"]
    assert summary["tienda"] == "ahumada"
    assert summary.get("grupo") is None
    assert summary["scope"] == "tienda"
    assert seen
    assert all(row["stores"] == ["ahumada"] for row in seen)
    assert {row["query"] for row in seen} == {"paracetamol", "ibuprofeno"}


def test_run_batch_tienda_dry_run_does_not_expand_to_the_group(monkeypatch):
    from retail.batch import runner

    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {"source": "test"})
    monkeypatch.setattr(
        "retail.store_categories.stores_for_group",
        lambda group_id, **kwargs: ["ahumada", "cruzverde", "salcobrand"],
    )
    monkeypatch.setattr(
        "retail.batch.store_scope.products_for_store",
        lambda products, store_id, **kwargs: (
            ["farmacias"],
            [{"id": "para", "query": "paracetamol"}],
        ),
    )
    summary = runner.run_batch(dry_run=True, tienda="ahumada")
    assert summary["stores"] == ["ahumada"]
    assert "cruzverde" not in summary["stores"]
    assert summary["searches"] == [{"id": "para", "query": "paracetamol"}]


def test_start_store_batch_rejects_second_start(monkeypatch):
    from retail.batch.store_scope import StoreBatchBusy
    from retail.web import jobs

    jobs._STORE_RUNNING.clear()
    monkeypatch.setattr("retail.batch.store_scope.normalize_store", lambda store_id: "ahumada")
    monkeypatch.setattr("retail.batch.store_scope.store_title", lambda store_id: "Ahumada")
    monkeypatch.setattr("retail.batch.store_scope.store_batch_is_busy", lambda repo, store_id: False)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)

    class _Thread:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name")

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", _Thread)
    try:
        first = jobs.start_store_batch("ahumada")
        assert first["tienda"] == "ahumada"
        assert first["running"] is True
        try:
            jobs.start_store_batch("ahumada")
            raised = False
        except StoreBatchBusy:
            raised = True
        assert raised
    finally:
        jobs._STORE_RUNNING.clear()


def test_cli_tienda_is_exclusive_with_grupo(monkeypatch):
    from retail.cli import unified_main

    seen: dict = {}

    def fake_run_batch(**kwargs):
        seen.update(kwargs)
        return {"searches": [], "alert_count": 0, "tienda": kwargs.get("tienda")}

    monkeypatch.setattr("retail.batch.runner.run_batch", fake_run_batch)
    assert unified_main(["batch", "--tienda", "ahumada", "--dry-run"]) == 0
    assert seen["tienda"] == "ahumada"
    assert seen["grupo"] is None
    assert unified_main(["batch", "--tienda", "ahumada", "--grupo", "farmacias"]) == 1
