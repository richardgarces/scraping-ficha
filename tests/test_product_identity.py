from datetime import datetime, timezone

from retail.compare import normalize_gtin
from retail.product_identity import build_product_identity_records


def _valid_gtin13() -> str:
    base = "780123456789"
    weighted = sum(
        int(digit) * (3 if index % 2 == 0 else 1)
        for index, digit in enumerate(reversed(base))
    )
    return f"{base}{(10 - weighted % 10) % 10}"


def _product(**changes):
    document = {
        "store": "falabella",
        "product_id": "sku-1",
        "sku_id": "sku-1",
        "name": "Producto de prueba",
        "brand": "Marca",
        "price": 10000,
        "currency": "CLP",
        "updated_at": datetime(2026, 4, 5, tzinfo=timezone.utc),
    }
    document.update(changes)
    return document


def test_valid_gtin_is_the_only_automatic_cross_offer_canonical_key():
    gtin = _valid_gtin13()
    one = build_product_identity_records(
        _product(specifications={"EAN": gtin}),
    )
    two = build_product_identity_records(
        _product(store="ripley", product_id="another-sku", specifications={"GTIN": gtin}),
    )

    assert one["catalog_products"][0]["_id"] == two["catalog_products"][0]["_id"]
    assert one["catalog_products"][0]["gtin"] == normalize_gtin(gtin)
    assert one["product_matches"][0]["review_status"] == "approved"
    assert one["product_matches"][0]["confidence_score"] == 1.0
    assert one["product_matches"][0]["method"] == "deterministic"


def test_heuristic_comparison_stays_provisional_and_does_not_merge_products():
    one = build_product_identity_records(
        _product(compare_code="identity:phone", entity_confidence=0.91, entity_match_method="identity"),
    )
    two = build_product_identity_records(
        _product(
            store="ripley",
            product_id="sku-2",
            compare_code="identity:phone",
            entity_confidence=0.91,
            entity_match_method="identity",
        ),
    )

    assert one["catalog_products"][0]["_id"] != two["catalog_products"][0]["_id"]
    assert one["product_matches"][0]["candidate_key"] == "identity:phone"
    assert one["product_matches"][0]["confidence_score"] == 0.91
    assert one["product_matches"][0]["review_status"] == "pending"


def test_ai_matching_method_is_kept_distinct():
    records = build_product_identity_records(
        _product(compare_code="candidate:1", entity_confidence=0.72, entity_match_method="llm"),
    )

    assert records["product_matches"][0]["method"] == "ai"
    assert records["product_matches"][0]["review_status"] == "pending"


def test_manual_override_is_preserved_as_an_approved_match():
    one = build_product_identity_records(
        _product(entity_override="manual:phone:256gb", entity_match_method="manual"),
    )
    two = build_product_identity_records(
        _product(
            store="ripley",
            product_id="sku-2",
            entity_override="manual:phone:256gb",
            entity_match_method="manual",
        ),
    )

    assert one["catalog_products"][0]["_id"] == two["catalog_products"][0]["_id"]
    assert one["product_matches"][0]["method"] == "manual"
    assert one["product_matches"][0]["review_status"] == "approved"


def test_invalid_gtin_does_not_merge_and_explicit_specs_form_variant():
    one = build_product_identity_records(
        _product(
            specifications={
                "EAN": "123",
                "Capacidad": "256 GB",
                "Color": "Azul",
                "Contenido neto": "500 ml",
            },
        ),
    )
    two = build_product_identity_records(
        _product(store="ripley", product_id="sku-2", specifications={"EAN": "123"}),
    )

    product = one["catalog_products"][0]
    variant = one["product_variants"][0]
    assert product["_id"] != two["catalog_products"][0]["_id"]
    assert "gtin" not in product
    assert product["quantity"] == 500
    assert product["unit"] == "ml"
    assert variant["capacity"] == "256 GB"
    assert variant["color"] == "Azul"
    assert one["offers"][0]["variant_id"] == variant["_id"]


def test_variant_attributes_are_read_from_top_level_product_fields():
    records = build_product_identity_records(
        _product(capacity="256 GB", color="Azul", pack="Pack de 2"),
    )

    assert records["product_variants"][0]["capacity"] == "256 GB"
    assert records["product_variants"][0]["color"] == "Azul"
    assert records["product_variants"][0]["pack"] == "Pack de 2"


def test_price_promotion_and_shipping_facts_stay_separate_and_timestamped():
    observed_at = datetime(2026, 4, 4, 10, tzinfo=timezone.utc)
    records = build_product_identity_records(
        _product(
            scraped_at=observed_at.isoformat(),
            price_all_payment=10000,
            price_card=9000,
            payment_card_name="Tarjeta tienda",
            price_coupon=8000,
            coupon_code="AHORRO",
            shipping_cost=0,
            shipping_region="RM",
            price_history=[
                {"price": 11000, "scraped_at": "2026-04-03T10:00:00Z", "price_basis": "all_payment"},
            ],
        ),
        now=datetime(2026, 4, 5, tzinfo=timezone.utc),
        include_history=True,
    )

    assert len(records["price_observations"]) == 2
    assert all(row["currency"] == "CLP" for row in records["price_observations"])
    assert all(row["observed_at"].tzinfo is not None for row in records["price_observations"])
    assert all("stock" not in row for row in records["price_observations"])
    promotions = {row["type"]: row for row in records["promotion_conditions"]}
    assert promotions["card"]["price"] == 9000
    assert promotions["coupon"]["price"] == 8000
    quote = records["shipping_quotes"][0]
    assert quote["cost"] == 0
    assert quote["region"] == "RM"
    assert quote["comuna"] is None


def test_undated_historical_points_and_promotions_do_not_get_a_fabricated_time():
    records = build_product_identity_records(
        _product(
            scraped_at=None,
            updated_at=None,
            price_card=9000,
            price_history=[{"price": 11000}],
        ),
        now=datetime(2026, 4, 5, tzinfo=timezone.utc),
        include_history=True,
    )

    assert records["price_observations"] == []
    assert "observed_at" not in records["promotion_conditions"][0]


def test_manual_match_upsert_does_not_set_the_same_path_twice(monkeypatch):
    from types import SimpleNamespace

    import pymongo

    from retail.product_identity import sync_product_identity_batch

    writes = {}

    class FakeUpdateOne:
        def __init__(self, query, update, upsert):
            self.query = query
            self.update = update
            self.upsert = upsert

    class FakeCollection:
        def __init__(self, name):
            self.name = name

        def bulk_write(self, operations, ordered):
            writes[self.name] = operations
            return SimpleNamespace(upserted_count=0, modified_count=0, matched_count=len(operations))

    class FakeDatabase:
        def __getitem__(self, name):
            return FakeCollection(name)

    monkeypatch.setattr(pymongo, "UpdateOne", FakeUpdateOne)
    sync_product_identity_batch(
        FakeDatabase(),
        [_product(entity_override="manual:phone:256gb", entity_match_method="manual")],
    )

    operation = writes["product_matches"][0]
    set_paths = set(operation.update.get("$set", {}))
    insert_paths = set(operation.update.get("$setOnInsert", {}))
    assert set_paths.isdisjoint(insert_paths)
    assert operation.update["$set"]["review_status"] == "approved"


def test_missing_observation_time_is_not_fabricated():
    records = build_product_identity_records(
        _product(scraped_at=None, updated_at=None),
        now=datetime(2026, 4, 5, tzinfo=timezone.utc),
    )

    assert records["price_observations"] == []
