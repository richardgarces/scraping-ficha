from retail.sources.falabella.urls import parse_target


def test_parse_search_text():
    target = parse_target("notebook gamer")
    assert target.kind == "search"
    assert target.query == "notebook gamer"


def test_parse_product_id():
    target = parse_target("80726514")
    assert target.kind == "product"
    assert target.product_id == "80726514"


def test_parse_category_id():
    target = parse_target("cat720161")
    assert target.kind == "category"
    assert target.category_id == "cat720161"


def test_parse_search_url():
    target = parse_target("https://www.falabella.cl/falabella-cl/search?Ntt=zapatillas")
    assert target.kind == "search"
    assert target.query == "zapatillas"


def test_parse_category_url():
    target = parse_target(
        "https://www.falabella.com/falabella-cl/category/cat720161/Smartphones?page=2"
    )
    assert target.kind == "category"
    assert target.category_id == "cat720161"
    assert target.category_name == "Smartphones"


def test_parse_product_url():
    target = parse_target(
        "https://www.falabella.com/falabella-cl/product/80726514/notebook-gamer-hp"
    )
    assert target.kind == "product"
    assert target.product_id == "80726514"
