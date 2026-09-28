from retail.models import Product, sane_discount
from retail.qdrant_index import embed_text
from retail.relevance import filter_relevant, score_product


def _product(name: str, **kwargs) -> Product:
    data = {
        "product_id": kwargs.pop("product_id", name),
        "sku_id": kwargs.pop("sku_id", "1"),
        "name": name,
        "brand": kwargs.pop("brand", "Samsung"),
        "store": kwargs.pop("store", "falabella"),
        "price": kwargs.pop("price", 10000),
    }
    data.update(kwargs)
    return Product(**data)


def test_keeps_matching_phone_and_drops_unrelated():
    query = "celular s25 512gb"
    kept, discarded, _ = filter_relevant(
        query,
        [
            _product("Celular Galaxy S25 512GB", product_id="a"),
            _product("Galaxy S25 Ultra 256GB", product_id="b"),
            _product("Celular MIX Flip 12+512G", product_id="c"),
            _product("Silla Malm pino", brand="IKEA", product_id="d"),
            _product("Carpa Doite Andes", brand="Doite", product_id="e"),
        ],
    )
    names = [item.name for item in kept]
    assert "Celular Galaxy S25 512GB" in names
    assert "Galaxy S25 Ultra 256GB" in names
    assert all("Silla" not in name and "MIX Flip" not in name and "Carpa" not in name for name in names)
    assert len(discarded) >= 2


def test_storage_is_optional_but_model_is_required():
    assert score_product("celular s25 512gb", _product("Galaxy S25 256GB")).accepted is True
    assert score_product("celular s25 512gb", _product("Celular POCO F9 Ultra")).accepted is False


def test_brand_and_category_query():
    kept, discarded, _ = filter_relevant(
        "leche colun",
        [
            _product("Leche Colun Entera 1L", brand="Colun", product_id="1"),
            _product("Yogurt Natural", brand="Soprole", product_id="2"),
        ],
    )
    assert [item.product_id for item in kept] == ["1"]
    assert discarded[0].product_id == "2"


def test_accessories_do_not_answer_a_device_query():
    kept, discarded, details = filter_relevant(
        "tv 50 pulgadas",
        [
            _product("Smart TV 50 Crystal UHD 4K", product_id="tv50"),
            _product("Rack Para TV 50 Pulgadas Nórdico", brand="Mica", product_id="rack"),
            _product("Soporte De Pared Para TV 32 A 70 Pulgadas", brand="Vivo", product_id="soporte"),
            _product("Mueble Rack TV 50 Pulgadas", brand="Casa", product_id="mueble"),
        ],
    )
    assert [item.product_id for item in kept] == ["tv50"]
    assert {item.product_id for item in discarded} == {"rack", "soporte", "mueble"}
    assert "rack" in details[("falabella", "rack")].reason


def test_requested_size_wins_over_other_sizes():
    assert score_product("tv 50 pulgadas", _product("Smart TV 55 QLED")).accepted is False
    assert score_product("tv 50 pulgadas", _product("Smart TV 50 QLED")).accepted is True
    # sin medida declarada no se castiga
    assert score_product("tv 50 pulgadas", _product("Smart TV QLED 4K")).accepted is True


def test_accessory_query_still_finds_the_accessory():
    kept, _, _ = filter_relevant(
        "rack para tv",
        [
            _product("Rack Para TV 50 Pulgadas", product_id="rack"),
            _product("Smart TV 50 Crystal UHD", product_id="tv"),
        ],
    )
    assert "rack" in [item.product_id for item in kept]


def test_charger_is_not_a_phone():
    assert score_product("celular s25", _product("Cargador Para Celular Galaxy S25")).accepted is False
    assert score_product("celular s25", _product("Celular Galaxy S25 256GB")).accepted is True


def test_discount_ignores_amounts_sent_as_percent():
    # Lider mandaba savingsAmt (pesos) en el campo del porcentaje: 103809-92990.
    assert sane_discount(10819, 103809, 92990) == 10
    item = Product(product_id="1", sku_id="1", name="x", price=92990, price_normal=103809, discount_percent=10819)
    assert item.discount_percent == 10


def test_discount_keeps_what_the_store_publishes():
    # Paris anuncia 20% (normal contra oferta) aunque price sea el de tarjeta.
    assert sane_discount(20, 100000, 75000) == 20
    assert sane_discount(51, 90990, 43683) == 51  # Mercado Libre trunca 51,99
    assert sane_discount(None, 100000, 80000) == 20  # sin etiqueta, la resta
    assert sane_discount(25, None, 80000) == 25  # sin precio normal, la etiqueta
    assert sane_discount(0, None, 80000) is None
    assert sane_discount(150, None, 80000) is None
    assert sane_discount(None, 80000, 80000) is None
    assert sane_discount(90, 100000, 80000) == 20  # etiqueta increíble, manda la resta


def test_embed_text_is_stable_and_normalized():
    first = embed_text("celular s25 512gb")
    second = embed_text("celular s25 512gb")
    assert first == second
    assert abs(sum(value * value for value in first) - 1) < 1e-6


def test_build_result_lists_discarded_products():
    from retail.search import build_result

    result = build_result(
        "tv 50 pulgadas",
        "db",
        ["falabella"],
        {"falabella": "Falabella"},
        [],
        [
            _product("Smart TV 50 Crystal UHD 4K", product_id="tv50"),
            _product("Rack Para TV 50 Pulgadas Nórdico", brand="Mica", product_id="rack", url="https://example.test/rack"),
        ],
        [],
        [],
        price_band=False,
    )
    assert result["discarded_count"] == 1
    item = result["discarded"][0]
    assert item["product_id"] == "rack"
    assert item["store_title"] == "Falabella"
    assert item["price"] == 10000
    assert item["url"] == "https://example.test/rack"
    assert item["reason"]
