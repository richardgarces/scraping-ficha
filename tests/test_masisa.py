import json

from retail.platforms.vtex import listing_item_to_product
from retail.registry import STORE_GROUP, get_client, list_stores
from retail.sources.masisa import parse_masisa_target


def test_masisa_registrada_y_agrupada():
    specs = [spec for spec in list_stores() if spec.id == "masisa"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.title == "Masisa"
    assert spec.group == "hogar"
    assert spec.platform == "vtex"
    assert STORE_GROUP["masisa"] == "hogar"
    assert len({item.id for item in list_stores()}) == len(list_stores())


def test_parse_masisa_targets():
    assert parse_masisa_target("velador").kind == "search"
    assert parse_masisa_target("velador").query == "velador"
    product = parse_masisa_target(
        "https://tienda.masisa.com/velador-villarrica-bosco-puerta-gris-grafito/p"
    )
    assert product.kind == "product"
    assert product.product_id == "velador-villarrica-bosco-puerta-gris-grafito"
    category = parse_masisa_target("muebles-a-pedido/dormitorio/veladores")
    assert category.kind == "category"
    assert category.category_id == "muebles-a-pedido/dormitorio/veladores"


def test_masisa_listing_keeps_numeric_price():
    product = listing_item_to_product(
        {
            "productId": "107",
            "productName": "Velador Villarrica Doble - (Bosco - Gris Grafito)",
            "brand": "Masisa®",
            "linkText": "velador-villarrica-bosco-puerta-gris-grafito",
            "categories": ["/Muebles a Pedido/Dormitorio/Veladores/"],
            "items": [
                {
                    "itemId": "107",
                    "sellers": [
                        {
                            "sellerName": "Masisa - CL",
                            "commertialOffer": {"Price": 59990.0, "ListPrice": 79990.0},
                        }
                    ],
                    "images": [],
                }
            ],
        },
        store_id="masisa",
        base="https://tienda.masisa.com",
    )
    assert product.store == "masisa"
    assert product.price == 59990
    assert product.price_normal == 79990
    assert product.name.startswith("Velador Villarrica Doble")
    assert product.url == (
        "https://tienda.masisa.com/velador-villarrica-bosco-puerta-gris-grafito/p"
    )


def test_masisa_product_url_falls_back_to_catalog_path(monkeypatch):
    payload = [
        {
            "productId": "107",
            "productName": "Velador Villarrica Doble - (Bosco - Gris Grafito)",
            "linkText": "velador-villarrica-bosco-puerta-gris-grafito",
            "items": [
                {
                    "itemId": "107",
                    "sellers": [
                        {
                            "sellerName": "Masisa - CL",
                            "commertialOffer": {"Price": 59990, "ListPrice": 79990},
                        }
                    ],
                    "images": [],
                }
            ],
        }
    ]
    seen: list[str] = []

    def fake_get(url, params=None):
        seen.append(url)
        if "/velador-villarrica-bosco-puerta-gris-grafito/p?" in url:
            return 200, "application/json", json.dumps(payload)
        return 200, "application/json", "[]"

    client = get_client("masisa", delay=0, timeout=1, retries=1)
    try:
        monkeypatch.setattr(client.http, "get", fake_get)
        found = client.scrape(
            "https://tienda.masisa.com/velador-villarrica-bosco-puerta-gris-grafito/p",
            max_items=1,
        )
    finally:
        client.close()
    assert len(found) == 1
    assert found[0].price == 59990
    assert found[0].url.endswith("/velador-villarrica-bosco-puerta-gris-grafito/p")
    assert any("/velador-villarrica-bosco-puerta-gris-grafito/p?" in url for url in seen)
