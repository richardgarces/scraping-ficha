from retail.sources.ripley.urls import parse_target, product_url


def test_parse_search_text():
    target = parse_target("notebook gamer")
    assert target.kind == "search"
    assert target.query == "notebook gamer"


def test_parse_sku():
    target = parse_target("2000409933532p")
    assert target.kind == "product"
    assert target.product_id == "2000409933532"


def test_parse_category_slug():
    target = parse_target("tecno/computacion/notebooks")
    assert target.kind == "category"
    assert target.category_id == "tecno/computacion/notebooks"


def test_parse_search_url():
    target = parse_target("https://www.ripley.cl/search/zapatillas?page=2")
    assert target.kind == "search"
    assert target.query == "zapatillas"


def test_parse_category_url():
    target = parse_target("https://simple.ripley.cl/tecno/computacion/notebooks")
    assert target.kind == "category"
    assert target.category_id == "tecno/computacion/notebooks"


def test_parse_product_url():
    target = parse_target(
        "https://simple.ripley.cl/notebook-gamer-hp-omen-2000409933532p"
    )
    assert target.kind == "product"
    assert target.product_id == "2000409933532"


def test_product_url():
    assert product_url("2000409933532") == "https://simple.ripley.cl/2000409933532p"


def test_marketplace_product_url():
    assert product_url("19230458", parent_id="MPM10001905493") == "https://simple.ripley.cl/MPM10001905493"
    target = parse_target("https://simple.ripley.cl/MPM10001905493")
    assert target.kind == "product"
    assert target.product_id == "MPM10001905493"
