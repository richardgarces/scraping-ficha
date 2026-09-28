from retail.registry import list_stores
from retail.sources.ahumada import listing_item_to_product as ahumada_product
from retail.sources.ahumada import parse_ahumada_target, parse_tile
from retail.sources.cruzverde import listing_item_to_product as cruzverde_product
from retail.sources.cruzverde import parse_cruzverde_target
from retail.sources.salcobrand import parse_salcobrand_target, product_from_graph, score_url


def test_farmacias_are_registered():
    ids = {spec.id for spec in list_stores()}
    assert {"ahumada", "cruzverde", "salcobrand", "drsimi"} <= ids


def test_parse_cruzverde_search_and_product():
    assert parse_cruzverde_target("paracetamol").kind == "search"
    assert parse_cruzverde_target("266145").kind == "product"
    target = parse_cruzverde_target("https://www.cruzverde.cl/product/266145")
    assert target.kind == "product"
    assert target.product_id == "266145"


def test_cruzverde_listing_prices():
    product = cruzverde_product(
        {
            "id": "266145",
            "name": "Xumadol Paracetamol 1000 mg 20 Comprimidos",
            "brand": "ITF LABOMED",
            "price": 11390,
            "prices": {"price-sale-cl": 7690, "price-list-cl": 11390},
            "image_groups": [{"images": [{"link": ""}, {"link": "https://img/x.jpg"}]}],
            "primary_category_id": "medicamentos",
        }
    )
    assert product.store == "cruzverde"
    assert product.price == 7690
    assert product.price_normal == 11390
    assert product.url == "https://www.cruzverde.cl/xumadol-paracetamol-1000-mg-20-comprimidos/266145.html"
    assert product.image_url == "https://img/x.jpg"


def test_parse_cruzverde_current_product_url():
    target = parse_cruzverde_target(
        "https://www.cruzverde.cl/xumadol-paracetamol-1000-mg-20-comprimidos/266145.html"
    )
    assert target.kind == "product"
    assert target.product_id == "266145"


def test_cruzverde_normalizes_producto_alias_to_current_slug_url():
    from retail.models import normalize_product_url

    assert normalize_product_url(
        "cruzverde",
        "https://www.cruzverde.cl/producto/266145",
        "Xumadol Paracetamol 1000 mg 20 Comprimidos",
    ) == "https://www.cruzverde.cl/xumadol-paracetamol-1000-mg-20-comprimidos/266145.html"


def test_cruzverde_removes_internal_clmc_prefix_from_public_url():
    from retail.models import normalize_product_url

    assert normalize_product_url(
        "cruzverde",
        "https://www.cruzverde.cl/product/CLMC_296782",
        "Encrespador de Pestañas Premium",
    ) == "https://www.cruzverde.cl/encrespador-de-pestanas-premium/296782.html"


def test_parse_ahumada_product_url():
    target = parse_ahumada_target(
        "https://www.farmaciasahumada.cl/paracetamol-500mg.-caja-16-comp.ad.-2757.html"
    )
    assert target.kind == "product"
    assert target.product_id == "2757"
    assert parse_ahumada_target("paracetamol").kind == "search"


def test_ahumada_skips_fonasa_copago():
    html = """
    <div class="product-tile" data-pid="2757" data-categories="Medicamentos,Dolor">
      <a href="/paracetamol-500mg.-caja-16-comp.ad.-2757.html">
        <img class="tile-image" src="/2757.jpg" alt="Paracetamol 500mg. Caja 16 Comp.Ad."/>
      </a>
      <span class="sales"><span>$359&nbsp;</span>
        <img class="promotion-badge" src="https://x/badge_fonasa.png"/>
      </span>
      <div class="cmr-price-display"><span class="value" content="618">$618</span></div>
      <del class="precio-normal"><span class="value" content="1309">$1.309</span></del>
    </div>
    """
    item = parse_tile(html)
    assert item is not None
    assert item["pid"] == "2757"
    assert item["price"] == 618
    assert item["price_normal"] == 1309
    product = ahumada_product(item)
    # Fonasa se ignora y CMR se conserva como precio condicionado; para
    # comparar se usa el valor accesible con cualquier medio.
    assert product.price == 1309
    assert product.price_card == 618
    assert product.price_normal == 1309
    assert "fonasa" not in (product.name or "").lower()


def test_ahumada_uses_sales_when_there_is_no_fonasa():
    html = """
    <div class="product-tile" data-pid="9" data-categories="Cuidado">
      <a href="/shampoo-9.html"><img class="tile-image" src="/9.jpg" alt="Shampoo"/></a>
      <div class="promotion-badge-container">$7.000</div>
      <del><span class="strike-through"><span class="value" content="15099">$15.099</span></span></del>
    </div>
    """
    item = parse_tile(html)
    assert item is not None
    assert item["price"] == 7000
    assert item["price_normal"] == 15099


def test_parse_salcobrand_targets():
    assert parse_salcobrand_target("paracetamol").kind == "search"
    assert parse_salcobrand_target("medicamentos").kind == "category"
    product = parse_salcobrand_target(
        "https://salcobrand.cl/products/kitadol-b-paracetamol-500mg-24-comprimidos"
    )
    assert product.kind == "product"
    assert product.product_id == "kitadol-b-paracetamol-500mg-24-comprimidos"


def test_salcobrand_jsonld_prices():
    product = product_from_graph(
        [
            {
                "@type": ["Product", "Drug"],
                "@id": "https://salcobrand.cl/products/kitadol#product",
                "name": "Kitadol (B) Paracetamol 500mg 24 Comprimidos",
                "url": "https://salcobrand.cl/products/kitadol-b-paracetamol-500mg-24-comprimidos",
                "sku": "430924",
                "brand": {"@type": "Brand", "name": "Kitadol"},
                "image": ["https://img/kitadol.jpg"],
                "offers": {"@id": "https://salcobrand.cl/products/kitadol#offer"},
            },
            {
                "@type": "Offer",
                "@id": "https://salcobrand.cl/products/kitadol#offer",
                "price": 1004,
                "priceCurrency": "CLP",
                "priceSpecification": [
                    {
                        "@type": "UnitPriceSpecification",
                        "priceType": "https://schema.org/StrikethroughPrice",
                        "price": 1499,
                    }
                ],
            },
        ]
    )
    assert product is not None
    assert product.store == "salcobrand"
    assert product.price == 1004
    assert product.price_normal == 1499
    assert product.brand == "Kitadol"


def test_salcobrand_score_prefers_full_token_match():
    url = "https://salcobrand.cl/products/kitadol-b-paracetamol-500mg-24-comprimidos"
    assert score_url(url, ["paracetamol", "500mg"]) > score_url(url, ["ibuprofeno"])
    assert score_url(url, ["ibuprofeno"]) == 0
