from urllib.parse import quote

from retail.registry import STORE_GROUP, list_stores
from retail.sources.knasta import listing_item_to_product, parse_knasta_target
from retail.store_display import display_store


def test_knasta_registrada_y_agrupada():
    specs = [spec for spec in list_stores() if spec.id == "knasta"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.title == "Otro"
    assert spec.group == "retail"
    assert spec.platform == "custom"
    assert STORE_GROUP["knasta"] == "retail"


def test_parse_knasta_targets():
    assert parse_knasta_target("notebook").kind == "search"
    assert parse_knasta_target("notebook").query == "notebook"
    search = parse_knasta_target("https://knasta.cl/results?q=tv")
    assert search.kind == "search"
    assert search.query == "tv"
    filtered = parse_knasta_target("https://knasta.cl/results/tecnologia?q=notebook")
    assert filtered.kind == "search"
    assert filtered.query == "notebook"
    assert filtered.category_id == "tecnologia"
    category = parse_knasta_target("https://knasta.cl/results/tecnologia")
    assert category.kind == "category"
    assert category.category_id == "tecnologia"
    numbered = parse_knasta_target("https://knasta.cl/results?category=20497")
    assert numbered.kind == "category"
    assert numbered.category_id == "20497"
    product = parse_knasta_target(
        "https://knasta.cl/detail/falabella/148462172/pack-x3-vestidos"
    )
    assert product.kind == "product"
    assert product.product_id == "falabella#148462172"
    assert parse_knasta_target("lider#00880609588974").kind == "product"


def test_knasta_listing_card_to_product():
    product = listing_item_to_product(
        {
            "kid": "abc#28217455",
            "product_id": "28217455",
            "retail": "abc",
            "retail_label": "Abc",
            "title": 'Smart TV LED 43"" Caixun FHD Google TV',
            "brand": "Caixun",
            "url": "https://www.abc.cl/smart-tv-led-43-caixun-fhd-google-tv-c43v1fg/28217455.html",
            "image": "https://img.example/tv.jpg",
            "current_price": 169990,
            "price_internet": 179990,
            "price_card": 169990,
            "last_variation_price": 199990,
            "rating_average": 4.5,
            "rating_total": 12,
        },
        source="search",
    )
    assert product.store == "knasta"
    assert product.product_id == "abc#28217455"
    assert product.sku_id == "28217455"
    assert product.name == 'Smart TV LED 43" Caixun FHD Google TV'
    assert product.price == 179990
    assert product.price_card == 169990
    assert product.price_internet == 179990
    assert product.price_cmr == 169990
    assert product.price_normal == 199990
    assert product.discount_percent == 10
    assert product.seller == "Abc"
    assert product.brand == "Caixun"
    assert product.url.startswith("https://www.abc.cl/")
    assert product.rating == 4.5
    assert product.reviews == 12


def test_knasta_affiliate_redirect_unwraps_store_url():
    product = listing_item_to_product(
        {
            "kid": "falabella#148462172",
            "product_id": "148462172",
            "retail": "falabella",
            "retail_label": "Falabella",
            "title": "Pack x3 Vestidos",
            "current_price": 15990,
            "url": (
                "/redirect/falabella/148462172/?partner_url="
                + quote(
                    "https://creators.falabella.com/-1wHg?origin=1&dl="
                    + quote(
                        "https://www.falabella.com/falabella-cl/product/148462172/Pack",
                        safe="",
                    ),
                    safe="",
                )
            ),
        }
    )
    assert product.url == "https://www.falabella.com/falabella-cl/product/148462172/Pack"


def test_knasta_muestra_tienda_final_o_otro():
    assert display_store(
        {
            "store": "knasta",
            "seller": "Falabella",
            "url": "https://www.falabella.com/falabella-cl/product/1",
        }
    ) == ("falabella", "Falabella Chile")
    assert display_store({"store": "knasta", "seller": "Abc"}) == ("otro", "Abc")
    assert display_store({"store": "knasta", "url": "https://tienda-ejemplo.cl/producto/1"}) == (
        "otro",
        "Tienda Ejemplo",
    )
    assert display_store({"store": "knasta", "url": "https://knasta.cl/detail/x/1"}) == (
        "otro",
        "Otro",
    )


def test_knasta_nunca_aparece_como_etiqueta_publica():
    from retail.store_display import public_store_key, public_store_label

    assert public_store_key("knasta") == "otro"
    assert public_store_label("knasta") == "Otro"
    assert display_store({"store": "falabella", "store_title": "Knasta"}) == ("falabella", "Otro")
    assert display_store({"store": "paris", "store_title": "Knaste"}) == ("paris", "Otro")
