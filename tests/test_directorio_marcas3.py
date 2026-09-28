from retail.registry import STORE_GROUP, list_stores
from retail.sources.arrow import listing_item_to_product, parse_arrow_target

NEW_STORES = {
    "acqui": ("hogar", "shopify"),
    "americaneagle": ("moda", "vtex"),
    "arrow": ("moda", "prestashop"),
    "calu": ("moda", "magento"),
    "cheflab": ("hogar", "shopify"),
    "coleman": ("deporte", "vtex"),
    "delsey": ("moda", "shopify"),
    "dermotienda": ("belleza", "shopify"),
    "dolcegusto": ("gastronomia", "magento"),
    "dominame": ("belleza", "shopify"),
    "domotiz": ("tecnologia", "shopify"),
    "dpgoutlet": ("moda", "shopify"),
    "ecook": ("gastronomia", "shopify"),
    "etchile": ("tecnologia", "woocommerce"),
    "florsheim": ("calzado", "vtex"),
    "form": ("hogar", "shopify"),
    "hardwork": ("moda", "shopify"),
    "hitway": ("musica", "shopify"),
    "ilgioco": ("moda", "vtex"),
    "infanti": ("infantil", "shopify"),
    "iochile": ("moda", "magento"),
    "ivmedical": ("belleza", "shopify"),
    "kaltemp": ("hogar", "shopify"),
    "kannu": ("deporte", "magento"),
    "kayaunite": ("deporte", "shopify"),
    "kitchenhouse": ("hogar", "shopify"),
    "kotting": ("moda", "magento"),
    "larelojeria": ("relojeria", "shopify"),
    "lechepalpelo": ("belleza", "shopify"),
    "lenceria": ("moda", "shopify"),
    "lineatre": ("moda", "shopify"),
    "magriffe": ("moda", "magento"),
    "mates": ("gastronomia", "shopify"),
    "mayordent": ("belleza", "woocommerce"),
    "mcgregor": ("moda", "magento"),
    "misjoyas": ("moda", "shopify"),
    "outletdelcafe": ("gastronomia", "shopify"),
    "passol": ("ferreteria", "shopify"),
    "pethome": ("otros", "shopify"),
    "petvet": ("otros", "shopify"),
    "pilgrim": ("moda", "shopify"),
    "polyphonik": ("musica", "shopify"),
    "pumasafety": ("ferreteria", "vtex"),
    "pyk": ("otros", "shopify"),
    "rapsodia": ("moda", "magento"),
    "razaspet": ("otros", "woocommerce"),
    "relan": ("hogar", "shopify"),
    "salmonmarket": ("gastronomia", "shopify"),
    "santiagoperfumes": ("belleza", "woocommerce"),
    "softys": ("hogar", "vtex"),
    "sokobox": ("belleza", "shopify"),
    "spazzio": ("hogar", "shopify"),
    "sportingbrands": ("deporte", "shopify"),
    "steelpro": ("ferreteria", "shopify"),
    "tecnored": ("ferreteria", "magento"),
    "theline": ("moda", "vtex"),
    "totto": ("moda", "vtex"),
    "treck": ("ferreteria", "vtex"),
    "tusmascotas": ("otros", "woocommerce"),
    "velez": ("moda", "vtex"),
    "ventus": ("hogar", "vtex"),
    "wados": ("moda", "magento"),
    "womensecret": ("moda", "vtex"),
    "worbee": ("tecnologia", "shopify"),
    "yauras": ("belleza", "shopify"),
    "zoy": ("hogar", "shopify"),
}

KEEP = ("fox", "trek", "mademsa", "masisa", "paris", "lider", "puma", "lippi", "infanti", "movistar")


def test_directorio_batch3_ids_unicos_y_agrupados():
    specs = {spec.id: spec for spec in list_stores()}
    assert len(specs) == len(list_stores())
    for store_id in KEEP:
        assert store_id in specs, store_id
    for store_id, (group, platform) in NEW_STORES.items():
        assert store_id in specs, store_id
        assert STORE_GROUP[store_id] == group
        assert specs[store_id].platform == platform
        assert specs[store_id].group in {None, group}


def test_parse_arrow_search_and_price():
    assert parse_arrow_target("camisa").kind == "search"
    product = parse_arrow_target("https://www.arrow.cl/camisas/12-camisa-casual.html")
    assert product.kind == "product"
    assert product.product_id == "12"
    found = listing_item_to_product(
        {
            "id_product": "88",
            "name": "Camisa Casual A Rayas Arrow",
            "manufacturer_name": "Arrow",
            "price": 26990,
            "canonical_url": "https://www.arrow.cl/camisas/88-camisa-casual.html",
            "reference": "ARW88",
        }
    )
    assert found.store == "arrow"
    assert found.price == 26990
    assert found.name.startswith("Camisa Casual")
    assert found.url.endswith("88-camisa-casual.html")
