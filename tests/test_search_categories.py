from retail.models import Product
from retail.search import scrape_category_probes


def _salt(store):
    return Product(store=store, product_id=f"sal-{store}", sku_id="sal", name="Sal de mesa", price=990)


def test_empty_probe_skips_remaining_category_and_continues(monkeypatch):
    calls = []

    def scrape(store, query, **kwargs):
        calls.append(store)
        return ([_salt(store)] if store == "lider" else []), None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    found, errors, skipped = scrape_category_probes(
        "sal", ["azaleia", "cardinale", "vans", "ansaldo", "toyng", "lider", "tottus"], delay=0,
    )
    assert set(calls) == {"azaleia", "ansaldo", "lider", "tottus"}
    assert set(skipped) == {"cardinale", "vans", "toyng"}
    assert found["lider"][0].name == "Sal de mesa"
    assert found["azaleia"] == []
    assert not errors


def test_unrelated_products_do_not_open_the_category(monkeypatch):
    calls = []

    def scrape(store, query, **kwargs):
        calls.append(store)
        return [Product(store=store, product_id="shoe", sku_id="shoe", name="Zapatillas Nike Air", price=50000)], None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    _, _, skipped = scrape_category_probes("sal", ["azaleia", "vans"], delay=0)
    assert calls == ["azaleia"]
    assert skipped == ["vans"]


def test_failed_probe_tries_next_store_instead_of_skipping(monkeypatch):
    calls = []

    def scrape(store, query, **kwargs):
        calls.append(store)
        return ([], "timeout") if store == "azaleia" else ([_salt(store)], None)

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    found, errors, skipped = scrape_category_probes("sal", ["azaleia", "cardinale", "vans"], delay=0)
    assert set(calls) == {"azaleia", "cardinale", "vans"}
    assert "azaleia" not in found
    assert errors == [{"store": "azaleia", "error": "timeout"}]
    assert not skipped


def test_department_stores_are_not_skipped_on_one_empty_result(monkeypatch):
    calls = []
    monkeypatch.setattr("retail.search.scrape_store", lambda store, *args, **kwargs: (calls.append(store) or [], None))
    _, _, skipped = scrape_category_probes("sal", ["falabella", "paris", "ripley"], delay=0)
    assert set(calls) == {"falabella", "paris", "ripley"}
    assert skipped == []


def test_salt_index_targets_categories_and_keeps_all_their_stores(monkeypatch):
    from retail.index.products import stores_for
    from retail.registry import list_stores
    from retail.search import search_products

    selected = stores_for("sal", [store.id for store in list_stores()], client=False)
    assert {"lider", "unimarc", "ahumada"}.issubset(selected)
    assert not {"azaleia", "vans", "ansaldo", "pcfactory"}.intersection(selected)

    calls = []
    monkeypatch.setattr("retail.search.resolve_search_query", lambda query: query)
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    monkeypatch.setattr("retail.search.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search.lookup_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.lookup_store_products", lambda *args, **kwargs: {})
    monkeypatch.setattr("retail.search.store_search_result", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.search.store_store_products", lambda *args, **kwargs: None)
    monkeypatch.setattr("retail.index.products.connect_redis", lambda: None)

    def scrape(store, query, **kwargs):
        calls.append(store)
        return ([_salt(store)] if store == "unimarc" else []), None

    monkeypatch.setattr("retail.search.scrape_store", scrape)
    result = search_products(
        "sal", stores=["lider", "tottus", "unimarc"], source="scrape", delay=0,
        persist=False, background_side_effects=False, wait_for_all=True,
    )
    assert set(calls) == {"lider", "tottus", "unimarc"}
    assert result["offer_count"] == 1
