from retail.platforms.woocommerce import listing_item_to_product as wc_product
from retail.registry import STORE_GROUP, list_stores
from retail.sources.audiomusica import parse_audiomusica_target
from retail.sources.bodyshop import parse_bodyshop_target
from retail.sources.casaroyal import parse_casaroyal_target
from retail.sources.construplaza import parse_construplaza_target
from retail.sources.dbs import parse_dbs_target
from retail.sources.prat import parse_prat_target
from retail.sources.promusic import parse_promusic_target
from retail.sources.preunic import listing_item_to_product as preunic_product
from retail.sources.preunic import parse_preunic_target
from retail.sources.sallybeauty import parse_sallybeauty_target
from retail.sources.weitzler import parse_weitzler_target


def test_verticales_nuevos_estan_registrados_y_agrupados():
    ids = {spec.id for spec in list_stores()}
    expected = {
        "construplaza": "ferreteria",
        "prat": "ferreteria",
        "weitzler": "ferreteria",
        "audiomusica": "musica",
        "casaroyal": "retail",
        "promusic": "musica",
        "dbs": "belleza",
        "sallybeauty": "belleza",
        "bodyshop": "belleza",
        "lush": "belleza",
        "pichara": "belleza",
        "preunic": "belleza",
        "vans": "calzado",
        "converse": "calzado",
        "puma": "deporte",
        "reebok": "deporte",
        "patagonia": "deporte",
        "asics": "deporte",
        "bebesit": "infantil",
        "opaline": "infantil",
        "ficcus": "infantil",
        "colloky": "infantil",
        "lavinoteca": "gastronomia",
        "mundovino": "gastronomia",
        "gmo": "opticas",
        "swarovski": "relojeria",
        "motorola": "tecnologia",
        "movistar": "tecnologia",
        "entel": "tecnologia",
        "centrale": "tecnologia",
        "oster": "hogar",
        "flex": "hogar",
        "mk": "ferreteria",
        "levis": "moda",
        "trial": "moda",
        "contrapunto": "libreria",
        "dellanatura": "farmacias",
        "dcshoes": "calzado",
        "descorcha": "gastronomia",
        "tika": "gastronomia",
        "janome": "hogar",
        "totaltools": "ferreteria",
        "maui": "moda",
        "ripcurl": "moda",
        "volcom": "moda",
        "gap": "moda",
        "ferouch": "moda",
        "perryellis": "moda",
        "tommy": "moda",
        "hugoboss": "moda",
        "guess": "moda",
        "speedo": "deporte",
        "needle": "musica",
        "ansaldo": "juguetes",
        "toyng": "juguetes",
        "piedrabruja": "juguetes",
        "catalonia": "libreria",
        "nacional": "libreria",
        "etienne": "belleza",
        "petrizzio": "belleza",
        "fdv": "hogar",
        "amesti": "ferreteria",
        "dartel": "ferreteria",
        "liquimoly": "otros",
        "chileautos": "autos",
        "autocosmos": "autos",
    }
    assert expected.keys() <= ids
    for store_id, group in expected.items():
        assert STORE_GROUP[store_id] == group


def test_parse_ferreteria_targets():
    assert parse_construplaza_target("taladro").kind == "search"
    product = parse_construplaza_target(
        "https://www.construplaza.cl/taladro-bosch/p"
    )
    assert product.kind == "product"
    assert product.product_id == "taladro-bosch"
    assert parse_prat_target("taladro").kind == "search"
    prat = parse_prat_target("https://www.ferreteriaprat.cl/products/taladro-13mm")
    assert prat.kind == "product"
    assert prat.product_id == "taladro-13mm"
    assert parse_weitzler_target("taladro").kind == "search"
    weitzler = parse_weitzler_target(
        "https://www.weitzler.cl/producto/taladro-percutor/"
    )
    assert weitzler.kind == "product"
    assert weitzler.product_id == "taladro-percutor"


def test_parse_musica_targets():
    assert parse_audiomusica_target("guitarra").kind == "search"
    assert parse_casaroyal_target("guitarra").kind == "search"
    assert parse_promusic_target("guitarra").kind == "search"
    guitar = parse_audiomusica_target(
        "https://www.audiomusica.com/guitarra-clasica/p"
    )
    assert guitar.kind == "product"
    assert guitar.product_id == "guitarra-clasica"
    promo = parse_promusic_target("https://www.promusic.cl/products/ukelele")
    assert promo.kind == "product"
    assert promo.product_id == "ukelele"


def test_parse_belleza_targets():
    assert parse_dbs_target("labial").kind == "search"
    assert parse_sallybeauty_target("labial").kind == "search"
    assert parse_bodyshop_target("crema").kind == "search"
    body = parse_bodyshop_target(
        "https://www.thebodyshop.cl/producto/tea-tree-skin-lotion/"
    )
    assert body.kind == "product"
    assert body.product_id == "tea-tree-skin-lotion"
    assert parse_preunic_target("crema").kind == "search"
    assert parse_preunic_target("593717").kind == "product"
    product = parse_preunic_target(
        "https://preunic.cl/products/crema-corporal-nivea-body-milk-soft-100ml"
    )
    assert product.kind == "product"
    assert product.product_id == "crema-corporal-nivea-body-milk-soft-100ml"
    category = parse_preunic_target("https://preunic.cl/t/maquillaje")
    assert category.kind == "category"
    assert category.category_id == "maquillaje"


def test_woocommerce_listing_prices_for_verticales():
    product = wc_product(
        {
            "id": 42,
            "name": "Taladro percutor 13 mm",
            "permalink": "https://www.weitzler.cl/producto/taladro-percutor/",
            "sku": "7801234567890",
            "prices": {
                "price": "49990",
                "regular_price": "59990",
                "sale_price": "49990",
                "currency_minor_unit": 0,
            },
            "images": [{"src": "https://img/taladro.jpg"}],
        },
        store_id="weitzler",
        seller="Weitzler",
    )
    assert product.store == "weitzler"
    assert product.price == 49990
    assert product.price_normal == 59990
    assert product.specifications["ean"] == "7801234567890"


def test_preunic_listing_prices():
    product = preunic_product(
        {
            "id": "593578",
            "sku": "593578",
            "name": "Crema Corporal Nivea Regeneración Intensiva Piel Sensible y Extra Seca 400ml",
            "brand": "NIVEA",
            "slug": "crema-corporal-nivea-regeneracion-intensiva-piel-sensible-y-extra-seca-400ml",
            "price": 8999,
            "offerPrice": 4949,
            "cardPrice": 4050,
            "image": "https://static.preunic.cl/img",
            "categories": ["Cuidado Corporal"],
            "__prices": {"current": {"value": 4949}, "previous": {"value": 8999}},
        }
    )
    assert product.store == "preunic"
    assert product.price == 4949
    assert product.price_internet == 4949
    assert product.price_normal == 8999
    assert product.price_cmr == 4050
    assert product.discount_percent == 45
    assert product.url == (
        "https://preunic.cl/products/"
        "crema-corporal-nivea-regeneracion-intensiva-piel-sensible-y-extra-seca-400ml"
    )
