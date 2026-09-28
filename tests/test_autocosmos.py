from retail.registry import STORE_GROUP, list_stores
from retail.sources.autocosmos import (
    AutocosmosStore,
    extract_listing_items,
    listing_item_to_product,
    parse_autocosmos_target,
)


def test_autocosmos_registrada_en_autos():
    assert "autocosmos" in {spec.id for spec in list_stores()}
    assert STORE_GROUP["autocosmos"] == "autos"


def test_parse_autocosmos_targets_y_paginacion():
    assert parse_autocosmos_target("toyota yaris").query == "toyota yaris"
    category = parse_autocosmos_target("https://www.autocosmos.cl/auto/usado")
    assert category.kind == "category"
    product = parse_autocosmos_target(
        "https://www.autocosmos.cl/auto/usado/toyota/yaris/xli/0123456789abcdef0123456789abcdef"
    )
    assert product.kind == "product"
    client = AutocosmosStore(delay=0)
    try:
        url = client._listing_url(parse_autocosmos_target("toyota yaris"), page=2, sort="precio_asc")
    finally:
        client.close()
    assert "/auto/listado/toyota/yaris" in url
    assert "seccion=precio-final" in url
    assert "p=2" in url
    assert "sort=8" in url


def test_autocosmos_extrae_precio_final_y_datos_del_auto():
    html = """
    <article class="card listing-card" itemscope itemtype="http://schema.org/Car">
      <meta itemprop="itemCondition" content="http://schema.org/UsedCondition">
      <meta itemprop="name" content="Toyota Yaris Sport">
      <meta itemprop="description" content="Único dueño">
      <a itemprop="url" href="/auto/usado/toyota/yaris/sport/0123456789abcdef0123456789abcdef"></a>
      <img itemprop="image" content="https://img.example/yaris.webp">
      <span itemprop="brand">Toyota</span><span itemprop="model">Yaris</span>
      <span itemprop="modelDate">2024</span>
      <meta itemprop="mileageFromOdometer" content="KMT 34300">
      <span itemprop="addressLocality">Santiago</span>
      <span itemprop="addressRegion">RM</span>
      <span itemprop="price" content="11690000"></span>
    </article>
    """
    items = extract_listing_items(html)
    assert len(items) == 1
    product = listing_item_to_product(items[0], source="category")
    assert product.product_id == "0123456789abcdef0123456789abcdef"
    assert product.price == 11690000
    assert product.condition == "used"
    assert product.specifications["year"] == "2024"
    assert product.specifications["mileage_km"] == "34300"
    assert product.image_url == "https://img.example/yaris.webp"


def test_autocosmos_no_confunde_el_pie_con_precio_del_auto():
    product = listing_item_to_product(
        {
            "url": "/auto/usado/a/b/c/0123456789abcdef0123456789abcdef",
            "name": "Auto de prueba",
            "price": "2500000",
            "price_title": "Pie:",
        }
    )
    assert product.price is None
