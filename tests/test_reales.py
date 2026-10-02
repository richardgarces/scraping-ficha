from datetime import datetime, timezone

from retail.reales import is_agotado, is_super_offer, pick_real_offer, previous_full_price_day


def _offer(**kwargs):
    row = {
        "name": "Shampoo XYZ 400ml",
        "brand": "XYZ",
        "compare_code": "ean:123",
        "url": "https://tienda.example/p",
        "has_thumb": False,
        "price_history": [],
    }
    row.update(kwargs)
    return row


def test_agotado_en_nombre_no_es_oferta_real():
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", name="Agotado Shampoo XYZ 400ml", price=6000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is None
    assert is_agotado({"name": "Agotado Shampoo XYZ 400ml"}) is True
    assert is_agotado({"status": "AGOTADO"}) is True
    assert is_agotado({"availability": "Sin stock"}) is True
    assert is_agotado({"name": "Shampoo XYZ 400ml"}) is False


def test_agotado_en_status_no_es_oferta_real():
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=6000,
                price_normal=10000,
                status="Agotado",
            ),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is None


def test_oferta_normal_sigue_calificando():
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", price=6000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["store"] == "falabella"
    assert is_agotado(deal) is False


def test_shampoo_comparacion_vs_otra_tienda_a_precio_normal():
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", price=6000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["store"] == "falabella"
    assert deal["price"] == 6000
    assert deal["rival_store"] == "ripley"
    assert deal["rival_price"] == 10000
    assert deal["kinds"] == ["comparacion"]
    assert deal["discount"] == 40.0
    assert deal["gap_percent"] == 40.0
    assert deal["market_best"] is True
    assert deal["best_price_store"] == "falabella"
    assert deal["strongest_published_store"] == "falabella"
    assert deal["entity_confidence"] >= 0.80
    assert deal["offer_score"] > 50


def test_real_offer_separates_biggest_discount_from_lowest_price():
    deal = pick_real_offer(
        [
            _offer(store="paris", product_id="a", price=8000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=9000, price_normal=18000),
            _offer(store="lider", product_id="c", price=12000, price_normal=12000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["best_price_store"] == "paris"
    assert deal["strongest_published_store"] == "ripley"
    rows = {row["store"]: row for row in deal["stores"]}
    assert rows["paris"]["best_price"] is True
    assert rows["ripley"]["strongest_published"] is True


def test_cross_store_matches_by_name_despite_different_store_codes():
    """Los SKU/EAN internos cambian por tienda: el par se arma por el nombre."""
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="111",
                compare_code="ean:0000000000111",
                price=6000,
                price_normal=10000,
            ),
            _offer(
                store="ripley",
                product_id="999",
                compare_code="ean:0000000000999",
                price=10000,
                price_normal=10000,
            ),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["store"] == "falabella"
    assert deal["rival_store"] == "ripley"
    assert deal["entity_confidence"] >= 0.80


def test_cross_store_rejects_unrelated_product_names():
    assert pick_real_offer(
        [
            _offer(
                store="paris",
                product_id="a",
                name="Producto genérico A",
                brand="",
                compare_code="name:x",
                price=6000,
                price_normal=10000,
            ),
            _offer(
                store="ripley",
                product_id="b",
                name="Otro artículo distinto B",
                brand="",
                compare_code="name:x",
                price=10000,
                price_normal=10000,
            ),
        ],
        comparacion=True,
        historial=False,
    ) is None


def test_no_es_oferta_real_si_todas_las_tiendas_estan_igual_de_baratas():
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", price=6000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=6100, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is None


def test_historial_requiere_un_dia_anterior_sin_descuento():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    history = [
        {"price": 10000, "scraped_at": datetime(2026, 8, 1, tzinfo=timezone.utc).isoformat()},
        {"price": 6000, "scraped_at": now.isoformat()},
    ]
    assert previous_full_price_day(history, 6000, 10000) == "2026-08-01"
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=6000,
                price_normal=10000,
                price_history=history,
            ),
            _offer(store="ripley", product_id="b", price=9500, price_normal=10000),
        ],
        comparacion=False,
        historial=True,
    )
    assert deal is not None
    assert "historial" in deal["kinds"]
    assert deal["was_full_price_on"] == "2026-08-01"


def test_historial_sin_pasado_lleno_no_califica():
    history = [
        {"price": 6000, "scraped_at": "2026-09-01T00:00:00+00:00"},
        {"price": 6000, "scraped_at": "2026-09-14T00:00:00+00:00"},
    ]
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=6000,
                price_normal=10000,
                price_history=history,
            ),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=False,
        historial=True,
    )
    assert deal is None


def test_historial_detecta_baja_real_aunque_la_tienda_no_informe_precio_normal():
    history = [
        {"price": 12000, "scraped_at": "2026-08-01T00:00:00+00:00"},
        {"price": 11800, "scraped_at": "2026-08-15T00:00:00+00:00"},
        {"price": 8000, "scraped_at": "2026-09-14T00:00:00+00:00"},
    ]
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=8000,
                price_normal=None,
                price_history=history,
            ),
            _offer(store="ripley", product_id="b", price=8500, price_normal=None),
        ],
        comparacion=False,
        historial=True,
    )
    assert deal is not None
    assert deal["published_discount"] == 0
    assert deal["verified_discount"] == 32.8
    assert deal["kinds"] == ["historial"]


def test_ambos_tipos_en_el_mismo_aviso():
    history = [
        {"price": 10000, "scraped_at": "2026-08-01T00:00:00+00:00"},
        {"price": 6000, "scraped_at": "2026-09-14T00:00:00+00:00"},
    ]
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=6000,
                price_normal=10000,
                price_history=history,
            ),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=True,
    )
    assert deal is not None
    assert deal["kinds"] == ["comparacion", "historial"]


def test_easy_paris_al_mismo_precio_no_es_oferta_real():
    deal = pick_real_offer(
        [
            _offer(store="easy", product_id="e1", price=399990, price_normal=819990),
            _offer(store="paris", product_id="p1", price=399990, price_normal=829990),
        ],
        comparacion=True,
        historial=False,
        iguales=False,
    )
    assert deal is None


def test_easy_paris_al_mismo_precio_sale_con_el_check():
    deal = pick_real_offer(
        [
            _offer(store="easy", product_id="e1", price=399990, price_normal=819990),
            _offer(store="paris", product_id="p1", price=399990, price_normal=829990),
        ],
        comparacion=False,
        historial=False,
        iguales=True,
    )
    assert deal is not None
    assert deal["kinds"] == ["iguales"]
    assert deal["price"] == 399990
    assert deal["rival_price"] == 399990
    assert deal["gap"] == 0
    assert {row["store"] for row in deal["stores"]} == {"easy", "paris"}


def test_misma_tienda_deja_el_menor_precio_y_compara_contra_ese():
    deal = pick_real_offer(
        [
            _offer(store="paris", product_id="p1", name="Paracetamol 500mg 16 comprimidos", price=16490, price_normal=21290),
            _offer(store="ripley", product_id="r1", name="Paracetamol 500mg 16 comprimidos", price=21290, price_normal=21290),
            _offer(store="ripley", product_id="r1b", name="Paracetamol 500mg caja 16 comp", price=21990, price_normal=24990),
            _offer(store="ripley", product_id="r2", name="Paracetamol 500mg 20 comprimidos", price=20990, price_normal=24190),
            _offer(store="falabella", product_id="f1", name="Paracetamol 1 kg", price=143990, price_normal=143990),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["store"] == "paris"
    assert deal["price"] == 16490
    assert deal["rival_store"] == "ripley"
    assert deal["rival_price"] == 21290
    assert deal["gap"] == 4800
    assert deal["gap_percent"] == 22.5
    stores = [row["store"] for row in deal["stores"]]
    assert stores.count("ripley") == 1
    assert {row["product_id"] for row in deal["stores"]} == {"p1", "r1"}
    ripley = next(row for row in deal["stores"] if row["store"] == "ripley")
    assert ripley["price"] == 21290


def test_easy_barato_y_ripley_a_precio_lleno_si_es_comparacion():
    deal = pick_real_offer(
        [
            _offer(store="easy", product_id="e1", price=399990, price_normal=819990),
            _offer(store="paris", product_id="p1", price=399990, price_normal=829990),
            _offer(store="ripley", product_id="r1", price=829990, price_normal=829990),
        ],
        comparacion=True,
        historial=False,
        iguales=False,
    )
    assert deal is not None
    assert deal["kinds"] == ["comparacion"]
    assert deal["rival_store"] == "ripley"
    assert deal["rival_price"] == 829990
    assert deal["gap"] == 430000
    assert deal["gap_percent"] == 51.8
    assert is_super_offer(deal) is True


def test_super_oferta_por_historial_sobre_50():
    history = [
        {"price": 10000, "scraped_at": "2026-08-01T00:00:00+00:00"},
        {"price": 4500, "scraped_at": "2026-09-14T00:00:00+00:00"},
    ]
    deal = pick_real_offer(
        [
            _offer(
                store="falabella",
                product_id="a",
                price=4500,
                price_normal=10000,
                price_history=history,
            ),
            _offer(store="ripley", product_id="b", price=7000, price_normal=10000),
        ],
        comparacion=False,
        historial=True,
    )
    assert deal is not None
    assert "historial" in deal["kinds"]
    assert deal["discount"] == 55.0
    assert deal["gap_percent"] < 50
    assert is_super_offer(deal) is True


def test_shampoo_40_no_es_super_oferta():
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", price=6000, price_normal=10000),
            _offer(store="ripley", product_id="b", price=10000, price_normal=10000),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is not None
    assert deal["gap_percent"] == 40.0
    assert is_super_offer(deal) is False
    assert is_super_offer(deal, threshold=39.0) is True


def test_iguales_no_califica_como_super():
    deal = pick_real_offer(
        [
            _offer(store="easy", product_id="e1", price=399990, price_normal=819990),
            _offer(store="paris", product_id="p1", price=399990, price_normal=829990),
        ],
        comparacion=False,
        historial=False,
        iguales=True,
    )
    assert deal is not None
    assert deal["kinds"] == ["iguales"]
    assert deal["discount"] > 50
    assert is_super_offer(deal) is False


def test_pack_1_vs_6_no_genera_oferta_por_comparacion():
    """Misma marca/nombre pero distinto envase: no hay brecha entre tiendas."""
    deal = pick_real_offer(
        [
            _offer(
                store="lider",
                product_id="a",
                name="Ozempic 1 unidad",
                brand="Novo",
                price=80000,
                price_normal=120000,
            ),
            _offer(
                store="paris",
                product_id="b",
                name="Ozempic 6 unidades",
                brand="Novo",
                price=400000,
                price_normal=400000,
            ),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is None
