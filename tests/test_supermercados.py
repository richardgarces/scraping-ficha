from retail.registry import list_stores
from retail.sources.alvi import listing_item_to_product as alvi_product
from retail.sources.alvi import parse_alvi_target
from retail.sources.cugat import listing_item_to_product as cugat_product
from retail.sources.cugat import parse_cugat_target
from retail.sources.unimarc import listing_item_to_product as unimarc_product
from retail.sources.unimarc import parse_unimarc_target


def test_supermercados_nuevos_estan_registrados():
    ids = {spec.id for spec in list_stores()}
    assert {"unimarc", "alvi", "cugat", "lider", "tottus"} <= ids


def test_parse_unimarc_search_and_product():
    assert parse_unimarc_target("leche colun").kind == "search"
    target = parse_unimarc_target(
        "https://www.unimarc.cl/leche-entera-natural-con-tapa-soprole-1-l/p"
    )
    assert target.kind == "product"
    assert target.product_id == "leche-entera-natural-con-tapa-soprole-1-l"


def test_unimarc_listing_prices():
    product = unimarc_product(
        {
            "price": {"price": "$1.180", "listPrice": "$1.220"},
            "item": {
                "productId": "1945",
                "itemId": "1945",
                "sku": "1945",
                "name": "Leche Soprole entera natural 1 L",
                "brand": "Soprole",
                "ean": "7802900001308",
                "slug": "/leche-entera-natural-con-tapa-soprole-1-l/p",
                "images": ["https://img/leche.png"],
                "categories": ["/Lácteos/Leches líquidas/"],
                "categoryId": "66",
            },
        }
    )
    assert product.store == "unimarc"
    assert product.price == 1180
    assert product.price_normal == 1220
    assert product.url.endswith("/leche-entera-natural-con-tapa-soprole-1-l/p")
    assert product.specifications["ean"] == "7802900001308"


def test_parse_alvi_and_prices():
    assert parse_alvi_target("leche").kind == "search"
    product = alvi_product(
        {
            "productId": "1945",
            "itemId": "1945",
            "sku": "1945",
            "name": "Leche Soprole entera natural 1 L",
            "brand": "Soprole",
            "ean": "7802900001308",
            "detailUrl": "/leche-entera-natural-con-tapa-soprole-1-l/p",
            "images": ["https://img/leche.jpg"],
            "categories": ["/Lácteos, refrigerados y huevos/Leches líquidas/"],
            "categoryId": "66",
            "sellers": [{"sellerId": "1", "sellerName": "Alvi", "price": 1180, "listPrice": 1220}],
        }
    )
    assert product.store == "alvi"
    assert product.price == 1180
    assert product.price_normal == 1220
    assert product.seller == "Alvi"


def test_parse_cugat_and_prices():
    target = parse_cugat_target(
        "https://cugat.cl/producto/leche-instantanea-entera-calo-bolsa-1440g/"
    )
    assert target.kind == "product"
    assert target.product_id == "leche-instantanea-entera-calo-bolsa-1440g"
    assert parse_cugat_target("leche").kind == "search"
    product = cugat_product(
        {
            "id": 91818,
            "name": "Leche instantánea entera Calo 26% bolsa 1440g",
            "permalink": "https://cugat.cl/producto/leche-instantanea-entera-calo-bolsa-1440g/",
            "sku": "7802910007970",
            "prices": {
                "price": "11990",
                "regular_price": "12990",
                "sale_price": "11990",
                "currency_minor_unit": 0,
            },
            "images": [{"src": "https://img/calo.jpg"}],
        }
    )
    assert product.store == "cugat"
    assert product.price == 11990
    assert product.price_normal == 12990
    assert product.specifications["ean"] == "7802910007970"
