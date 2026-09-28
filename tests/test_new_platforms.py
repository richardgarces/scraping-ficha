from retail.registry import list_stores
from retail.sources.ikea import listing_item_to_product as ikea_item
from retail.sources.ikea import parse_ikea_target
from retail.sources.nike import listing_item_to_product as nike_item
from retail.platforms.shopify import listing_item_to_product as shopify_item
from retail.platforms.shopify import parse_shopify_target
from retail.platforms.magento import listing_item_to_product as magento_item
from retail.platforms.magento import parse_listing_html, parse_magento_target
from retail.sources.pcfactory import listing_item_to_product as pcfactory_item
from retail.sources.pcfactory import parse_pcfactory_target
from retail.sources.tottus import parse_tottus_target
from retail.platforms.vtex import listing_item_to_product as vtex_item, parse_vtex_target


def test_registered_new_stores():
    ids = {spec.id for spec in list_stores()}
    assert {
        "amphora",
        "colloky",
        "doite",
        "drsimi",
        "fashionspark",
        "ikea",
        "intime",
        "lippi",
        "nike",
        "pcfactory",
        "tottus",
        "weplay",
        "antartica",
        "rosen",
        "sparta",
        "cannon",
        "tiendaflores",
    } <= ids


def test_parse_ikea():
    assert parse_ikea_target("silla").kind == "search"
    assert parse_ikea_target("30605423").kind == "product"
    assert parse_ikea_target("fu002").kind == "category"
    product = parse_ikea_target("https://www.ikea.com/cl/es/p/sandsberg-silla-negro-30605423/")
    assert product.kind == "product"
    assert product.product_id == "30605423"
    category = parse_ikea_target("https://www.ikea.com/cl/es/cat/sillas-fu002/")
    assert category.kind == "category"
    assert category.category_id == "fu002"


def test_ikea_listing_prices():
    product = ikea_item(
        {
            "name": "SANDSBERG",
            "typeName": "Silla",
            "id": "30605423",
            "itemNo": "30605423",
            "pipUrl": "https://www.ikea.com/cl/es/p/sandsberg-silla-negro-30605423/",
            "mainImageUrl": "https://img",
            "ratingValue": 4.7,
            "ratingCount": 58,
            "badge": {"type": "TOP_SELLER"},
            "salesPrice": {"numeral": 12990.0},
        }
    )
    assert product.store == "ikea"
    assert product.price == 12990
    assert product.is_bestseller is True


def test_parse_vtex_and_nike_prices():
    assert parse_vtex_target("air max").kind == "search"
    assert parse_vtex_target("20701").kind == "product"
    assert parse_vtex_target("ropa/polerones").kind == "category"
    target = parse_vtex_target("https://www.nike.cl/if1266-084-nike-air/p")
    assert target.kind == "product"
    assert target.product_id == "if1266-084-nike-air"
    product = nike_item(
        {
            "productId": "20701",
            "productName": "Nike Air",
            "brand": "Nike",
            "linkText": "if1266-084-nike-air",
            "categoryId": "19",
            "categories": ["/nike/ropa/"],
            "items": [
                {
                    "itemId": "202846",
                    "images": [{"imageUrl": "https://img"}],
                    "sellers": [
                        {
                            "sellerName": "Nike",
                            "commertialOffer": {"Price": 55990.0, "ListPrice": 79990.0},
                        }
                    ],
                }
            ],
        }
    )
    assert product.store == "nike"
    assert product.price == 55990
    assert product.price_normal == 79990
    assert product.discount_percent == 30
    assert product.url.endswith("/p")

    stock_product = vtex_item(
        {
            "productId": "1",
            "productName": "Producto con stock",
            "items": [{"itemId": "11", "sellers": [{"commertialOffer": {"Price": 1000, "ListPrice": 1200, "AvailableQuantity": 6}}]}],
        },
        store_id="prueba",
        base="https://example.com",
    )
    assert stock_product.stock == 6
    assert stock_product.availability == "En stock"


def test_parse_shopify_and_prices():
    assert parse_shopify_target("jeans").kind == "search"
    product = parse_shopify_target("https://www.fashionspark.com/products/parka-hombre")
    assert product.kind == "product"
    assert product.product_id == "parka-hombre"
    category = parse_shopify_target("https://www.doite.cl/collections/camping")
    assert category.kind == "category"
    assert category.category_id == "camping"
    item = shopify_item(
        {
            "id": 1,
            "title": "Parka",
            "handle": "parka",
            "vendor": "Fashion Spark",
            "variants": [{"sku": "A1", "price": "19990.00", "compare_at_price": "29990.00"}],
            "images": [{"src": "https://img"}],
        },
        store_id="fashionspark",
        base="https://www.fashionspark.com",
    )
    assert item.store == "fashionspark"
    assert item.price == 19990
    assert item.price_normal == 29990
    assert item.url.endswith("/products/parka")
    expensive = shopify_item(
        {"title": "MARQ", "price": "1389990", "handle": "marq"},
        store_id="garmin",
        base="https://garminstore.cl",
    )
    assert expensive.price == 1389990


def test_parse_pcfactory_and_prices():
    assert parse_pcfactory_target("notebook").kind == "search"
    assert parse_pcfactory_target("57695").kind == "product"
    target = parse_pcfactory_target(
        "https://www.pcfactory.cl/producto/57695-hp-notebook"
    )
    assert target.kind == "product"
    assert target.product_id == "57695"
    product = pcfactory_item(
        {
            "id": 57695,
            "nombre": "Notebook HP",
            "marca": "HP",
            "slug": "57695-hp-notebook",
            "thumbnail": "/public/foto/57695/1_200.jpg",
            "categoria": {"id": 425, "nombre": "Notebooks"},
            "precio": {"efectivo": 499990.0, "normal": 515490.0, "referencia": 599990.0},
        }
    )
    assert product.store == "pcfactory"
    assert product.price == 499990
    assert product.price_normal == 599990
    assert product.url.endswith("57695-hp-notebook")


def test_parse_tottus():
    assert parse_tottus_target("leche").kind == "search"
    product = parse_tottus_target(
        "https://www.tottus.cl/tottus-cl/articulo/112737942/leche-entera"
    )
    assert product.kind == "product"
    assert product.product_id == "112737942"


def test_parse_magento_and_html():
    assert parse_magento_target("lego").kind == "search"
    category = parse_magento_target("camas-y-colchones/colchones")
    assert category.kind == "category"
    items, count = parse_listing_html(
        """
        <li class="item product product-item">
          <a class="product-item-link" href="https://www.weplay.cl/lego.html">
            <img data-src="" src="https://img.weplay.cl/lego-first.jpg">
            Lego Classic
          </a>
              <div data-product-id="36527"></div>
              <span id="product-price-36527" data-price-amount="89990" data-price-type="finalPrice"></span>
        </li>
        <span class="toolbar-number">36</span>
        """
    )
    assert count == 36
    product = magento_item(items[0], store_id="weplay")
    assert product.store == "weplay"
    assert product.price == 89990
    assert product.product_id == "36527"
    assert product.image_url == "https://img.weplay.cl/lego-first.jpg"
