"""fake_discount unificado con reales + muestreo de identidad admin."""

from datetime import datetime, timedelta, timezone

from retail.identity_audit import sample_identity_pairs
from retail.reales import detect_selling_fake_discount, offer_integrity, pick_real_offer


def _hist(*rows):
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    out = []
    for row in rows:
        days, price = row[0], row[1]
        normal = row[2] if len(row) > 2 else None
        point = {
            "price": price,
            "scraped_at": (now - timedelta(days=days)).isoformat(),
        }
        if normal is not None:
            point["price_normal"] = normal
        out.append(point)
    return out


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


def test_selling_fake_discount_blocks_real_offer():
    """Alza de venta y «descuento» de vuelta: fake_discount + no oferta real."""
    history = _hist(
        (60, 100000),
        (40, 100000),
        (20, 100000),
        (3, 140000),
        (0, 101000),
    )
    item = _offer(
        store="falabella",
        product_id="a",
        price=101000,
        price_all_payment=101000,
        price_normal=140000,
        price_history=history,
    )
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    signal = detect_selling_fake_discount(item, now=now)
    assert signal is not None
    assert signal["kind"] == "fake_discount"

    integrity = offer_integrity(
        item,
        [_offer(store="ripley", product_id="b", price=140000, price_all_payment=140000, price_normal=140000)],
        entity_confidence=0.9,
        now=now,
    )
    assert "fake_discount" in integrity["suspicion_flags"]
    assert integrity["fake_discount"] is not None

    deal = pick_real_offer(
        [
            item,
            _offer(store="ripley", product_id="b", price=140000, price_all_payment=140000, price_normal=140000),
        ],
        comparacion=True,
        historial=True,
    )
    assert deal is None


def test_sample_identity_pairs_keeps_high_confidence_cross_store():
    docs = [
        _offer(store="falabella", product_id="1", name="Shampoo XYZ 400ml", brand="XYZ", price=6000),
        _offer(store="ripley", product_id="2", name="Shampoo XYZ 400ml", brand="XYZ", price=10000),
        _offer(store="paris", product_id="3", name="Acondicionador Distinto 1L", brand="Otro", price=5000),
    ]
    pairs = sample_identity_pairs(docs, min_confidence=0.80, limit=10, seed=1)
    assert pairs
    assert all(pair["confidence"] >= 0.80 for pair in pairs)
    assert all(pair["left"]["store"] != pair["right"]["store"] for pair in pairs)
    keys = {pair["pair_id"] for pair in pairs}
    assert any("falabella:1|ripley:2" in key or "ripley:2|falabella:1" in key for key in keys)
