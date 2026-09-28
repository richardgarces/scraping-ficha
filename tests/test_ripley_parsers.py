from retail.sources.ripley.parsers import listing_from_next_data, listing_item_to_product, product_detail_to_product


def test_listing_item_prices():
    product = listing_item_to_product(
        {
            "sku": "2000409933532",
            "parentProductID": "2000409933532P",
            "name": "NOTEBOOK GAMER HP",
            "description": "Notebook Gamer HP Omen",
            "brand": "HP",
            "priceNumber": 1349990,
            "masterPriceNumber": 1699990,
            "discount": 21,
            "currency": "CLP",
            "primaryImage": "https://rimage.ripley.cl/img.jpg",
            "seller": "RIPLEY",
            "shop": {"sellerId": 1, "shopName": "Shop Ecsa"},
            "rating_reviews": {"score": 4.5, "count": 10},
            "sponsored": {"is_sponsored": True},
            "categoryCode": "R190704000000",
        }
    )
    assert product.store == "ripley"
    assert product.price == 1349990
    assert product.price_normal == 1699990
    assert product.discount_percent == 21
    assert product.rating == 4.5
    assert product.reviews == 10
    assert product.url.endswith("2000409933532p")


def test_listing_marketplace_url_uses_mpm_id():
    product = listing_item_to_product(
        {
            "sku": "19230458",
            "parentProductID": "MPM10001905493",
            "name": "JUEGO DE LIVING DE TERRAZA BRISA 4 PIEZAS PARA EXTERIOR MARRÓN",
            "priceNumber": 199990,
        }
    )
    assert product.url == "https://simple.ripley.cl/MPM10001905493"
    assert product.product_id == "MPM10001905493"
    assert product.sku_id == "19230458"


def test_listing_from_next_data_pagination():
    payload = {
        "props": {
            "pageProps": {
                "findabilityProps": {
                    "pageType": "search",
                    "data": {
                        "products": [{"sku": "1"}],
                        "total": 100,
                        "limit": 48,
                        "offset": 48,
                    },
                }
            }
        }
    }
    listing = listing_from_next_data(payload)
    assert listing["pagination"]["currentPage"] == 2
    assert listing["pagination"]["count"] == 100
    assert len(listing["results"]) == 1


def test_product_detail_specs():
    product = product_detail_to_product(
        {
            "props": {
                "pageProps": {
                    "detailProps": {
                        "data": {
                            "product": {
                                "sku": "1",
                                "parentProductID": "1P",
                                "name": "Zapatilla",
                                "brand": "Nike",
                                "canonicalSlug": "zapatilla",
                                "categoryCode": "R1",
                                "breadcrumbs": [{"code": "calzado", "label": "Calzado"}],
                                "shortDescription": "<p>Cómoda</p>",
                                "fullImage": "https://img",
                                "parentpricestock": {
                                    "price": {
                                        "master": {"valueNumber": 59990, "currency": "CLP"},
                                        "sale": {
                                            "valueNumber": 49990,
                                            "currency": "CLP",
                                            "discountPercentage": "17",
                                        },
                                        "ripley": {"valueNumber": 47990},
                                    }
                                },
                                "variants": [
                                    {
                                        "sku": "1",
                                        "shop": {"sellerId": 1, "shopName": "Shop Ecsa"},
                                        "attributes": [
                                            {
                                                "name": "Color",
                                                "Values": [{"values": "Negro"}],
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    }
                }
            }
        }
    )
    assert product.store == "ripley"
    assert product.price_cmr == 47990
    assert product.price == 49990
    assert product.price_card == 47990
    assert product.category == "Calzado"
    assert product.specifications["Color"] == "Negro"
