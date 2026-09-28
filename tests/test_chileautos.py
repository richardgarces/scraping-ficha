from retail.registry import STORE_GROUP, list_stores
from retail.sources.chileautos import ChileautosStore, listing_item_to_product, parse_chileautos_target


def test_chileautos_registrada_y_agrupada():
    ids = {spec.id for spec in list_stores()}
    assert "chileautos" in ids
    assert STORE_GROUP["chileautos"] == "autos"
    spec = next(item for item in list_stores() if item.id == "chileautos")
    assert spec.title == "Chileautos"
    assert spec.platform == "carsales"
    assert spec.group == "autos"


def test_parse_chileautos_targets():
    assert parse_chileautos_target("toyota").kind == "search"
    assert parse_chileautos_target("toyota").query == "toyota"
    search = parse_chileautos_target("https://www.chileautos.cl/vehiculos/busqueda?q=suzuki")
    assert search.kind == "search"
    assert search.query == "suzuki"
    category = parse_chileautos_target("https://www.chileautos.cl/vehiculos/toyota/yaris")
    assert category.kind == "category"
    assert category.category_id == "toyota/yaris"
    product = parse_chileautos_target(
        "https://www.chileautos.cl/vehiculos/detalles/2025-toyota-yaris/CP-AD-8556820/"
    )
    assert product.kind == "product"
    assert product.product_id == "CP-AD-8556820"
    assert parse_chileautos_target("CL-AD-20893223").kind == "product"


def test_chileautos_listing_card_to_product():
    product = listing_item_to_product(
        {
            "type": "ListingCard",
            "action": {
                "type": "NavigateAction",
                "tracking": {
                    "additionalAttributes": {
                        "tracking/item/networkId": "CP-AD-8556820",
                        "tracking/item/make": "Toyota",
                        "tracking/item/model": "Yaris",
                        "tracking/item/year": "2024",
                        "tracking/item/price": "11690000",
                        "tracking/item/adtype": "Vehículo Usado",
                        "tracking/item/state": "Metropolitana de Santiago",
                    }
                },
                "data": {
                    "url": (
                        "/vehiculos/detalles/2024-toyota-yaris/CP-AD-8556820/"
                        "?gts=CP-AD-8556820&gtsViewType=topspotnitro"
                    ),
                    "prefetchTitle": "2024 Toyota Yaris Sport",
                    "prefetchImage": "https://chileautos.pxcrush.net/cars/demo.jpg",
                    "prefetchSellerType": "Agencia",
                },
            },
            "gallery": {
                "type": "InlineCarousel",
                "children": [{"type": "Image", "url": "https://img.example/car.jpg"}],
            },
        },
        source="search",
    )
    assert product.store == "chileautos"
    assert product.product_id == "CP-AD-8556820"
    assert product.price == 11690000
    assert product.brand == "Toyota"
    assert product.name.startswith("2024 Toyota Yaris")
    assert product.url == "https://www.chileautos.cl/vehiculos/detalles/2024-toyota-yaris/CP-AD-8556820/"
    assert product.is_sponsored is True
    assert product.image_url.endswith("demo.jpg")
    assert product.condition == "used"
    assert product.specifications["vehicle_type"] == "car"
    assert product.specifications["year"] == "2024"


def test_chileautos_agrega_numero_de_pagina_al_listado():
    client = ChileautosStore(delay=0)
    try:
        target = parse_chileautos_target(
            "https://www.chileautos.cl/vehiculos/autos-veh%C3%ADculo/usado-tipo/"
        )
        url, params = client._listing_url(target, sort=None, page=3)
    finally:
        client.close()
    assert url.endswith("/vehiculos/autos-veh%C3%ADculo/usado-tipo/")
    assert params["page"] == "3"
