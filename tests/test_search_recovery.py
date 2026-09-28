from types import SimpleNamespace

from retail.models import Product
from retail.qdrant_index import QdrantIndex
from retail.search import DB_RECOVERY_MIN_RESULTS, search_products


class _Repo:
    def __init__(self, rows):
        self.rows = rows

    def ping(self):
        return True

    def close(self):
        return None

    def find_by_query(self, query):
        return list(self.rows)

    def histories(self, keys):
        return {}

    def thumb_flags(self, keys):
        return set()


class _Qdrant:
    def __init__(self):
        self.indexed = []

    def upsert_products(self, products, query=None):
        self.indexed.extend(products)
        return len(products)

    def search(self, query, limit=80):
        return []

    def scores_for(self, query, products):
        return {}

    def category_candidates(self, query, limit=40):
        return [
            {
                "category": "Tecnología",
                "score": 0.91,
                "hits": 4,
                "stores": ["pcfactory"],
            }
        ]


def _product(store, ident, *, category=None, catalog_category=None):
    return Product(
        product_id=ident,
        sku_id=ident,
        name="Notebook gamer RTX",
        store=store,
        price=799_990,
        category=category,
        catalog_category=catalog_category,
    )


def test_qdrant_category_candidates_aggregate_payload_categories():
    hits = [
        SimpleNamespace(
            score=0.92,
            payload={"catalog_category": "Tecnología", "category": "Notebooks", "store": "pcfactory"},
        ),
        SimpleNamespace(
            score=0.81,
            payload={"catalog_category": "Tecnología", "category": "Computación", "store": "falabella"},
        ),
    ]
    client = SimpleNamespace(
        query_points=lambda **kwargs: SimpleNamespace(points=hits),
    )

    categories = QdrantIndex(client).category_candidates("notebook gamer")

    tecnologia = next(item for item in categories if item["category"] == "Tecnología")
    assert tecnologia["hits"] == 2
    assert tecnologia["stores"] == ["falabella", "pcfactory"]
    assert tecnologia["score"] == 0.92


def test_qdrant_product_payload_keeps_store_and_catalog_categories():
    captured = {}

    def upsert(**kwargs):
        captured.update(kwargs)

    index = QdrantIndex(SimpleNamespace(upsert=upsert))
    product = _product(
        "pcfactory",
        "notebook-1",
        category="Computación / Notebooks",
        catalog_category="Tecnología",
    )

    assert index.upsert_products([product], query="notebook gamer") == 1
    payload = captured["points"][0].payload
    assert payload["category"] == "Computación / Notebooks"
    assert payload["catalog_category"] == "Tecnología"
    assert payload["store"] == "pcfactory"


def test_db_search_under_ten_scrapes_stores_in_inferred_category(monkeypatch):
    mongo_row = _product("falabella", "mongo-1").to_dict(flatten_specs=False)
    repo = _Repo([mongo_row])
    qdrant = _Qdrant()
    calls = []

    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: qdrant)
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)

    def scrape(store_id, query, **kwargs):
        calls.append(store_id)
        return [_product(store_id, f"live-{store_id}")], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)

    result = search_products(
        "notebook gamer",
        source="db",
        stores=["falabella", "pcfactory"],
        max_items=10,
        persist=False,
        delay=0,
        timeout=1,
        background_side_effects=False,
        wait_for_all=True,
    )

    assert DB_RECOVERY_MIN_RESULTS == 10
    assert calls == ["pcfactory"]
    assert result["recovery"]["triggered"] is True
    assert result["recovery"]["initial_count"] == 1
    assert result["recovery"]["categories"] == ["Tecnología"]
    assert qdrant.indexed[0].product_id == "mongo-1"
    live = next(row for row in result["rows"] if row["store"] == "pcfactory")
    assert live["catalog_category"] == "Tecnología"


def test_underfilled_recovery_cache_prevents_repeated_scraping(monkeypatch):
    cached = {
        "query": "producto escaso",
        "offer_count": 2,
        "groups": [],
        "rows": [],
        "progress": [],
        "recovery": {"triggered": True, "initial_count": 0, "stores": ["pcfactory"]},
    }
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: cached)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr(
        "retail.search.connect_repo",
        lambda: (_ for _ in ()).throw(AssertionError("no debe volver a consultar ni scrapear")),
    )

    result = search_products(
        "producto escaso",
        source="db",
        stores=["pcfactory"],
        persist=False,
    )

    assert result["offer_count"] == 2
    assert result["recovery"]["triggered"] is True


def test_quick_db_search_never_scrapes_without_user_confirmation(monkeypatch):
    mongo_row = _product("falabella", "mongo-quick").to_dict(flatten_specs=False)
    repo = _Repo([mongo_row])
    calls = []

    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: _Qdrant())
    monkeypatch.setattr("retail.search.claim_unique_sweep", lambda *args, **kwargs: False)
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)
    monkeypatch.setattr("retail.search.scrape_store", lambda *args, **kwargs: calls.append(args[0]))

    result = search_products(
        "notebook gamer",
        source="db",
        stores=["falabella", "pcfactory"],
        persist=False,
        background_side_effects=False,
        wait_for_all=True,
        recover_underfilled_db=False,
    )

    assert calls == []
    assert "recovery" not in result
    assert result["offer_count"] == 1
