"""Scraping básico: admin, upsert del repositorio y tiendas solo del grupo."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from retail.web.app import app


def test_basic_scrape_api_requires_admin(anonymous_repo):
    client = TestClient(app)
    denied = client.post("/api/admin/basic-scrape", json={})
    assert denied.status_code == 401
    page = client.get("/cron", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")


def test_basic_scrape_api_returns_409_when_busy(monkeypatch):
    from retail.batch.basic_scrape import BasicScrapeBusy

    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin"},
    )

    def busy(**kwargs):
        raise BasicScrapeBusy()

    monkeypatch.setattr("retail.web.settings_api.start_basic_scrape", busy)
    client = TestClient(app)
    response = client.post("/api/admin/basic-scrape", json={})
    assert response.status_code == 409
    assert "curso" in response.json()["detail"]


def test_cron_page_has_basic_scrape_button():
    from pathlib import Path

    html = Path("retail/web/static/cron.html").read_text()
    js = Path("retail/web/static/cron.js").read_text()
    assert "Scraping básico" in html
    assert 'id="basic-scrape-run"' in html
    assert 'src="/static/cron.js?v=' in html
    assert "/api/admin/basic-scrape" in js


def test_start_basic_scrape_rejects_second_start(monkeypatch):
    from retail.batch.basic_scrape import BasicScrapeBusy
    from retail.web import jobs

    jobs._BASIC_RUNNING = False

    class _Repo:
        def find_running_basic_scrape(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr("retail.search.connect_repo", lambda: _Repo())

    class _Thread:
        def __init__(self, *args, **kwargs):
            self.name = kwargs.get("name")

        def start(self):
            return None

    monkeypatch.setattr(jobs.threading, "Thread", _Thread)
    try:
        first = jobs.start_basic_scrape()
        assert first["job"] == "scraping_basico"
        assert first["running"] is True
        try:
            jobs.start_basic_scrape()
            raised = False
        except BasicScrapeBusy:
            raised = True
        assert raised
    finally:
        jobs._BASIC_RUNNING = False


def test_upsert_offers_inserts_new_and_updates_existing():
    from retail.mongo import ProductRepository

    class MemCollection:
        def __init__(self):
            self.docs = []

        def find(self, query, projection=None):
            wanted = {
                (item.get("store"), item.get("product_id"))
                for item in (query or {}).get("$or") or []
            }
            for doc in self.docs:
                if (doc.get("store"), doc.get("product_id")) in wanted:
                    yield doc

        def bulk_write(self, operations, ordered=False):
            upserted = modified = matched = 0
            for op in operations:
                filt = op._filter
                update = op._doc
                existing = next(
                    (
                        doc
                        for doc in self.docs
                        if doc.get("store") == filt.get("store")
                        and doc.get("product_id") == filt.get("product_id")
                    ),
                    None,
                )
                if existing is None and op._upsert:
                    doc = {}
                    doc.update(update.get("$setOnInsert") or {})
                    doc.update(update.get("$set") or {})
                    if "$push" in update:
                        doc["price_history"] = list(update["$push"]["price_history"]["$each"])
                    self.docs.append(doc)
                    upserted += 1
                elif existing is not None:
                    existing.update(update.get("$set") or {})
                    if "$push" in update:
                        existing.setdefault("price_history", []).extend(
                            update["$push"]["price_history"]["$each"]
                        )
                    matched += 1
                    modified += 1

            class Result:
                pass

            result = Result()
            result.upserted_count = upserted
            result.modified_count = modified
            result.matched_count = matched
            return result

    repo = ProductRepository.__new__(ProductRepository)
    repo.collection = MemCollection()
    offer = {
        "store": "ahumada",
        "product_id": "para-500",
        "sku_id": "para-500",
        "name": "Paracetamol 500",
        "price": 1990,
        "currency": "CLP",
    }
    created = repo.upsert_offers([offer], "paracetamol")
    assert created == {"upserted": 1, "modified": 0, "matched": 0}
    assert repo.collection.docs[0]["price"] == 1990

    updated = repo.upsert_offers([{**offer, "price": 1490}], "paracetamol")
    assert updated["upserted"] == 0
    assert updated["modified"] == 1
    assert len(repo.collection.docs) == 1
    assert repo.collection.docs[0]["price"] == 1490


def test_job_scrapes_only_the_product_group_and_upserts(monkeypatch):
    from retail.batch.basic_scrape import run_basic_scrape
    from retail.search import SEARCH_TIMEOUT

    calls = []
    catalog = {}

    def fake_search(query, **kwargs):
        stores = list(kwargs.get("stores") or [])
        calls.append({"query": query, "stores": stores, "timeout": kwargs.get("timeout"), "fresh": kwargs.get("fresh")})
        assert kwargs.get("stores") is not None
        assert set(stores) != {"ahumada", "cruzverde", "salcobrand", "pcfactory", "entel", "movistar", "falabella"}
        price = 1490 if "500" in query else 1990
        store = stores[0]
        return {
            "offer_count": 1,
            "groups": [
                {
                    "offers": [
                        {
                            "store": store,
                            "product_id": "para-500" if "para" in query else "note-1",
                            "sku_id": "sku",
                            "name": query,
                            "price": price,
                        }
                    ]
                }
            ],
            "saved": None,
            "store_errors": [],
        }

    def stores_for_group(group, **kwargs):
        return {
            "farmacias": ["ahumada", "cruzverde", "salcobrand"],
            "tecnologia": ["pcfactory", "entel", "movistar"],
        }[group]

    monkeypatch.setattr("retail.batch.basic_scrape.search_products", fake_search)
    monkeypatch.setattr("retail.store_categories.stores_for_group", stores_for_group)
    monkeypatch.setattr(
        "retail.batch.basic_scrape.list_stores",
        lambda: [
            SimpleNamespace(id=item)
            for item in (
                "ahumada",
                "cruzverde",
                "salcobrand",
                "pcfactory",
                "entel",
                "movistar",
                "falabella",
            )
        ],
    )

    class Repo:
        def __init__(self):
            self.started = None
            self.finished = None

        def start_batch_run(self, data):
            self.started = dict(data)
            return "run-1"

        def update_batch_run(self, run_id, **fields):
            return None

        def advance_batch_run(self, run_id, **fields):
            return None

        def finish_batch_run(self, run_id, **fields):
            self.finished = fields

        def persist_search(self, query, groups, **kwargs):
            upserted = modified = 0
            for group in groups:
                for offer in group.get("offers") or []:
                    key = (offer.get("store"), offer.get("product_id"))
                    if key in catalog:
                        catalog[key]["price"] = offer.get("price")
                        modified += 1
                    else:
                        catalog[key] = {"price": offer.get("price"), "name": offer.get("name")}
                        upserted += 1
            return {"upserted": upserted, "modified": modified, "matched": modified}

    def resolve(text):
        if "notebook" in text.casefold():
            return SimpleNamespace(groups=("tecnologia",))
        return None

    repo = Repo()
    summary = run_basic_scrape(
        products=[
            {
                "store": "ahumada",
                "product_id": "1",
                "name": "Paracetamol",
                "last_search_query": "paracetamol",
                "groups": ["farmacias"],
            },
            {
                "store": "cruzverde",
                "product_id": "1b",
                "name": "Paracetamol",
                "last_search_query": "paracetamol",
                "groups": ["farmacias"],
            },
            {
                "store": "pcfactory",
                "product_id": "2",
                "name": "Notebook gamer",
            },
            {
                "store": "ahumada",
                "product_id": "3",
                "name": "Paracetamol 500 mg",
                "last_search_query": "paracetamol 500",
                "groups": ["farmacias"],
            },
            {"store": "liquimoly", "product_id": "4", "name": "Aceite raro xyz"},
        ],
        repo=repo,
        pause=0,
        resolve_fn=resolve,
    )

    assert repo.started["job"] == "scraping_basico"
    assert repo.started["scope"] == "basico"
    assert "grupo" not in repo.started
    assert "tienda" not in repo.started
    assert [row["query"] for row in calls] == ["paracetamol", "Notebook gamer", "paracetamol 500"]
    assert calls[0]["stores"] == ["ahumada", "cruzverde", "salcobrand"]
    assert calls[1]["stores"] == ["pcfactory", "entel", "movistar"]
    assert calls[2]["stores"] == ["ahumada", "cruzverde", "salcobrand"]
    assert all("falabella" not in row["stores"] for row in calls)
    assert all(row["timeout"] == SEARCH_TIMEOUT and row["fresh"] is True for row in calls)
    assert catalog[("ahumada", "para-500")]["price"] == 1490
    assert catalog[("pcfactory", "note-1")]["price"] == 1990
    assert summary["saved_upserted"] == 2
    assert summary["saved_modified"] == 1
    assert summary["skipped"] == 1
    assert repo.finished["status"] == "done"


def test_groups_for_product_skips_unmatched_instead_of_fallback():
    from retail.batch.basic_scrape import groups_for_product

    assert groups_for_product(
        {"name": "iphone 16", "last_search_query": "iphone 16"},
        resolve_fn=lambda text: None,
    ) == []
    assert groups_for_product(
        {"store": "ahumada", "name": "sin indice"},
        resolve_fn=lambda text: None,
    ) == ["farmacias"]
    assert groups_for_product(
        {"store": "falabella", "name": "Tv 55", "groups": ["tecnologia"]},
        resolve_fn=lambda text: SimpleNamespace(groups=("retail", "supermercados")),
    ) == ["tecnologia"]


def test_cron_status_keeps_basic_scrape_apart(monkeypatch):
    from retail.batch.cron_status import build_cron_batch_status

    monkeypatch.setattr("retail.batch.cron_status.list_store_categories", lambda **kwargs: [])
    monkeypatch.setattr("retail.batch.cron_status.list_stores", lambda: [])

    class Repo:
        def latest_batch_runs_by_grupo(self):
            return {}

        def latest_batch_runs_by_tienda(self):
            return {}

        def latest_batch_run_by_job(self, job):
            assert job == "scraping_basico"
            return {
                "status": "running",
                "processed": 1,
                "items": 4,
                "saved_upserted": 2,
                "saved_modified": 1,
                "skipped": 0,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

    payload = build_cron_batch_status(repo=Repo())
    assert payload["basic_scrape"]["status"] == "running"
    assert payload["any_running"] is True
    assert payload["groups"] == []
    assert payload["store_jobs"] == []
    assert payload["basic_scrape"]["progress"]["new"] == 2
    assert payload["basic_scrape"]["progress"]["updated"] == 1
    assert payload["basic_scrape"]["progress"]["processed"] == 1


def test_iter_stored_products_closes_each_page_before_yielding():
    """Un cursor vivo entre productos expira y Mongo responde CursorNotFound."""
    from retail.mongo import ProductRepository

    class Cursor:
        live = 0

        def __init__(self, docs):
            self.docs = list(docs)
            self.limit_n = None

        def sort(self, key, direction):
            assert (key, direction) == ("_id", 1)
            self.docs.sort(key=lambda item: item["_id"])
            return self

        def limit(self, count):
            self.limit_n = count
            return self

        def __iter__(self):
            Cursor.live += 1
            try:
                yield from self.docs[: self.limit_n]
            finally:
                pass

        def close(self):
            Cursor.live -= 1

    class Collection:
        def __init__(self, docs):
            self.docs = docs
            self.queries = []

        def find(self, query, projection=None):
            assert projection is not None
            assert "_id" not in projection or projection.get("_id") != 0
            self.queries.append(query)
            last = (query.get("_id") or {}).get("$gt")
            matched = [dict(doc) for doc in self.docs if last is None or doc["_id"] > last]
            return Cursor(matched)

    docs = [{"_id": index, "store": "falabella", "product_id": f"p{index}", "name": f"Producto {index}"} for index in range(1, 6)]
    repo = ProductRepository.__new__(ProductRepository)
    repo.collection = Collection(docs)
    Cursor.live = 0

    seen = []
    for item in repo.iter_stored_products(page_size=2):
        assert Cursor.live == 0
        assert item["_id"] in {1, 2, 3, 4, 5}
        seen.append(item["product_id"])

    assert seen == ["p1", "p2", "p3", "p4", "p5"]
    assert repo.collection.queries == [{}, {"_id": {"$gt": 2}}, {"_id": {"$gt": 4}}, {"_id": {"$gt": 5}}]
    assert Cursor.live == 0


def test_iter_stored_products_can_resume_after_id():
    from retail.mongo import ProductRepository

    class Cursor:
        def __init__(self, docs):
            self.docs = list(docs)
            self.limit_n = None

        def sort(self, key, direction):
            self.docs.sort(key=lambda item: item["_id"])
            return self

        def limit(self, count):
            self.limit_n = count
            return self

        def __iter__(self):
            yield from self.docs[: self.limit_n]

        def close(self):
            return None

    class Collection:
        def __init__(self, docs):
            self.docs = docs
            self.queries = []

        def find(self, query, projection=None):
            self.queries.append(query)
            last = (query.get("_id") or {}).get("$gt")
            matched = [dict(doc) for doc in self.docs if last is None or doc["_id"] > last]
            return Cursor(matched)

    docs = [{"_id": index, "product_id": f"p{index}"} for index in range(1, 6)]
    repo = ProductRepository.__new__(ProductRepository)
    repo.collection = Collection(docs)
    seen = [item["product_id"] for item in repo.iter_stored_products(page_size=10, after_id=2)]
    assert seen == ["p3", "p4", "p5"]
    assert repo.collection.queries == [{"_id": {"$gt": 2}}, {"_id": {"$gt": 5}}]


def test_resolve_basic_resume_after_uses_run_or_offset():
    from retail.batch.basic_scrape import BasicScrapeNothingToResume, resolve_basic_resume_after

    repo = SimpleNamespace(
        basic_scrape_cursor=lambda: None,
        product_id_at_offset=lambda offset: f"id-{offset}",
    )
    assert resolve_basic_resume_after(repo, {"resume_after_id": "abc"}) == "abc"
    assert resolve_basic_resume_after(repo, {"processed": 480}) == "id-479"
    try:
        resolve_basic_resume_after(repo, {"processed": 0})
        raised = False
    except BasicScrapeNothingToResume:
        raised = True
    assert raised
