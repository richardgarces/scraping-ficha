"""Tests del piloto Scrapling (fixtures HTML estáticos, sin scrape live)."""

from __future__ import annotations

import retail.scrapling_html as scrapling_html
from retail.sources.hites import listing_item_to_product as hites_item_to_product
from retail.sources.hites import parse_hites_grid
from retail.sources.santaritaonline import (
    listing_item_to_product as santarita_item_to_product,
    parse_listing_html,
    parse_product_html,
)


HITES_GRID = (
    '<a href="/televisor-led-55-961015001.html">TV</a>'
    '<img class="img-fluid w-100 tile-image js-image1" '
    'src="/on/demandware.static/-/Sites-masterCatalog_Hites/default/images/original/'
    'television-y-video/961015001_1.jpg" />'
    '<div data-gtmselectitem="{&quot;item&quot;:{&quot;item_id&quot;:&quot;961015001&quot;,'
    '&quot;item_name&quot;:&quot;Televisor LED 55&quot;,&quot;item_brand&quot;:&quot;Samsung&quot;,'
    '&quot;price&quot;:299990,&quot;discount&quot;:50000,&quot;item_category&quot;:&quot;TV&quot;}}"></div>'
)

SANTARITA_LISTING = """
<ul class="products products-container grid">
<li class="product-col product-default product type-product post-890233">
  <a href="https://santaritaonline.com/producto/pack-escudo/">
    <img class="wp-post-image" src="https://santaritaonline.com/wp-content/uploads/2026/07/2-1.png" />
  </a>
  <h3 class="woocommerce-loop-product__title">Pack Escudo</h3>
  <span class="price"><ins><span class="woocommerce-Price-amount amount"><bdi>$50.457</bdi></span></ins></span>
  <a data-product_id="890233" data-product_sku="PAK1021330" class="add_to_cart_button" href="/?add-to-cart=890233">Agregar</a>
  <span class="gtm4wp_productdata" data-gtm4wp_product_data='{"internal_id":890233,"item_id":890233,"item_name":"Pack Escudo","sku":"PAK1021330","price":50457,"stockstatus":"instock","item_category":"Packs","productlink":"https://santaritaonline.com/producto/pack-escudo/"}'></span>
</li>
</ul>
"""

SANTARITA_PRODUCT = """
<html><head>
<script type="application/ld+json">
{"@type":"Product","name":"Vino Carmen","sku":"PTV1014030","offers":{"@type":"Offer","price":"17990","priceCurrency":"CLP","availability":"https://schema.org/InStock"},"brand":{"@type":"Brand","name":"Santa Rita"},"image":"https://santaritaonline.com/img.webp","url":"https://santaritaonline.com/producto/vino-carmen/"}
</script>
</head>
<body>
<div id="product-886987" class="product type-product post-886987">
  <span class="sku">PTV1014030</span>
  <button name="add-to-cart" value="886987">Agregar</button>
</div>
</body></html>
"""


def test_scrapling_flag_only_pilot_stores(monkeypatch):
    monkeypatch.setenv("SCRAPLING_STORES", "hites,santaritaonline,lider")
    assert scrapling_html.scrapling_enabled_for("hites") is True
    assert scrapling_html.scrapling_enabled_for("santaritaonline") is True
    assert scrapling_html.scrapling_enabled_for("lider") is False
    monkeypatch.delenv("SCRAPLING_STORES", raising=False)
    assert scrapling_html.scrapling_enabled_for("hites") is False


def test_fetch_html_optional_uses_scrapling_when_flagged(monkeypatch):
    monkeypatch.setenv("SCRAPLING_STORES", "hites")
    monkeypatch.setattr(scrapling_html, "scrapling_available", lambda: True)
    monkeypatch.setattr(
        scrapling_html,
        "fetch_html",
        lambda url, params=None, timeout=30.0: HITES_GRID,
    )
    body = scrapling_html.fetch_html_optional(
        "hites", "https://www.hites.com/grid", params={"q": "tv"}
    )
    assert "961015001" in (body or "")
    assert scrapling_html.fetch_html_optional("paris", "https://example.com") is None


def test_hites_grid_fixture_still_builds_product_schema():
    items = parse_hites_grid(HITES_GRID)
    assert len(items) == 1
    product = hites_item_to_product(items[0], source="search")
    payload = product.to_dict(flatten_specs=False)
    assert payload["store"] == "hites"
    assert payload["product_id"] == "961015001"
    assert payload["price"] == 299990
    assert payload["price_normal"] == 349990
    assert payload["name"]


def test_santarita_fixtures_build_product_schema():
    listing = parse_listing_html(SANTARITA_LISTING)
    assert listing
    row = listing[0]
    listed = santarita_item_to_product(row, source="search")
    assert listed.store == "santaritaonline"
    assert listed.product_id == "890233"
    assert listed.price == 50457

    item = parse_product_html(SANTARITA_PRODUCT)
    assert item is not None
    product = santarita_item_to_product(item, source="product")
    payload = product.to_dict(flatten_specs=False)
    assert payload["store"] == "santaritaonline"
    assert payload["price"] == 17990
    assert payload["product_id"]


def test_hites_prefers_scrapling_html_path(monkeypatch):
    from retail.sources.hites import HitesStore

    monkeypatch.setenv("SCRAPLING_STORES", "hites")
    monkeypatch.setattr(scrapling_html, "scrapling_available", lambda: True)
    monkeypatch.setattr(
        scrapling_html,
        "fetch_html",
        lambda url, params=None, timeout=30.0: HITES_GRID,
    )
    store = HitesStore(delay=0, timeout=5, retries=1)

    def fail_http(*_a, **_k):
        raise AssertionError("no debe usar HTTP si Scrapling responde")

    assert store.http is not None
    monkeypatch.setattr(store.http, "get", fail_http)
    body = store._html("https://www.hites.com/on/demandware.store/Sites-HITES-Site/default/Search-UpdateGrid", {"q": "tv"})
    assert "961015001" in body
    store.close()
