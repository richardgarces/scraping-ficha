from retail.registry import STORE_GROUP, list_stores
from retail.sources.pesaschile import listing_item_to_product, parse_pesaschile_target

NEW_STORES = {
    "block": ("calzado", "shopify"),
    "pesaschile": ("deporte", "prestashop"),
    "mennt": ("moda", "shopify"),
    "starsex": ("belleza", "shopify"),
    "azedan": ("otros", "woocommerce"),
    "scaldasonno": ("hogar", "shopify"),
    "fabricadevelas": ("hogar", "shopify"),
    "zagg": ("tecnologia", "shopify"),
    "juanvaldez": ("gastronomia", "shopify"),
    "daher": ("otros", "woocommerce"),
    "neumax": ("otros", "woocommerce"),
    "thelab": ("opticas", "shopify"),
    "vincenzi": ("hogar", "shopify"),
    "sharkninja": ("hogar", "shopify"),
    "atakama": ("deporte", "shopify"),
    "nuvac": ("hogar", "woocommerce"),
    "mademsa": ("hogar", "vtex"),
    "toyotomi": ("hogar", "woocommerce"),
    "vitepal": ("ferreteria", "magento"),
    "trek": ("deporte", "magento"),
    "fox": ("deporte", "shopify"),
}

KEEP = (
    "masisa",
    "knasta",
    "dondelanegra",
    "dimarsa",
    "hites",
    "privilege",
    "edelbrock",
    "fensa",
    "indumac",
    "homemobili",
    "thorben",
    "stoked",
    "hp",
    "garmin",
    "productosdelujo",
    "nooki",
    "cosmetic",
    "lodoro",
    "vadell",
    "playmore",
    "apro",
    "safetystore",
    "braloy",
    "sodimac",
    "levis",
    "ferouch",
    "head",
)


def test_directorio_batch2_ids_unicos_y_agrupados():
    specs = {spec.id: spec for spec in list_stores()}
    assert len(specs) == len(list_stores())
    for store_id in KEEP:
        assert store_id in specs, store_id
    for store_id, (group, platform) in NEW_STORES.items():
        assert store_id in specs, store_id
        assert STORE_GROUP[store_id] == group
        assert specs[store_id].platform == platform
        assert specs[store_id].group in {None, group}


def test_parse_pesaschile_search_and_price():
    assert parse_pesaschile_target("disco").kind == "search"
    product = parse_pesaschile_target(
        "https://pesaschile.cl/categorias/1494-par-discos-olimpicos-grip-rubber-025kg-promachine.html"
    )
    assert product.kind == "product"
    assert product.product_id == "1494"
    found = listing_item_to_product(
        {
            "id_product": "1494",
            "name": "Par Discos Olímpicos Grip Rubber 2.5kg | PROmachine",
            "manufacturer_name": "PROMACHINE",
            "price_amount": 11990,
            "regular_price_amount": 11990,
            "canonical_url": "https://pesaschile.cl/categorias/1494-par-discos-olimpicos.html",
            "reference": "DOP025",
        }
    )
    assert found.store == "pesaschile"
    assert found.price == 11990
    assert found.name.startswith("Par Discos")
    assert found.url.endswith("1494-par-discos-olimpicos.html")
