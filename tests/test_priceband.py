from retail.models import Product
from retail.priceband import conflict, fit, preference
from retail.relevance import filter_relevant


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


def test_preference_reads_cheap_and_premium_words():
    assert preference("tv barato") == "low"
    assert preference("lavaplatos económico") == "low"
    assert preference("notebook gamer") == "high"
    assert preference("audífonos premium") == "high"
    assert preference("iphone 16 pro") is None
    assert preference("tv 50 pulgadas") is None


def test_fit_drops_an_outlier_from_the_main_cloud():
    band = fit([249990, 279990, 319990, 389990, 9990], None)
    assert band is not None
    assert conflict(9990, band)
    assert conflict(319990, band) is None


def test_fit_skips_when_there_are_few_or_compact_prices():
    assert fit([9990, 249990, 319990], None) is None
    assert fit([180000, 220000, 250000, 399990], None) is None
    band = fit([9990, 249990, 319990, 389990], None)
    assert band is not None
    assert conflict(9990, band)


def test_tv_search_drops_a_cheap_box_next_to_real_sets():
    kept, discarded, details = filter_relevant(
        "tv 50 pulgadas",
        _tv_cloud(),
    )
    assert "box" not in [item.product_id for item in kept]
    assert "box" in [item.product_id for item in discarded]
    assert "9.990" in (details[("falabella", "box")].reason or "")
    assert {item.product_id for item in kept} == {"a", "b", "c", "d"}


def test_price_band_can_be_disabled():
    kept, discarded, details = filter_relevant(
        "tv 50 pulgadas",
        _tv_cloud(),
        price_band=False,
    )
    assert "box" in [item.product_id for item in kept]
    assert details[("falabella", "box")].accepted is True
    assert details[("falabella", "box")].reason is None
    assert "box" not in [item.product_id for item in discarded]


def _tv_cloud():
    return [
        _product("Smart TV 50 Crystal UHD", product_id="a", price=249990),
        _product("Smart TV 50 QLED 4K", product_id="b", price=319990),
        _product("Smart TV 50 Pulgadas LED", product_id="c", price=279990),
        _product("Smart TV 50 Crystal", product_id="d", price=389990),
        _product("Smart TV Box Android 4K", product_id="box", price=9990),
    ]


def test_cheap_query_keeps_the_low_cluster():
    kept, discarded, _ = filter_relevant(
        "tv barato",
        [
            _product("Smart TV 43 LED", product_id="a", price=179990),
            _product("Smart TV 50 LED", product_id="b", price=219990),
            _product("Smart TV 43 Pulgadas", product_id="c", price=199990),
            _product("Smart TV 50 Crystal", product_id="d", price=249990),
            _product("Smart TV 75 QLED 8K", product_id="oled", price=1299990),
        ],
    )
    assert "oled" in [item.product_id for item in discarded]
    assert {item.product_id for item in kept} == {"a", "b", "c", "d"}


def test_gamer_query_keeps_the_high_cluster():
    kept, discarded, _ = filter_relevant(
        "notebook gamer",
        [
            _product("Notebook Lenovo IdeaPad 15", product_id="a", price=399990),
            _product("Notebook HP 14", product_id="b", price=449990),
            _product("Notebook Dell Inspiron", product_id="c", price=429990),
            _product("Notebook Asus Vivobook", product_id="d", price=519990),
            _product("Notebook Asus ROG Strix", product_id="rog", price=1599990),
            _product("Notebook Lenovo Legion 5", product_id="legion", price=1799990),
            _product("Notebook Acer Nitro", product_id="nitro", price=1499990),
            _product("Notebook HP Omen 16", product_id="omen", price=1699990),
        ],
    )
    assert {item.product_id for item in kept} == {"rog", "legion", "nitro", "omen"}
    assert {item.product_id for item in discarded} >= {"a", "b", "c", "d"}
