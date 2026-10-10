from fastapi.testclient import TestClient

from retail.compare import (
    compare_code,
    compare_products,
    pack_of,
    pack_tokens,
    same_product_identity,
)
from retail.models import Product
from retail.search import attach_cheaper_hints, merge_products, refresh_cached_comparisons
from retail.web.app import app


def _product(**kwargs) -> Product:
    data = {
        "product_id": "1",
        "sku_id": "1",
        "name": "Notebook Gamer 15",
        "brand": "HP",
        "store": "falabella",
        "price": 699990,
    }
    data.update(kwargs)
    return Product(**data)


def test_compare_code_prefers_barcode():
    product = _product(sku_id="7801234567894", product_id="interno")
    assert compare_code(product) == "ean:07801234567894"


def test_compare_code_ignores_internal_sku_posing_as_barcode():
    """Tottus manda su SKU de 9 dígitos y Ripley uno que parte en 2000."""
    assert compare_code(_product(sku_id="155105026", product_id="155105025")).startswith("id:")
    assert compare_code(_product(sku_id="2000411435376", product_id="x")).startswith("id:")


def test_compare_groups_same_code_and_marks_lowest():
    groups = compare_products(
        [
            _product(store="falabella", sku_id="7801234567894", price=699990),
            _product(store="ripley", sku_id="7801234567894", name="Notebook Gamer", price=649990),
            _product(store="paris", sku_id="otro", name="Silla oficina", brand="Ikea", price=39990),
        ]
    )
    comparable = [group for group in groups if group["comparable"]]
    assert len(comparable) == 1
    group = comparable[0]
    assert group["lowest_price"] == 649990
    assert group["lowest_stores"] == ["ripley"]
    winners = [offer for offer in group["offers"] if offer["is_lowest"]]
    assert [offer["store"] for offer in winners] == ["ripley"]


def test_same_name_groups_when_there_is_no_barcode():
    groups = compare_products(
        [
            _product(store="falabella", sku_id="fa1", product_id="fa1", price=10000),
            _product(store="paris", sku_id="pa1", product_id="pa1", price=8000),
        ]
    )
    assert groups[0]["comparable"] is True
    assert groups[0]["lowest_stores"] == ["paris"]
    assert groups[0]["kind"] in {"name", "identity"}


def test_en_uno_is_not_a_model_and_does_not_mix_different_products():
    mini_lider = _product(
        store="lider",
        name="Estufa Infrarroja 2 en1 Thor Mini 1500",
        brand="Thorben",
        price=99990,
    )
    mini_ripley = _product(
        store="ripley",
        name="ESTUFA INFRARROJA THORBEN 1500 W 2 EN 1 THOR MINI",
        brand="THORBEN",
        price=109990,
    )
    aire = _product(
        store="falabella",
        name="Aire Acondicionado Portátil Frio/Calor Smart Pac 4 En1 Wifi 14000 Btu",
        brand="THORBEN",
        price=489990,
    )

    assert "en1" not in compare_code(mini_lider)
    assert same_product_identity(mini_lider, mini_ripley)
    assert not same_product_identity(mini_lider, aire)
    groups = compare_products([mini_lider, mini_ripley, aire])
    comparable = [group for group in groups if group["comparable"]]
    assert len(comparable) == 1
    assert {row["store"] for row in comparable[0]["offers"]} == {"lider", "ripley"}


def test_same_phone_groups_across_store_skus():
    groups = compare_products(
        [
            _product(store="falabella", sku_id="17354674", product_id="17354674", name="Celular Galaxy S25 512GB", brand="Samsung", price=899990),
            _product(store="lider", sku_id="888", product_id="888", name="Galaxy S25 5G 512GB 8GB RAM Dual Sim", brand="Samsung", price=864990),
            _product(store="paris", sku_id="999", product_id="999", name="Galaxy S25 FE 256GB", brand="Samsung", price=549990),
        ]
    )
    phones = {group["compare_code"]: group for group in groups}
    s25 = [group for group in groups if "s25" in group["compare_code"] and "s25fe" not in group["compare_code"]]
    fe = [group for group in groups if "s25fe" in group["compare_code"]]
    assert len(s25) == 1
    assert s25[0]["comparable"] is True
    assert set(s25[0]["lowest_stores"]) == {"lider"}
    assert fe and fe[0]["comparable"] is False
    assert all(not code.startswith("ean:17354674") for code in phones)


def test_store_sku_is_not_treated_as_ean():
    product = _product(sku_id="17354674", product_id="17354674", name="Galaxy S25 512GB", brand="Samsung")
    assert compare_code(product).startswith("id:")


def test_merge_prefers_scraped_product():
    stored = [_product(store="falabella", product_id="1", price=90000)]
    scraped = [_product(store="falabella", product_id="1", price=70000)]
    merged, scraped_keys = merge_products(scraped, stored)
    assert len(merged) == 1
    assert merged[0].price == 70000
    assert ("falabella", "1") in scraped_keys


def test_product_from_dict_ignores_extra_fields():
    product = Product.from_dict(
        {
            "product_id": "9",
            "sku_id": "9",
            "name": "Leche",
            "compare_code": "ean:9",
            "is_lowest": True,
            "last_search_query": "leche",
        }
    )
    assert product.name == "Leche"
    assert product.product_id == "9"


def test_web_health_and_stores():
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert "degraded" in body
    assert "mongo_error" in body
    assert body["stores"] > 0
    page = client.get("/")
    assert page.status_code == 200
    assert "Comparador de precios" in page.text
    assert "Ofertas de hoy" in page.text
    assert "Filtrar banda de precio" in page.text
    assert 'id="price-band"' in page.text
    assert 'id="price-band" type="checkbox"' in page.text
    assert 'id="price-band" type="checkbox" checked' not in page.text
    assert 'id="store-groups"' in page.text
    assert '<details id="explore-filters" class="collapsible-filters" data-admin hidden>' in page.text
    assert '<div class="search-opts">' in page.text
    assert '<details class="stores-box">' in page.text
    assert 'value="both" checked' in page.text
    assert 'value="db" checked' not in page.text
    assert 'id="max" type="number" min="1" max="20" value="20"' in page.text
    assert '<div data-admin hidden>\n          <details id="search-detail" class="search-detail" hidden>' in page.text
    assert 'src="/static/app.js?v=' in page.text
    assert 'href="/static/styles.css?v=' in page.text
    styles = __import__("pathlib").Path("retail/web/static/styles.css").read_text()
    assert "[data-admin][hidden] { display: none !important; }" in styles
    hoy = client.get("/hoy")
    assert hoy.status_code == 200
    assert "deal-grid" in hoy.text
    assert 'id="today-filters" class="collapsible-filters"' in hoy.text
    assert 'id="q"' not in hoy.text
    assert health.json().get("qdrant") in {True, False}
    stores = client.get("/api/stores")
    assert any(item["id"] == "falabella" for item in stores.json())
    by_id = {item["id"]: item for item in stores.json()}
    assert by_id["falabella"]["group"] == "retail"
    assert by_id["lider"]["group"] == "supermercados"
    assert by_id["ahumada"]["group"] == "farmacias"
    assert by_id["sodimac"]["group"] == "ferreteria"
    assert by_id["prat"]["group"] == "ferreteria"
    assert by_id["audiomusica"]["group"] == "musica"
    assert by_id["dbs"]["group"] == "belleza"
    assert "Farmacias" in by_id["cruzverde"]["group_title"]
    assert by_id["casaroyal"]["group"] == "retail"
    assert "Retail" in by_id["casaroyal"]["group_title"]
    assert "Belleza" in by_id["sallybeauty"]["group_title"]
    assert by_id["vans"]["group"] == "calzado"
    assert by_id["dcshoes"]["group"] == "calzado"
    assert by_id["maui"]["group"] == "moda"
    assert by_id["ansaldo"]["group"] == "juguetes"
    assert by_id["amesti"]["group"] == "ferreteria"
    assert by_id["bebesit"]["group"] == "infantil"
    assert by_id["lavinoteca"]["group"] == "gastronomia"
    assert "Ópticas" in by_id["gmo"]["group_title"]


def test_web_health_marks_degraded_when_mongo_queries_fail(monkeypatch):
    class BrokenRepo:
        def count(self):
            raise RuntimeError("boom")

        def real_offer_worker_status(self):
            raise RuntimeError("boom")

        def close(self):
            return None

    monkeypatch.setattr("retail.web.app.connect_repo", lambda: BrokenRepo())
    monkeypatch.setattr("retail.web.app.connect_qdrant", lambda: None)
    monkeypatch.setattr("retail.search_cache.connect_redis", lambda: None)
    body = TestClient(app).get("/api/health").json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["mongo"] is False
    assert body["mongo_error"] == "RuntimeError"
    assert body["products"] == 0


def test_non_admin_search_options_are_forced_to_safe_defaults():
    from retail.web.app import _search_args_for_role

    args = _search_args_for_role(
        False,
        "notebook",
        "scrape",
        "falabella",
        3,
        0.5,
        True,
        True,
    )
    assert args["source"] == "both"
    assert args["stores"] is None
    assert args["max_items"] == 20
    assert args["price_band"] is False
    assert args["fresh"] is False


def test_admin_keeps_advanced_search_options():
    from retail.web.app import _search_args_for_role

    args = _search_args_for_role(True, "notebook", "scrape", "falabella", 3, 0.5, True, True)
    assert args["source"] == "scrape"
    assert args["stores"] == ["falabella"]
    assert args["max_items"] == 3
    assert args["price_band"] is True
    assert args["fresh"] is True


def test_quick_search_uses_only_the_database_for_every_role():
    from retail.web.app import _search_args_for_role

    visitor = _search_args_for_role(False, "notebook", "scrape", "falabella", 3, 0.5, True, True, True)
    admin = _search_args_for_role(True, "notebook", "both", "falabella", 3, 0.5, True, True, True)

    assert visitor["source"] == "db"
    assert visitor["stores"] is None
    assert visitor["fresh"] is False
    assert visitor["recover_underfilled_db"] is False
    assert admin["source"] == "db"
    assert admin["stores"] == ["falabella"]
    assert admin["fresh"] is False
    assert admin["recover_underfilled_db"] is False


def test_admin_web_search_rejects_bad_source(monkeypatch):
    monkeypatch.setattr("retail.web.app.request_is_admin", lambda request: True)
    client = TestClient(app)
    response = client.get("/api/search", params={"q": "leche", "source": "otro"})
    assert response.status_code == 400


def _tv(store: str, name: str, price: int, **kwargs) -> Product:
    return _product(store=store, name=name, brand="Samsung", price=price, product_id=f"{store}-{price}", **kwargs)


def test_screen_size_splits_televisions_of_the_same_model():
    """El U8000H de 43" y el de 65" no son el mismo producto."""
    groups = compare_products(
        [
            _tv("tottus", "Smart Tv 43 Crystal Uhd U8000H 4K 2026", 299990),
            _tv("falabella", '43" Crystal UHD U8000H 4K Smart TV', 319990),
            _tv("tottus", "Smart Tv 65 Crystal Uhd U8000H 4K 2026", 514990),
        ]
    )
    assert len(groups) == 2
    grande = next(group for group in groups if group["lowest_price"] == 514990)
    assert not grande["comparable"]
    chico = next(group for group in groups if group["lowest_price"] == 299990)
    assert sorted(offer["store"] for offer in chico["offers"]) == ["falabella", "tottus"]


def test_long_manufacturer_code_matches_the_short_one():
    """Ripley publica UN50U8000HGXZS donde Falabella publica U8000H."""
    groups = compare_products(
        [
            _tv("falabella", '50" Crystal UHD U8000H 4K Smart TV', 329990),
            _tv("ripley", 'SMART TV SAMSUNG LED 4K UHD 50” UN50U8000HGXZS', 349990),
        ]
    )
    assert len(groups) == 1
    assert groups[0]["comparable"]


def test_tier_word_keeps_phone_models_apart():
    codes = {
        compare_code(_product(name=name, brand="Samsung", sku_id=name, product_id=name))
        for name in (
            "Celular Galaxy S25 256GB",
            'CELULAR SAMSUNG GALAXY S25+ 6.7" 256 GB',
            "CELULAR SAMSUNG GALAXY ULTRA S25 256 GB",
            "Celular Galaxy S25 Ultra 256GB",
            "Celular Galaxy S25 FE 256GB",
        )
    }
    # S25, S25+, S25 Ultra y S25 FE son cuatro teléfonos, y da igual el orden
    # en que la tienda escriba "Ultra".
    assert len(codes) == 4
    assert "id:samsung|s25ultra|256gb|1un" in codes
    assert "id:samsung|s25plus|256gb|1un" in codes


def test_grouping_joins_barcode_and_fingerprint_namespaces():
    """Una tienda publica el código de barras y la otra no: igual se juntan."""
    groups = compare_products(
        [
            _product(store="lider", name="Notebook Gamer 15", sku_id="7801234567894", product_id="l1", price=649990),
            _product(store="paris", name="Notebook Gamer 15", sku_id="interno-9", product_id="p1", price=699990),
        ]
    )
    assert len(groups) == 1
    assert groups[0]["comparable"]
    assert groups[0]["compare_code"] == "ean:07801234567894"


def test_normalize_gtin_rejects_codes_that_are_not_product_barcodes():
    from retail.compare import normalize_gtin

    assert normalize_gtin("7801234567894") == "07801234567894"
    assert normalize_gtin("036000291452") == "00036000291452"  # UPC de 12, rellenado a 14
    assert normalize_gtin("00880609767433") is None  # el de Líder no cuadra el verificador
    assert normalize_gtin("2000411435376") is None  # rango interno del comercio
    assert normalize_gtin("17366557") is None  # product_id de 8 dígitos con suerte
    assert normalize_gtin("155105026") is None  # SKU de 9 dígitos
    assert normalize_gtin("") is None


def test_categories_endpoint_answers():
    """Falló en producción con NameError: ASCENDING vivía solo en __init__."""
    client = TestClient(app)
    response = client.get("/api/categories", params={"limit": 1})
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert "items" in response.json()


def test_collapse_mirrors_joins_falabella_and_sodimac():
    from retail.compare import collapse_mirrors

    salida = collapse_mirrors(
        [
            {"store": "sodimac", "store_title": "Sodimac Chile", "product_id": "80748819", "price": 639990, "name": "TV"},
            {"store": "falabella", "store_title": "Falabella Chile", "product_id": "80748819", "price": 639990, "name": "TV"},
            {"store": "ripley", "store_title": "Ripley", "product_id": "80748819", "price": 639990, "name": "TV"},
        ]
    )
    assert len(salida) == 2
    falabella = next(row for row in salida if row["store"] == "falabella")
    assert falabella["mirrors"]["stores"] == ["sodimac"]
    assert falabella["mirrors"]["store_titles"] == ["Sodimac Chile"]
    assert any(row["store"] == "ripley" for row in salida)


def test_collapse_mirrors_keeps_cheapest_sister_when_price_differs():
    """Sodimac ≡ Falabella: distinto precio no inventa ahorro; queda el más barato."""
    from retail.compare import collapse_mirrors

    salida = collapse_mirrors(
        [
            {"store": "falabella", "product_id": "1", "price": 100000},
            {"store": "sodimac", "product_id": "1", "price": 89000},
        ]
    )
    assert len(salida) == 1
    assert salida[0]["store"] == "sodimac"
    assert salida[0]["price"] == 89000
    assert salida[0]["mirrors"]["stores"] == ["falabella"]


def test_same_retailer_aliases_sodimac_falabella():
    from retail.compare import normalize_store_id, same_retailer, store_family

    assert normalize_store_id("Sodimac Homecenter") == "sodimac"
    assert normalize_store_id("Falabella.com") == "falabella"
    assert store_family("sodimac") == store_family("falabella") == "falabella"
    assert same_retailer("sodimac", "falabella") is True
    assert same_retailer("sodimac", "paris") is False
    assert same_retailer("paris", "easy") is True
    assert same_retailer("falabella", "ripley") is False


def test_collapse_display_stops_calling_mirrors_comparable():
    from retail.compare import collapse_display

    groups = collapse_display(
        [
            {
                "comparable": True,
                "offers": [
                    {"store": "falabella", "product_id": "1", "price": 100000, "name": "TV"},
                    {"store": "sodimac", "product_id": "1", "price": 100000, "name": "TV"},
                ],
            }
        ]
    )
    assert len(groups[0]["offers"]) == 1
    assert groups[0]["comparable"] is False
    assert groups[0]["offers"][0]["comparable"] is False


def test_collapse_variants_keeps_cheapest_and_reports_range():
    from retail.compare import collapse_variants

    filas = [
        {"store": "ikea", "name": "HOPPVALS Cortina celular", "product_id": "b", "price": 37990},
        {"store": "ikea", "name": "HOPPVALS Cortina celular", "product_id": "a", "price": 25990},
        {"store": "ikea", "name": "HOPPVALS Cortina celular", "product_id": "c", "price": 28990},
        {"store": "ikea", "name": "BILLY Estante", "product_id": "d", "price": 49990},
        # Mismo nombre en otra tienda: eso es comparación entre tiendas, no variante.
        {"store": "falabella", "name": "HOPPVALS Cortina celular", "product_id": "e", "price": 31990},
    ]
    salida = collapse_variants(filas)
    assert len(salida) == 3
    cortina = next(row for row in salida if row["store"] == "ikea" and "HOPPVALS" in row["name"])
    assert cortina["product_id"] == "a"  # se queda la más barata
    assert cortina["variants"] == {"count": 3, "min_price": 25990, "max_price": 37990}
    assert "variants" not in next(row for row in salida if row["name"] == "BILLY Estante")


def test_collapse_variants_ignores_accents_and_leaves_priceless_behind():
    from retail.compare import collapse_variants

    salida = collapse_variants(
        [
            {"store": "paris", "name": "Sillón Café", "product_id": "x", "price": None},
            {"store": "paris", "name": "SILLON CAFE", "product_id": "y", "price": 80000},
        ]
    )
    assert len(salida) == 1
    assert salida[0]["product_id"] == "y"
    assert salida[0]["variants"]["count"] == 2


def test_attach_cheaper_hints_on_each_offer():
    from datetime import datetime, timezone

    groups = [
        {
            "offers": [
                {
                    "store": "ripley",
                    "store_title": "Ripley",
                    "price": 100000,
                    "price_history": [
                        {
                            "price": 70000,
                            "scraped_at": datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat(),
                        }
                    ],
                },
                {
                    "store": "falabella",
                    "store_title": "Falabella",
                    "price": 80000,
                    "price_history": [],
                },
            ]
        }
    ]
    attach_cheaper_hints(groups)
    dear = groups[0]["offers"][0]
    cheap = groups[0]["offers"][1]
    assert dear["cheaper_elsewhere"]["store"] == "falabella"
    assert dear["cheaper_elsewhere"]["price"] == 80000
    assert dear["cheaper_before"]["price"] == 70000
    assert cheap["cheaper_elsewhere"] is None
    assert cheap["cheaper_before"] is None


def test_partybox_encore_generations_are_separate_but_second_generation_groups():
    groups = compare_products(
        [
            _product(
                store="ebest", product_id="32672", sku_id="32672",
                name="JBL Partybox Encore 2 Essential", brand=None, price=199990,
            ),
            _product(
                store="entel", product_id="prod2380057", sku_id="PO_B_17949",
                name="Partybox Encore Essential", brand="JBL", price=264990,
            ),
            _product(
                store="pcfactory", product_id="57197", sku_id="57197",
                name="JBL PartyBox Encore Essential 2", brand="JBL", price=249990,
            ),
            _product(
                store="entel", product_id="prod2660044", sku_id="PO_B_20490",
                name="PartyBox Encore Essential 2", brand="JBL", price=279990,
            ),
        ]
    )

    second_generation = next(group for group in groups if group["lowest_price"] == 199990)
    first_generation = next(
        group for group in groups
        if any(offer["product_id"] == "prod2380057" for offer in group["offers"])
    )
    assert {offer["product_id"] for offer in second_generation["offers"]} == {
        "32672", "57197", "prod2660044",
    }
    assert second_generation["lowest_stores"] == ["ebest"]
    assert [offer["product_id"] for offer in first_generation["offers"]] == ["prod2380057"]
    assert first_generation["comparable"] is False

    attach_cheaper_hints(groups)
    offers = {offer["product_id"]: offer for offer in second_generation["offers"]}
    assert offers["32672"]["cheaper_elsewhere"] is None
    assert offers["prod2660044"]["cheaper_elsewhere"] == {
        "store": "ebest",
        "store_title": "ebest",
        "price": 199990,
        "gap": 80000,
        "gap_percent": 28.6,
    }
    assert first_generation["offers"][0]["cheaper_elsewhere"] is None


def test_old_cached_search_is_regrouped_before_serving():
    rows = [
        {
            "store": "ebest", "product_id": "32672", "sku_id": "32672",
            "name": "JBL Partybox Encore 2 Essential", "brand": None, "price": 199990,
        },
        {
            "store": "pcfactory", "product_id": "57197", "sku_id": "57197",
            "name": "JBL PartyBox Encore Essential 2", "brand": "JBL", "price": 249990,
        },
        {
            "store": "entel", "product_id": "old", "sku_id": "old",
            "name": "Partybox Encore Essential", "brand": "JBL", "price": 264990,
            "cheaper_elsewhere": {"store": "pcfactory", "price": 249990},
        },
    ]
    cached = {"groups": [{"offers": rows}], "rows": rows, "comparison_version": 1}

    refresh_cached_comparisons(cached)

    by_id = {row["product_id"]: row for row in cached["rows"]}
    assert cached["comparison_version"] == 2
    assert by_id["32672"]["cheaper_elsewhere"] is None
    assert by_id["57197"]["cheaper_elsewhere"]["store"] == "ebest"
    assert by_id["old"]["cheaper_elsewhere"] is None


def test_pack_count_splits_tablets_of_the_same_name():
    """16 comprimidos y 20 no son el mismo producto, aunque el resto coincida."""
    groups = compare_products(
        [
            _product(store="lider", name="Paracetamol 500mg 16 comprimidos", brand="Genfar", product_id="l16", sku_id="l16", price=5440),
            _product(store="paris", name="Paracetamol 500 mg caja 16 comp", brand="Genfar", product_id="p16", sku_id="p16", price=7990),
            _product(store="lider", name="Paracetamol 500mg 20 comprimidos", brand="Genfar", product_id="l20", sku_id="l20", price=7990),
        ]
    )
    sixteen = next(group for group in groups if any("16" in offer["name"] and "20" not in offer["name"] for offer in group["offers"]))
    twenty = next(group for group in groups if any("20" in offer["name"] for offer in group["offers"]))
    assert sixteen["comparable"] is True
    assert {offer["store"] for offer in sixteen["offers"]} == {"lider", "paris"}
    assert twenty["comparable"] is False
    assert all("20" not in offer["name"] for offer in sixteen["offers"])


def test_liter_matches_milliliters_but_not_another_volume():
    same = compare_products(
        [
            _product(store="lider", name="Leche entera 1 L", brand="Soprole", product_id="a", sku_id="a", price=1000),
            _product(store="paris", name="Leche entera 1000 ml", brand="Soprole", product_id="b", sku_id="b", price=1100),
        ]
    )
    split = compare_products(
        [
            _product(store="lider", name="Shampoo XYZ 400ml", brand="XYZ", product_id="c", sku_id="c", price=6000),
            _product(store="paris", name="Shampoo XYZ 1 L", brand="XYZ", product_id="d", sku_id="d", price=10000),
        ]
    )
    assert len(same) == 1
    assert same[0]["comparable"] is True
    assert len(split) == 2
    assert all(not group["comparable"] for group in split)


def test_pack_tokens_spanish_unit_patterns():
    assert "6un" in pack_tokens("Producto x6")
    assert "6un" in pack_tokens("Producto 6u")
    assert "6un" in pack_tokens("Producto 6 un")
    assert "6un" in pack_tokens("Producto 6 pack")
    assert "6un" in pack_tokens("Producto caja 6")
    assert "6un" in pack_tokens("Producto set 6")
    assert "6un" in pack_tokens("Producto multipack 6")
    assert "6un" in pack_tokens("cajita 6")
    assert pack_tokens("Ozempic") == ("1un",)
    assert pack_tokens("Ozempic 1 unidad") == ("1un",)
    assert pack_tokens("Ozempic 6 unidades") == ("6un",)
    # Modelo / pulgadas no son cantidad de envase.
    assert pack_tokens("iPhone 16 Pro") == ("1un",)
    assert "65un" not in pack_tokens("Smart TV 65 pulgadas")
    assert pack_tokens("Smart TV 65 pulgadas") == ("1un",)


def test_pack_tokens_preserves_decimal_kg_and_case():
    assert "1500g" in pack_tokens("Azúcar granulada lansa 1.5 kg")
    assert "1500g" in pack_tokens("Azúcar Granulada 1,5 Kg")
    assert "1000g" in pack_tokens("Azúcar Granulada 1 Kg")
    assert "400g" in pack_tokens("Azúcar granulada Iansa, 400 g")


def test_one_unit_vs_six_not_comparable_but_same_pack_is():
    """1 unidad y 6 unidades no se comparan entre tiendas; dos de 6 sí."""
    split = compare_products(
        [
            _product(store="lider", name="Ozempic 1 unidad", brand="Novo", product_id="a", sku_id="a", price=80000),
            _product(store="paris", name="Ozempic 6 unidades", brand="Novo", product_id="b", sku_id="b", price=400000),
        ]
    )
    assert len(split) == 2
    assert all(not group["comparable"] for group in split)

    same = compare_products(
        [
            _product(store="lider", name="Ozempic x6", brand="Novo", product_id="c", sku_id="c", price=390000),
            _product(store="paris", name="Ozempic pack 6", brand="Novo", product_id="d", sku_id="d", price=400000),
        ]
    )
    assert len(same) == 1
    assert same[0]["comparable"] is True


def test_omitted_qty_defaults_to_one_and_matches_explicit_one():
    groups = compare_products(
        [
            _product(store="lider", name="Ozempic", brand="Novo", product_id="a", sku_id="a", price=80000),
            _product(store="paris", name="Ozempic 1 unidad", brand="Novo", product_id="b", sku_id="b", price=82000),
            _product(store="ripley", name="Ozempic 6 unidades", brand="Novo", product_id="c", sku_id="c", price=400000),
        ]
    )
    single = next(group for group in groups if any(offer["store"] == "lider" for offer in group["offers"]))
    assert single["comparable"] is True
    assert {offer["store"] for offer in single["offers"]} == {"lider", "paris"}
    assert all("6" not in offer["name"] for offer in single["offers"])
    assert pack_of(_product(name="Ozempic", brand="Novo")) == ("1un",)


def test_pack_qty_from_specifications():
    lone = _product(store="lider", name="Yogurt Colun", brand="Colun", product_id="a", sku_id="a", price=1000)
    pack = _product(
        store="paris",
        name="Yogurt Colun",
        brand="Colun",
        product_id="b",
        sku_id="b",
        price=5000,
        specifications={"contenido": "pack 6"},
    )
    groups = compare_products([lone, pack])
    assert len(groups) == 2
    assert all(not group["comparable"] for group in groups)
