from retail.registry import STORE_GROUP, list_stores
from retail.sources.braloy import listing_item_to_product as braloy_product
from retail.sources.braloy import parse_braloy_target
from retail.sources.hites import parse_hites_grid, parse_hites_target

NEW_STORES = {
    "dimarsa": ("retail", "vtex"),
    "hites": ("retail", "sfcc"),
    "privilege": ("moda", "vtex"),
    "edelbrock": ("moda", "shopify"),
    "fensa": ("hogar", "vtex"),
    "indumac": ("hogar", "woocommerce"),
    "homemobili": ("hogar", "shopify"),
    "thorben": ("hogar", "shopify"),
    "stoked": ("deporte", "magento"),
    "hp": ("tecnologia", "magento"),
    "garmin": ("tecnologia", "shopify"),
    "productosdelujo": ("belleza", "shopify"),
    "nooki": ("belleza", "shopify"),
    "cosmetic": ("belleza", "shopify"),
    "lodoro": ("belleza", "shopify"),
    "vadell": ("juguetes", "shopify"),
    "playmore": ("juguetes", "shopify"),
    "apro": ("ferreteria", "shopify"),
    "safetystore": ("ferreteria", "shopify"),
    "braloy": ("otros", "prestashop"),
}


def test_directorio_ids_unicos_y_agrupados():
    specs = {spec.id: spec for spec in list_stores()}
    assert len(specs) == len(list_stores())
    assert "masisa" in specs
    assert "knasta" in specs
    assert "dondelanegra" in specs
    for store_id, (group, platform) in NEW_STORES.items():
        assert store_id in specs, store_id
        assert STORE_GROUP[store_id] == group
        assert specs[store_id].platform == platform
        assert specs[store_id].group in {None, group}


def test_parse_hites_search_and_grid():
    assert parse_hites_target("televisor").kind == "search"
    product = parse_hites_target(
        "https://www.hites.com/led-50-samsung-978689001.html"
    )
    assert product.kind == "product"
    assert product.product_id == "978689001"
    html = (
        '<a href="/led-50-samsung-978689001.html"></a>'
        '<img class="js-image1" src="https://www.hites.com/dw/image/pim/978689001/978689001_1.jpg?sw=306&amp;sh=306">'
        '<img class="js-image2" src="https://www.hites.com/dw/image/pim/978689001/978689001_2.jpg?sw=306&amp;sh=306">'
        '<div data-gtmselectitem="{&quot;item_id&quot;:&quot;978689001&quot;,'
        '&quot;value&quot;:279990,&quot;item&quot;:{&quot;item_id&quot;:&quot;978689001&quot;,'
        '&quot;item_name&quot;:&quot;Led 50 Samsung&quot;,&quot;item_brand&quot;:&quot;Samsung&quot;,'
        '&quot;item_category&quot;:&quot;Televisores&quot;,&quot;price&quot;:279990,'
        '&quot;discount&quot;:130000}}"></div>'
    )
    rows = parse_hites_grid(html)
    assert len(rows) == 1
    assert rows[0]["name"] == "Led 50 Samsung"
    assert rows[0]["price"] == 279990
    assert rows[0]["price_normal"] == 409990
    assert rows[0]["url"].endswith("/led-50-samsung-978689001.html")
    assert rows[0]["image"] == "https://www.hites.com/dw/image/pim/978689001/978689001_1.jpg?sw=306&sh=306"


def test_hites_uses_first_variant_image_when_item_id_is_shorter():
    html = (
        '<a href="/zapatilla-953407.html"></a>'
        '<img class="js-image1" src="https://www.hites.com/dw/image/pim/953407008/953407008_1.jpg">'
        '<img class="js-image2" src="https://www.hites.com/dw/image/pim/953407008/953407008_2.jpg">'
        '<div data-gtmselectitem="{&quot;item&quot;:{&quot;item_id&quot;:&quot;953407001&quot;,'
        '&quot;item_name&quot;:&quot;Zapatilla&quot;,&quot;price&quot;:49990}}"></div>'
    )
    rows = parse_hites_grid(html)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://www.hites.com/zapatilla-953407.html"
    assert rows[0]["image"].endswith("953407008_1.jpg")


def test_parse_braloy_search_and_price():
    assert parse_braloy_target("alimento").kind == "search"
    product = parse_braloy_target(
        "https://braloy.cl/inicio/8067-barfood-lacena.html"
    )
    assert product.kind == "product"
    assert product.product_id == "8067"
    category = parse_braloy_target("https://braloy.cl/201-accesorios")
    assert category.kind == "category"
    assert category.category_id == "201-accesorios"
    found = braloy_product(
        {
            "id_product": "8067",
            "name": "Barfood Lacena Alimento Humedo Perro 300 grs.",
            "manufacturer_name": "Barfood",
            "price_amount": 3490,
            "regular_price_amount": 4990,
            "canonical_url": "https://braloy.cl/inicio/8067-barfood-lacena.html",
            "reference": "6797322867605",
        }
    )
    assert found.store == "braloy"
    assert found.price == 3490
    assert found.price_normal == 4990
    assert found.url.endswith("8067-barfood-lacena.html")
