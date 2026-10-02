from retail.registry import STORE_GROUP, list_stores
from retail.sources.santaritaonline import (
    AGE_COOKIE,
    DEFAULT_COMUNA,
    listing_item_to_product,
    parse_listing_html,
    parse_product_html,
    parse_santaritaonline_target,
)

LISTING_FIXTURE = """
<ul class="products products-container grid">
<li class="product-col product-default product type-product post-890233 status-publish first instock product_cat-packs has-post-thumbnail sale shipping-taxable purchasable product-type-simple">
<div class="product-inner">
  <div class="product-image">
    <a href="https://santaritaonline.com/producto/pack-escudo-de-casa-real-carmenere-cabernet-sauvignon-2/">
      <div class="labels"><div class="onsale">45%</div></div>
      <div class="inner"><img width="800" height="800" src="https://santaritaonline.com/wp-content/uploads/2026/07/2-1.png" class=" wp-post-image" alt="" /></div>
    </a>
  </div>
  <div class="product-content">
    <a class="product-loop-title" href="https://santaritaonline.com/producto/pack-escudo-de-casa-real-carmenere-cabernet-sauvignon-2/">
      <h3 class="woocommerce-loop-product__title">Pack Escudo de Casa Real Carmenere y Cabernet Sauvignon</h3>
    </a>
    <span class="price"><ins><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">$</span>50.457</bdi></span></ins> <del><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">$</span>91.740</bdi></span></del></span>
    <a href="/?add-to-cart=890233" data-quantity="1" class="button product_type_simple add_to_cart_button ajax_add_to_cart" data-product_id="890233" data-product_sku="PAK1021330">Agregar</a>
    <span class="gtm4wp_productdata" style="display:none; visibility:hidden;" data-gtm4wp_product_data="{&quot;internal_id&quot;:890233,&quot;item_id&quot;:890233,&quot;item_name&quot;:&quot;Pack Escudo de Casa Real Carmenere y Cabernet Sauvignon&quot;,&quot;sku&quot;:&quot;PAK1021330&quot;,&quot;price&quot;:50457,&quot;stocklevel&quot;:16,&quot;stockstatus&quot;:&quot;instock&quot;,&quot;item_category&quot;:&quot;Packs&quot;,&quot;id&quot;:890233,&quot;productlink&quot;:&quot;https:\\/\\/santaritaonline.com\\/producto\\/pack-escudo-de-casa-real-carmenere-cabernet-sauvignon-2\\/&quot;,&quot;item_brand&quot;:&quot;&quot;}"></span>
  </div>
</div>
</li>
</ul>
"""

PRODUCT_FIXTURE = """
<html><head>
<meta property="og:title" content="Vino Carmen Delanz Carmenere Apalta 2024 750cc | Santa Rita" />
<meta property="og:url" content="https://santaritaonline.com/producto/vino-carmen-delanz-carmenere-apalta-2024-750cc-2/" />
<meta property="og:image" content="https://santaritaonline.com/wp-content/uploads/2026/06/Vino_DelanzApalta2024.webp" />
<script type="application/ld+json">
[
  {"@type":"BreadcrumbList","itemListElement":[]},
  {
    "@context":"https://schema.org/",
    "@type":"Product",
    "url":"https://santaritaonline.com/producto/vino-carmen-delanz-carmenere-apalta-2024-750cc-2/",
    "name":"Vino Carmen Delanz Carmenere Apalta 2024 750cc",
    "sku":"PTV1014030-24-NC",
    "description":"Ensamblaje Carménère de Apalta.",
    "image":[{"@type":"ImageObject","url":"https://santaritaonline.com/wp-content/uploads/2026/06/Vino_DelanzApalta2024.webp"}],
    "brand":{"@type":"Brand","name":"Santa Rita"},
    "offers":{"@type":"Offer","availability":"https://schema.org/InStock","price":"17990","priceCurrency":"CLP","url":"https://santaritaonline.com/producto/vino-carmen-delanz-carmenere-apalta-2024-750cc-2/"}
  }
]
</script>
</head>
<body>
<div id="product-886987" class="product type-product post-886987">
  <span class="sku">PTV1014030-24-NC</span>
  <span class="price"><span class="woocommerce-Price-amount amount"><bdi><span class="woocommerce-Price-currencySymbol">$</span>17.990</bdi></span></span>
  <form>
    <button type="submit" name="add-to-cart" value="886987">Agregar</button>
  </form>
</div>
</body></html>
"""


def test_santaritaonline_registrada_y_agrupada():
    specs = [spec for spec in list_stores() if spec.id == "santaritaonline"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.title == "Santa Rita Online"
    assert spec.group == "gastronomia"
    assert spec.platform == "woocommerce"
    assert STORE_GROUP["santaritaonline"] == "gastronomia"
    assert AGE_COOKIE.startswith("resp-agev-age-verification-passed=")
    assert DEFAULT_COMUNA == "PROVIDENCIA"


def test_parse_santaritaonline_targets():
    assert parse_santaritaonline_target("carmenere").kind == "search"
    assert parse_santaritaonline_target("carmenere").query == "carmenere"
    search = parse_santaritaonline_target(
        "https://santaritaonline.com/?s=carmenere&post_type=product"
    )
    assert search.kind == "search"
    assert search.query == "carmenere"
    product = parse_santaritaonline_target(
        "https://santaritaonline.com/producto/vino-carmen-delanz-carmenere-apalta-2024-750cc-2/"
    )
    assert product.kind == "product"
    assert product.product_id == "vino-carmen-delanz-carmenere-apalta-2024-750cc-2"
    assert parse_santaritaonline_target("886987").kind == "product"
    assert parse_santaritaonline_target("886987").product_id == "886987"
    category = parse_santaritaonline_target(
        "https://santaritaonline.com/categoria/lineas-de-vino/ultra-premium/"
    )
    assert category.kind == "category"
    assert category.category_id == "lineas-de-vino/ultra-premium"
    assert parse_santaritaonline_target("lineas-de-vino/ultra-premium").kind == "category"


def test_parse_listing_html_card_prices_and_gtm():
    rows = parse_listing_html(LISTING_FIXTURE)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "890233"
    assert row["sku"] == "PAK1021330"
    assert "Escudo de Casa Real" in row["name"]
    assert row["price"] == 50457
    assert row["price_normal"] == 91740
    assert row["discount_percent"] == 45
    assert row["category"] == "Packs"
    assert row["url"].endswith("/producto/pack-escudo-de-casa-real-carmenere-cabernet-sauvignon-2/")
    assert row["image_url"].endswith("/2-1.png")
    assert row["availability"] == "En stock"
    assert row["stock"] == 16
    product = listing_item_to_product(row, source="search")
    assert product.store == "santaritaonline"
    assert product.seller == "Santa Rita Online"
    assert product.price == 50457
    assert product.price_normal == 91740
    assert product.sku_id == "PAK1021330"


def test_parse_product_html_schema():
    item = parse_product_html(PRODUCT_FIXTURE)
    assert item is not None
    assert item["id"] == "886987"
    assert item["sku"] == "PTV1014030-24-NC"
    assert "Carmen Delanz" in item["name"]
    assert item["price"] == 17990
    assert item["price_normal"] == 17990
    assert item["brand"] == "Santa Rita"
    assert item["availability"] == "En stock"
    assert item["image_url"].endswith("Vino_DelanzApalta2024.webp")
    product = listing_item_to_product(item, source="product")
    assert product.product_id == "886987"
    assert product.url.endswith("/vino-carmen-delanz-carmenere-apalta-2024-750cc-2/")
