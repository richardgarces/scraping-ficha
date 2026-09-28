from urllib.parse import unquote

from retail.platforms.vtex import encode_vtex_query, normalize_vtex_ft
from retail.registry import STORE_GROUP, get_client, list_stores


def test_vtex_ft_encodes_spaces_as_percent_20():
    assert normalize_vtex_ft("  mini   led ") == "mini led"
    encoded = encode_vtex_query({"ft": "mini led", "_from": 0, "_to": 9})
    assert "ft=mini%20led" in encoded
    assert "mini led" not in encoded
    assert "+" not in encoded.split("ft=", 1)[1].split("&", 1)[0]
    assert unquote("mini%20led") == "mini led"


def test_vtex_space_query_does_not_400(monkeypatch):
    seen: list[tuple[str, object]] = []

    def fake_get(url, params=None):
        seen.append((url, params))
        return 200, "application/json", "[]"

    client = get_client("nike", delay=0, timeout=1, retries=1)
    try:
        monkeypatch.setattr(client.http, "get", fake_get)
        found = client.scrape("mini led", max_pages=1, max_items=3)
    finally:
        client.close()
    assert found == []
    assert seen
    url, params = seen[0]
    assert params in (None, {})
    assert "ft=mini%20led" in url
    assert "mini led" not in url


def test_casaroyal_registrada_en_retail_con_intelligent_search(monkeypatch):
    by_id = {spec.id: spec for spec in list_stores()}
    assert "casaroyal" in by_id
    assert by_id["casaroyal"].title == "Casa Royal"
    assert by_id["casaroyal"].platform == "vtex"
    assert STORE_GROUP["casaroyal"] == "retail"

    seen: list[tuple[str, object]] = []

    def fake_get(url, params=None):
        seen.append((url, params))
        return (
            200,
            "application/json",
            '{"products":[{"productId":"1","productName":"Guitarra test","linkText":"guitarra-test","items":[{"itemId":"1","sellers":[{"sellerName":"Casa Royal","commertialOffer":{"Price":1000,"ListPrice":1200}}],"images":[]}]}]}',
        )

    client = get_client("casaroyal", delay=0, timeout=1, retries=1)
    try:
        monkeypatch.setattr(client.http, "get", fake_get)
        found = client.scrape("guitarra", max_pages=1, max_items=3)
    finally:
        client.close()
    assert len(found) == 1
    assert found[0].name == "Guitarra test"
    assert found[0].store == "casaroyal"
    assert seen
    url, params = seen[0]
    assert "intelligent-search/product_search" in url
    assert isinstance(params, dict)
    assert params.get("query") == "guitarra"
