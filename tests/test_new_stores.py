from retail.registry import STORE_GROUP, list_stores
from retail.models import Product
from retail.sources.falabella import FalabellaClient
from retail.sources.easy import parse_easy_target
from retail.sources.paris import listing_item_to_product, parse_paris_target
from retail.sources.sodimac import SodimacStore, parse_sodimac_target


def test_registered_stores():
    ids = {spec.id for spec in list_stores()}
    assert {
        "easy",
        "falabella",
        "lider",
        "mercadolibre",
        "paris",
        "ripley",
        "sodimac",
    } <= ids


def test_every_store_is_grouped():
    missing = [spec.id for spec in list_stores() if spec.id not in STORE_GROUP]
    assert missing == []


def test_parse_paris_search_and_category():
    assert parse_paris_target("notebook").kind == "search"
    assert parse_paris_target("tecCompNotebooks").kind == "category"
    assert parse_paris_target("151337999").kind == "product"


def test_parse_paris_product_url():
    target = parse_paris_target(
        "https://www.paris.cl/notebook-galaxy-book4-intel-151337999.html"
    )
    assert target.kind == "product"
    assert target.product_id == "151337999"


def test_paris_listing_prices():
    product = listing_item_to_product(
        {
            "id": "1",
            "name": {"es-CL": "Notebook"},
            "brand": "HP",
            "slug": {"es-CL": "notebook-hp-1"},
            "sellers": ["Paris"],
            "masterVariant": {
                "sku": "1",
                "prices": {
                    "regular": {"value": {"centAmount": 100000}},
                    "offer": {"value": {"centAmount": 80000}, "discountOnRegular": 0.2},
                    "paymentMethod": {"value": {"centAmount": 75000}},
                },
                "images": [{"url": "https://img"}],
            },
        }
    )
    assert product.store == "paris"
    # El precio principal debe estar disponible sin contratar la tarjeta Paris.
    assert product.price == 80000
    assert product.price_card == 75000
    assert product.price_normal == 100000
    assert product.discount_percent == 20
    assert product.url == "https://www.paris.cl/notebook-hp-1.html"


def test_parse_sodimac():
    assert parse_sodimac_target("taladro").kind == "search"
    assert parse_sodimac_target("CATG36264").kind == "category"
    target = parse_sodimac_target(
        "https://www.sodimac.cl/sodimac-cl/category/CATG36264/Herramientas"
    )
    assert target.category_id == "CATG36264"
    assert target.category_name == "Herramientas"
    product = parse_sodimac_target(
        "https://www.sodimac.cl/sodimac-cl/articulo/80726514/taladro"
    )
    assert product.kind == "product"
    assert product.product_id == "80726514"


def test_sodimac_rewrites_falabella_product_url_as_articulo():
    rewritten = SodimacStore.rewrite_url(
        SodimacStore.__new__(SodimacStore),
        "https://www.falabella.com/falabella-cl/product/80726514/taladro",
    )
    assert rewritten == "https://www.sodimac.cl/sodimac-cl/articulo/80726514/taladro"


def test_sodimac_normalizes_falabella_host_and_keeps_query():
    from retail.models import normalize_product_url

    rewritten = normalize_product_url(
        "sodimac",
        "https://www.falabella.com/falabella-cl/product/80726514/taladro?exp=so_com",
    )
    assert rewritten == "https://www.sodimac.cl/sodimac-cl/articulo/80726514/taladro?exp=so_com"


def test_stored_sodimac_product_url_is_normalized_when_loaded():
    product = Product.from_dict(
        {
            "store": "sodimac",
            "product_id": "80726514",
            "sku_id": "80726514",
            "name": "Taladro",
            "url": "https://www.sodimac.cl/sodimac-cl/product/80726514/taladro",
        }
    )
    assert product.url == "https://www.sodimac.cl/sodimac-cl/articulo/80726514/taladro"


def test_product_page_uses_sodimac_articulo_fallback():
    from pathlib import Path

    script = Path("retail/web/static/producto.js").read_text(encoding="utf-8")
    page = Path("retail/web/static/producto.html").read_text(encoding="utf-8")
    assert "sodimac-cl/articulo/" in script
    assert "sodimac-cl/product/" not in script
    assert 'src="/static/producto.js?v=' in page
    assert 'id="chart-offer"' in page
    assert 'id="chart-normal"' in page
    assert 'id="chart-combined"' in page
    assert 'data-chart-mode="combined"' in page


def test_falabella_alt_product_id():
    url = (
        "https://www.falabella.com/falabella-cl/product/"
        "153777946/kit-taladro/153777947"
    )
    assert FalabellaClient._product_id_from_path(url) == "153777946"


def test_parse_easy():
    assert parse_easy_target("taladro").kind == "search"
    target = parse_easy_target("herramientas/herramientas-electricas/taladros")
    assert target.kind == "category"
    product = parse_easy_target(
        "https://www.easy.cl/taladro-einhell-1311876/p"
    )
    assert product.kind == "product"
