from retail.registry import STORE_GROUP, list_stores
from retail.sources.decathlon import (
    listing_item_to_product,
    parse_decathlon_target,
    parse_listing_html,
    parse_product_html,
)

LISTING_FIXTURE = r"""
<html><body>
<script>
self.__next_f.push([1,"{\"products\":[{\"id\":\"161592_8403427\",\"supermodelId\":\"161592\",\"skuId\":\"74d92f34-53c1-40e9-99a5-fe19aa86d7da\",\"label\":\"Zapatillas Deportivas PW 100 Ninos Negro Velcro\",\"images\":[{\"src\":\"https://contents.mediadecathlon.com/p2810429/k$abc/picture.jpg\",\"alt\":\"picture\"}],\"url\":\"/p/zapatillas-deportivas-pw-100-ninos-negro-velcro/161592/c382c227m8403427\",\"models\":[{\"brand\":\"DECATHLON\",\"id\":\"8403427\",\"price\":{\"currencies\":{\"main\":{\"valueWithTaxes\":13000,\"currency\":\"CLP\",\"referenceValueWithTaxes\":\"$undefined\",\"discountPercentage\":\"$undefined\"}},\"priceType\":\"STANDARD\"},\"nature\":\"zapatillas\",\"url\":\"/p/zapatillas-deportivas-pw-100-ninos-negro-velcro/161592/c382c227m8403427\"}]},{\"id\":\"999001_1112223\",\"supermodelId\":\"999001\",\"skuId\":\"aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee\",\"label\":\"ZAPATILLAS CAMINATA HOMBRE KLNJ BE GEARED UP NEGRO\",\"images\":[{\"src\":\"https://contents.mediadecathlon.com/p1/k$def/picture.jpg\",\"alt\":\"picture\"}],\"url\":\"/p/zapatillas-caminata-hombre-klnj/999001/c1m1112223\",\"models\":[{\"brand\":\"DECATHLON\",\"id\":\"1112223\",\"price\":{\"currencies\":{\"main\":{\"valueWithTaxes\":30000,\"referenceValueWithTaxes\":35000,\"currency\":\"CLP\",\"discountPercentage\":14}},\"priceType\":\"END_OF_LINE\"},\"nature\":\"zapatillas\",\"url\":\"/p/zapatillas-caminata-hombre-klnj/999001/c1m1112223\"}]}],\"pagination\":{\"total\":9,\"nbItemsPerPage\":40,\"next\":\"search?Ntt=zapatillas\\u0026from=40\\u0026size=40\"}}"])
</script>
</body></html>
"""

PRODUCT_FIXTURE = """
<html><head>
<title>Zapatillas Deportivas PW 100 Niños Negro Velcro | Decathlon</title>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "ProductGroup",
      "@id": "#ItemGroup-161592",
      "name": "Zapatillas Deportivas PW 100 Niños Negro Velcro",
      "brand": {"@type": "Brand", "name": "DECATHLON"},
      "productGroupID": "161592"
    },
    {
      "@type": "Product",
      "isVariantOf": {"@id": "#ItemGroup-161592"},
      "image": "https://contents.mediadecathlon.com/p2810429/k$abc/picture.jpg",
      "name": "Zapatillas Deportivas PW 100 Niños Negro Velcro",
      "offers": {
        "@type": "Offer",
        "url": "https://www.decathlon.cl/p/zapatillas-deportivas-pw-100-ninos-negro-velcro/161592/c382c227m8403427",
        "availability": "https://schema.org/InStock",
        "priceSpecification": {
          "@type": "UnitPriceSpecification",
          "price": 13000,
          "priceCurrency": "CLP",
          "valueAddedTaxIncluded": true
        }
      }
    }
  ]
}
</script>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://www.decathlon.cl/"},
    {"@type": "ListItem", "position": 2, "name": "Deportes", "item": "https://www.decathlon.cl/deportes"},
    {"@type": "ListItem", "position": 3, "name": "Educación física", "item": "https://www.decathlon.cl/deportes/educacion-fisica"},
    {"@type": "ListItem", "position": 4, "name": "Zapatillas niños", "item": "https://www.decathlon.cl/deportes/educacion-fisica/zapatillas-educacion-fisica-ninos"}
  ]
}
</script>
</head><body></body></html>
"""


def test_decathlon_registrada_y_agrupada():
    specs = [spec for spec in list_stores() if spec.id == "decathlon"]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.title == "Decathlon"
    assert spec.group == "deporte"
    assert spec.platform == "decathlon"
    assert STORE_GROUP["decathlon"] == "deporte"


def test_parse_decathlon_targets():
    assert parse_decathlon_target("zapatillas").kind == "search"
    assert parse_decathlon_target("zapatillas").query == "zapatillas"
    search = parse_decathlon_target("https://www.decathlon.cl/search?Ntt=zapatillas")
    assert search.kind == "search"
    assert search.query == "zapatillas"
    category = parse_decathlon_target("mujer/calzado-mujer")
    assert category.kind == "category"
    assert category.category_id == "mujer/calzado-mujer"
    cat_url = parse_decathlon_target("https://www.decathlon.cl/mujer/calzado-mujer")
    assert cat_url.kind == "category"
    assert cat_url.category_id == "mujer/calzado-mujer"
    product = parse_decathlon_target(
        "https://www.decathlon.cl/p/zapatillas-deportivas-pw-100-ninos-negro-velcro/161592/c382c227m8403427"
    )
    assert product.kind == "product"
    assert product.product_id == "161592_8403427"
    assert parse_decathlon_target("161592").kind == "product"
    assert parse_decathlon_target("161592_8403427").kind == "product"


def test_parse_listing_html_prices_and_offer():
    rows = parse_listing_html(LISTING_FIXTURE)
    assert len(rows) == 2
    standard = rows[0]
    assert standard["id"] == "161592_8403427"
    assert "PW 100" in standard["name"]
    assert standard["price"] == 13000
    assert standard["price_normal"] == 13000
    assert standard["brand"] == "DECATHLON"
    assert standard["category"] == "zapatillas"
    assert standard["url"].endswith("/161592/c382c227m8403427")
    assert "mediadecathlon.com" in standard["image_url"]
    offer = rows[1]
    assert offer["price"] == 30000
    assert offer["price_normal"] == 35000
    assert offer["discount_percent"] == 14
    product = listing_item_to_product(offer, source="search")
    assert product.store == "decathlon"
    assert product.seller == "Decathlon"
    assert product.price == 30000
    assert product.price_normal == 35000
    assert product.discount_percent == 14


def test_parse_product_html_json_ld():
    url = "https://www.decathlon.cl/p/zapatillas-deportivas-pw-100-ninos-negro-velcro/161592/c382c227m8403427"
    item = parse_product_html(PRODUCT_FIXTURE, raw_url=url)
    assert item is not None
    assert item["id"] == "161592_8403427"
    assert "PW 100" in item["name"]
    assert item["price"] == 13000
    assert item["brand"] == "DECATHLON"
    assert item["category"] == "Zapatillas niños"
    assert item["image_url"].endswith("picture.jpg")
    product = listing_item_to_product(item, source="product")
    assert product.product_id == "161592_8403427"
    assert product.url.endswith("/161592/c382c227m8403427")
