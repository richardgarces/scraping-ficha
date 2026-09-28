from retail.sources.mercadolibre import listing_item_to_product, parse_mercadolibre_target


def test_parse_mercadolibre_search_and_ids():
    assert parse_mercadolibre_target("notebook gamer").kind == "search"
    assert parse_mercadolibre_target("MLC1648").kind == "category"
    assert parse_mercadolibre_target("MLC2411516980").kind == "product"


def test_parse_mercadolibre_urls():
    search = parse_mercadolibre_target("https://listado.mercadolibre.cl/notebook-gamer")
    assert search.kind == "search"
    category = parse_mercadolibre_target("https://www.mercadolibre.cl/ofertas?category=MLC1648")
    assert category.kind == "category"
    assert category.category_id == "MLC1648"
    product = parse_mercadolibre_target(
        "https://www.mercadolibre.cl/audifonos/p/MLC18519571"
    )
    assert product.kind == "product"
    assert product.product_id == "MLC18519571"


def test_mercadolibre_listing_prices():
    product = listing_item_to_product(
        {
            "card": {
                "metadata": {
                    "id": "MLC2411516980",
                    "product_id": "MLC18519571",
                    "url": "www.mercadolibre.cl/audifonos/p/MLC18519571",
                },
                "pictures": {"pictures": [{"id": ""}, {"id": "732252-MLA99931019181_112025"}]},
                "components": [
                    {"type": "title", "title": {"text": "Audífonos Gamer Logitech"}},
                    {"type": "seller", "seller": {"text": "Logitech G {icon_cockade}"}},
                    {
                        "type": "review_compacted",
                        "review_compacted": {
                            "values": [{"key": "label", "label": {"text": "4.8"}}]
                        },
                    },
                    {
                        "type": "price",
                        "price": {
                            "current_price": {"value": 43683},
                            "price_labels": [
                                {
                                    "values": [
                                        {"price": {"value": 90990, "previous": True}}
                                    ]
                                }
                            ],
                            "discount_polylabel": {
                                "values": [{"pill": {"text": "51% OFF"}}]
                            },
                        },
                    },
                ],
            }
        }
    )
    assert product.store == "mercadolibre"
    assert product.price == 43683
    assert product.price_normal == 90990
    assert product.discount_percent == 51
    assert product.seller == "Logitech G"
    assert product.rating == 4.8
    assert product.url.endswith("MLC18519571")
    assert product.image_url.endswith("732252-MLA99931019181_112025-F.webp")
