from retail.parsers import parse_clp
from retail.models import Product, first_image_url
from retail.sources.falabella.parsers import listing_item_to_product, product_detail_to_product


def test_parse_clp_chilean_thousands():
    assert parse_clp("699.990") == 699990
    assert parse_clp(["1.069.990"]) == 1069990
    assert parse_clp("$ 719.990") == 719990
    assert parse_clp(None) is None


def test_listing_item_prices():
    product = listing_item_to_product(
        {
            "productId": "80726514",
            "skuId": "80726514",
            "displayName": "Notebook Gamer",
            "brand": "HP",
            "url": "https://www.falabella.com/falabella-cl/product/80726514/x",
            "sellerName": "Falabella",
            "discountBadge": {"label": "-35%"},
            "prices": [
                {"type": "cmrPrice", "price": ["699.990"]},
                {"type": "internetPrice", "price": ["719.990"]},
                {"type": "normalPrice", "price": ["1.069.990"]},
            ],
            "rating": "3.9",
            "totalReviews": "90",
            "mediaUrls": ["https://media.falabella.com/img.jpg"],
            "isSponsored": True,
        }
    )
    assert product.price == 719990
    assert product.price_card == 699990
    assert product.price_normal == 1069990
    assert product.discount_percent == 35
    assert product.rating == 3.9
    assert product.reviews == 90
    assert product.is_sponsored is True


def test_falabella_event_price_is_all_payment_not_crossed_normal():
    """Campañas publican eventPrice + normalPrice tachado, sin internetPrice."""
    product = product_detail_to_product(
        {
            "data": {
                "id": "157189413",
                "name": "Samsung Galaxy S26 FE 256 GB Blueberry",
                "brandName": "SAMSUNG",
                "slug": "samsung-galaxy-s26-fe",
                "variants": [
                    {
                        "id": "157189414",
                        "prices": [
                            {
                                "type": "eventPrice",
                                "crossed": False,
                                "price": ["769.990"],
                            },
                            {
                                "type": "normalPrice",
                                "crossed": True,
                                "price": ["919.990"],
                            },
                        ],
                        "offerings": [{"sellerName": "samsung", "sellerId": "S"}],
                    }
                ],
            }
        }
    )
    assert product.price == 769990
    assert product.price_internet == 769990
    assert product.price_all_payment == 769990
    assert product.price_normal == 919990
    assert product.discount_percent == 16


def test_first_image_skips_empty_entries_and_accepts_nested_objects():
    images = [None, {}, {"url": ""}, {"image": {"src": "https://img.example/primera.jpg"}}, "https://img.example/segunda.jpg"]
    assert first_image_url(images) == "https://img.example/primera.jpg"


def test_first_image_uses_first_gallery_entry_with_store_specific_size_keys():
    images = [
        {"large": {"location": "https://img.example/primera.jpg"}},
        {"large": {"location": "https://img.example/segunda.jpg"}},
    ]
    assert first_image_url(images) == "https://img.example/primera.jpg"


def test_first_image_normalizes_protocol_relative_url():
    assert first_image_url(["//img.example/primera.jpg", "https://img.example/segunda.jpg"]) == (
        "https://img.example/primera.jpg"
    )


def test_product_normalizes_multiple_images_before_persisting():
    product = Product(
        product_id="1",
        sku_id="1",
        name="Producto",
        store="demo",
        image_url=[{"src": ""}, {"src": "https://img.example/primera.jpg"}],
    )
    assert product.image_url == "https://img.example/primera.jpg"


def test_falabella_listing_uses_first_valid_image_from_multiple_objects():
    product = listing_item_to_product(
        {
            "productId": "1",
            "skuId": "1",
            "displayName": "Producto con galería",
            "prices": [{"type": "internetPrice", "price": ["19.990"]}],
            "mediaUrls": [{"url": ""}, {"url": "https://img.example/primera.jpg"}, {"url": "https://img.example/segunda.jpg"}],
        }
    )
    assert product.image_url == "https://img.example/primera.jpg"


def test_product_detail_specs():
    product = product_detail_to_product(
        {
            "data": {
                "id": "1",
                "name": "Zapatilla",
                "brandName": "Nike",
                "slug": "zapatilla",
                "longDescription": "<p>Cómoda</p>",
                "breadCrumb": [{"id": "cat1", "label": "Calzado"}],
                "attributes": {
                    "specifications": [
                        {"name": "Color", "value": "Negro"},
                        {"name": "Talla", "value": "42"},
                    ]
                },
                "variants": [
                    {
                        "id": "1",
                        "prices": [{"type": "internetPrice", "price": ["49.990"]}],
                        "offerings": [{"sellerName": "Falabella", "sellerId": "FALABELLA_CHILE"}],
                    }
                ],
            }
        }
    )
    assert product.brand == "Nike"
    assert product.price == 49990
    assert product.category == "Calzado"
    assert product.specifications["Color"] == "Negro"
    assert product.description == "Cómoda"
