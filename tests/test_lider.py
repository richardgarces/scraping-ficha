from retail.sources.lider import listing_item_to_product, parse_lider_target


def test_parse_lider_search_and_ids():
    assert parse_lider_target("leche colun").kind == "search"
    assert parse_lider_target("00888833356718").kind == "product"
    assert parse_lider_target("40094495_51094991_65672745").kind == "category"


def test_parse_lider_urls():
    search = parse_lider_target("https://www.lider.cl/browse?query=leche")
    assert search.kind == "search"
    assert search.query == "leche"
    product = parse_lider_target(
        "https://www.lider.cl/ip/lactancia/absorbentes-de-leche-familia-x60/00888833356718"
    )
    assert product.kind == "product"
    assert product.product_id == "00888833356718"
    category = parse_lider_target(
        "https://www.lider.cl/browse/mundo-bebe/lactancia/extractores-de-leche/40094495_51094991_65672745"
    )
    assert category.kind == "category"
    assert category.category_id.endswith("65672745")


def test_lider_listing_prices():
    product = listing_item_to_product(
        {
            "usItemId": "00888833356718",
            "id": "abc",
            "name": "Absorbentes De Leche Familia x60",
            "brand": "Familia",
            "sellerName": "Lider",
            "sellerId": "1",
            "price": 3033,
            "priceInfo": {"linePrice": "$3.033", "wasPrice": "$3.990", "savingsAmt": 24},
            "canonicalUrl": "/ip/lactancia/absorbentes/00888833356718",
            "imageInfo": {"thumbnailUrl": "https://img"},
            "averageRating": 4.2,
            "numberOfReviews": 3,
            "category": {
                "categoryPathId": "1:2:3",
                "path": [{"name": "Lactancia", "url": "/browse/x"}],
            },
        }
    )
    assert product.store == "lider"
    assert product.price == 3033
    assert product.price_normal == 3990
    assert product.url.endswith("00888833356718")
    assert product.category == "Lactancia"
