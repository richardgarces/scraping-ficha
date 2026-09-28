from retail.parsers import parse_money
from retail.registry import STORE_GROUP, list_stores
from retail.sources.entel import listing_item_to_product as entel_product
from retail.sources.entel import parse_entel_target
from retail.sources.movistar import listing_item_to_product as movistar_product
from retail.sources.movistar import parse_listing_html, parse_movistar_target


def test_telefonia_registrada_y_agrupada():
    ids = {spec.id for spec in list_stores()}
    assert {"movistar", "entel"} <= ids
    assert STORE_GROUP["movistar"] == "tecnologia"
    assert STORE_GROUP["entel"] == "tecnologia"


def test_parse_movistar_targets():
    assert parse_movistar_target("galaxy").kind == "search"
    search = parse_movistar_target("https://catalogo.movistar.cl/catalogsearch/result/?q=galaxy")
    assert search.kind == "search"
    assert search.query == "galaxy"
    category = parse_movistar_target("https://catalogo.movistar.cl/tienda/celulares")
    assert category.kind == "category"
    assert category.category_id == "celulares"
    product = parse_movistar_target(
        "https://catalogo.movistar.cl/tienda/iphone-18-pro-max-256gb-borgona"
    )
    assert product.kind == "product"
    assert product.product_id == "iphone-18-pro-max-256gb-borgona"
    assert parse_movistar_target("65896").kind == "product"


def test_movistar_listing_cash_price():
    items, count = parse_listing_html(
        """
        <li class="item product product-item">
          <div class="product-item-info" id="product-item-info 65896">
            <a href="https://catalogo.movistar.cl/tienda/iphone-18-pro-max-256gb-borgona"
               class="product-item-link" title="iPhone 18 Pro Max 256GB Borgoña"
               data-crosss-id-catalog="65896">
              <h2>iPhone 18 Pro Max 256GB Borgoña</h2>
            </a>
            <img class="product-image-photo" src="https://catalogo.movistar.cl/media/iphone.png"/>
            <div class="infoValores">
              <div class="divCon-plan onePrice">
                <span class="divCon-plan-txt-valor-sinLabel">$1.699.990</span>
              </div>
              <div class="monthly-price">en 24 cuotas de $70.833 sin interés*</div>
            </div>
          </div>
        </li>
        <span class="toolbar-number">Mostrando 1 al 36 de 99</span>
        """
    )
    assert count == 99
    product = movistar_product(items[0], source="search")
    assert product.store == "movistar"
    assert product.product_id == "65896"
    assert product.price == 1699990
    assert "iphone-18-pro-max-256gb-borgona" in (product.url or "")
    assert product.name.startswith("iPhone 18")


def test_parse_entel_targets():
    assert parse_entel_target("galaxy").kind == "search"
    search = parse_entel_target("https://miportal.entel.cl/personas/busqueda?Ntt=iphone")
    assert search.kind == "search"
    assert search.query == "iphone"
    category = parse_entel_target("https://miportal.entel.cl/personas/catalogo/celulares/samsung")
    assert category.kind == "category"
    assert category.category_id == "celulares/samsung"
    product = parse_entel_target("https://miportal.entel.cl/personas/catalogo/prod2590044")
    assert product.kind == "product"
    assert product.product_id == "prod2590044"
    seo = parse_entel_target(
        "https://miportal.entel.cl/personas/celulares/iphone-18-pro/prod2780062"
    )
    assert seo.kind == "product"
    assert seo.product_id == "prod2780062"
    assert parse_entel_target("prod2780062").kind == "product"
    assert parse_entel_target("celulares").kind == "category"


def test_entel_listing_equipment_price():
    product = entel_product(
        {
            "detailsAction": {"recordState": "/prod2780062"},
            "attributes": {
                "productId": ["prod2780062"],
                "displayName": ["iPhone 18 Pro"],
                "brand": ["Apple"],
                "listPrice": ["1549990.000000"],
                "referencePrice": ["1699990.000000"],
                "sku": ["138048"],
                "seoUrl": ["/personas/celulares/iphone-18-pro/prod2780062"],
                "productImage": ["/static/x/images/iphone.jpg"],
                "parentCategoryName": ["Celulares"],
                "description": ["Apple IPHONE 18 PRO, 256 GB Negro"],
            },
        },
        source="search",
    )
    assert product.store == "entel"
    assert product.product_id == "prod2780062"
    assert product.price == 1549990
    assert product.price_normal == 1699990
    assert product.brand == "Apple"
    assert product.url.endswith("/personas/celulares/iphone-18-pro/prod2780062")


def test_entel_skips_zero_list_price():
    product = entel_product(
        {
            "attributes": {
                "productId": ["prod2010047"],
                "displayName": ["Galaxy S23 5G 256GB"],
                "listPrice": ["0.000000"],
                "referencePrice": ["1115990.000000"],
            }
        }
    )
    assert product.price is None


def test_parse_money_decimal_and_clp():
    assert parse_money("1549990.000000") == 1549990
    assert parse_money("199989.999600") == 199990
    assert parse_money("$1.549.990") == 1549990
    assert parse_money("0.000000") is None
