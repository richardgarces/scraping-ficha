from retail.registry import STORE_GROUP, list_stores
from retail.sources.dondelanegra import listing_item_to_product, parse_dondelanegra_target


def test_dondelanegra_registrada_y_agrupada():
    specs = [spec for spec in list_stores() if spec.id == "dondelanegra"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.title == "Donde La Negra"
    assert spec.group == "gastronomia"
    assert spec.platform == "custom"
    assert STORE_GROUP["dondelanegra"] == "gastronomia"
    assert len({item.id for item in list_stores()}) == len(list_stores())


def test_parse_dondelanegra_targets():
    assert parse_dondelanegra_target("pisco").kind == "search"
    assert parse_dondelanegra_target("pisco").query == "pisco"
    search = parse_dondelanegra_target("https://dondelanegra.cl/buscar/?q=whisky")
    assert search.kind == "search"
    assert search.query == "whisky"
    product = parse_dondelanegra_target(
        "https://dondelanegra.cl/producto/alto-del-carmen-35o-1l/"
    )
    assert product.kind == "product"
    assert product.product_id == "alto-del-carmen-35o-1l"
    category = parse_dondelanegra_target(
        "https://dondelanegra.cl/categoria-producto/pisco/"
    )
    assert category.kind == "category"
    assert category.category_id == "pisco"
    assert category.category_name == "categoria"
    brand = parse_dondelanegra_target("https://dondelanegra.cl/marca/glenmorangie/")
    assert brand.kind == "category"
    assert brand.category_id == "glenmorangie"
    assert brand.category_name == "marca"


def test_dondelanegra_listing_card_to_product():
    product = listing_item_to_product(
        {
            "id": 1749,
            "name": "Pisco Alto del Carmen 35º 1L",
            "slug": "alto-del-carmen-35o-1l",
            "sku": "DP00106",
            "price": "6990",
            "sale_price": "5790",
            "permalink": "https://dondelanegra.cl/producto/alto-del-carmen-35o-1l/",
            "images": [{"src": "/images/products/1749_0_alto-1l.jpg"}],
            "categories": [{"id": 2, "name": "Pisco", "slug": "pisco"}],
        },
        source="search",
    )
    assert product.store == "dondelanegra"
    assert product.product_id == "alto-del-carmen-35o-1l"
    assert product.sku_id == "DP00106"
    assert product.name == "Pisco Alto del Carmen 35º 1L"
    assert product.price == 5790
    assert product.price_normal == 6990
    assert product.discount_percent == 17
    assert product.url == "https://dondelanegra.cl/producto/alto-del-carmen-35o-1l/"
    assert product.image_url == "https://dashboard.dondelanegra.cl/images/products/1749_0_alto-1l.jpg"
    assert product.category == "Pisco"
    assert product.seller == "Donde La Negra"
