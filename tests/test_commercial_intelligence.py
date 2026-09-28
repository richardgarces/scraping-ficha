from retail.commercial import conditions_compatible, extract_financing, extract_shipping, shipping_comparable
from retail.compare import compare_products, extract_ean, identity_match_confidence
from retail.models import Product
from retail.reales import is_agotado
from retail.stock_validation import find_quantity
from retail.structured_extraction import apply as apply_structured


def product(**overrides):
    data = {
        "product_id": "1",
        "sku_id": "SM-S25-256",
        "name": "Samsung Galaxy S25 256GB",
        "brand": "Samsung",
        "store": "falabella",
        "price": 700000,
    }
    data.update(overrides)
    return Product(**data)


def test_condition_is_detected_and_prevents_new_refurbished_collision():
    new = product(store="falabella", product_id="new", condition="new")
    refurbished = product(
        store="paris",
        product_id="ref",
        name="Samsung Galaxy S25 256GB reacondicionado grado A",
    )
    assert refurbished.condition == "refurbished"
    assert not conditions_compatible(new.condition, refurbished.condition)
    assert len(compare_products([new, refurbished])) == 2


def test_ram_variants_are_not_merged():
    first = product(store="falabella", product_id="8", name="Samsung Galaxy S25 256GB 8GB RAM")
    second = product(store="paris", product_id="12", name="Samsung Galaxy S25 256GB RAM 12GB")
    assert len(compare_products([first, second])) == 2


def test_all_payment_price_wins_over_card_price_for_comparison():
    item = product(
        price=600000,
        price_cmr=600000,
        price_internet=700000,
        price_normal=800000,
    )
    assert item.price == 700000
    assert item.price_all_payment == 700000
    assert item.price_card == 600000
    assert item.payment_card_name == "CMR Falabella"
    assert item.discount_percent == 12


def test_visible_shipping_and_inventory_are_normalized():
    shipping = extract_shipping("Despacho gratis por compras sobre $50.000. Retiro en tienda disponible")
    assert shipping["shipping_free_threshold"] == 50000
    assert shipping["pickup_available"] is True
    item = product(
        description="Últimas 3 unidades. Despacho por $5.990",
        variants=[
            {"id": "m", "name": "M", "inventory_quantity": 2, "available": True},
            {"id": "l", "name": "L", "stock": 1, "available": True},
        ],
    )
    assert item.low_stock is True
    assert item.shipping_cost == 5990
    assert item.stock == 3


def test_zero_numeric_stock_is_not_a_real_offer():
    assert is_agotado({"stock": 0, "availability": ""}) is True


def test_stock_probe_uses_bounded_binary_search():
    calls = []
    quantity = find_quantity(lambda requested: calls.append(requested) or requested <= 13, maximum=50)
    assert quantity == 13
    assert len(calls) < 12


def test_financing_small_print_is_kept_separate_from_price():
    data = extract_financing("Precio en 24 cuotas. CAE 34,8%. Costo total del crédito $780.000.")
    assert data["installment_count"] == 24
    assert data["financial_cae"] == 34.8
    assert data["installment_total"] == 780000


def test_shipping_requires_the_same_region_to_compare_totals():
    assert shipping_comparable([
        {"shipping_cost": 5000, "shipping_region": "Metropolitana"},
        {"shipping_cost": 0, "shipping_region": "Metropolitana"},
    ])
    assert not shipping_comparable([
        {"shipping_cost": 5000, "shipping_region": "Metropolitana"},
        {"shipping_cost": 0, "shipping_region": "Valparaíso"},
    ])


def test_structured_fallback_only_fills_missing_valid_values():
    item = product(price=700000, shipping_cost=None)
    apply_structured(item, {
        "condition": "open_box",
        "shipping_cost": "5990",
        "financial_cae": "34,5",
        "pickup_available": "yes",
        "payment_conditions": "24 cuotas con interés",
    })
    assert item.condition == "open_box"
    assert item.shipping_cost == 5990
    assert item.financial_cae == 34.5
    assert item.pickup_available is None
    assert item.payment_conditions == "24 cuotas con interés"


def test_ean_in_specifications_has_priority_over_store_sku():
    item = product(sku_id="7802900001315", specifications={"Código de barras": "7802900001308"})
    assert extract_ean(item) == "07802900001308"


def test_hybrid_text_joins_reordered_names_with_strict_pack():
    first = product(
        store="lider", product_id="a", brand="Ariel",
        name="Detergente líquido Ariel concentrado 3L limpieza profunda",
    )
    second = product(
        store="tottus", product_id="b", brand="Ariel",
        name="Ariel detergente concentrado líquido limpieza profunda 3 litros",
    )
    confidence, method = identity_match_confidence(first, second)
    assert confidence >= 0.84
    assert method == "hybrid_text"
    group = compare_products([first, second])[0]
    assert group["offer_count"] == 2
    assert group["entity_match_method"] == "hybrid_text"


def test_manufacturer_part_number_joins_different_store_titles():
    first = product(
        store="falabella", product_id="a", name="Lavadora carga frontal blanca 9 kg",
        brand="LG", sku_id="INTERNO-A", specifications={"MPN": "WD9-WVC4S6"},
    )
    second = product(
        store="paris", product_id="b", name="LG AI DD lavadora frontal blanca 9 kg",
        brand="LG", sku_id="INTERNO-B", specifications={"Código fabricante": "WD9WVC4S6"},
    )
    confidence, method = identity_match_confidence(first, second)
    assert confidence == 0.99
    assert method == "manufacturer_code"
    assert compare_products([first, second])[0]["offer_count"] == 2


def test_bundle_is_not_merged_with_product_sold_alone():
    alone = product(store="falabella", product_id="a", name="Samsung Galaxy S25 256GB")
    bundle = product(
        store="paris", product_id="b",
        name="Samsung Galaxy S25 256GB bundle con audífonos",
    )
    confidence, method = identity_match_confidence(alone, bundle)
    assert confidence == 0
    assert method == "strict_mismatch"
    assert len(compare_products([alone, bundle])) == 2


def test_same_ean_does_not_collapse_bundle_into_product_sold_alone():
    alone = product(
        store="falabella", product_id="a", sku_id="7802900001308",
        name="Samsung Galaxy S25 256GB",
    )
    bundle = product(
        store="paris", product_id="b", sku_id="7802900001308",
        name="Samsung Galaxy S25 256GB bundle con audífonos",
    )
    groups = compare_products([alone, bundle])
    assert len(groups) == 2
    assert len({group["compare_code"] for group in groups}) == 2


def test_manual_split_prevents_automatic_match_and_manual_merge_forces_it():
    first = product(store="lider", product_id="a", entity_override="manual:a")
    second = product(store="tottus", product_id="b", entity_override="manual:b")
    assert len(compare_products([first, second])) == 2
    second.entity_override = "manual:a"
    merged = compare_products([first, second])
    assert len(merged) == 1
    assert merged[0]["entity_match_method"] == "manual"
