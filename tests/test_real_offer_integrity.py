"""Casos de oferta real: inflación de lista, cross-store, baja genuina, Cyber."""

from datetime import datetime, timedelta, timezone

from retail.reales import (
    cross_store_anchor,
    detect_list_inflation,
    detect_pre_event_inflation,
    offer_integrity,
    pick_real_offer,
)


def _hist(*rows):
    """rows: (days_ago, price, price_normal?)."""
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


def test_list_inflation_marks_showcase_discount():
    """Lista 10k→14k y vuelve a ~10k: −29% comercial, ahorro real ~0."""
    history = _hist(
        (25, 10000, 10000),
        (18, 10000, 10000),
        (10, 10000, 10000),
        (5, 14000, 14000),
        (1, 10000, 14000),
        (0, 10000, 14000),
    )
    item = _offer(store="falabella", product_id="a", price=10000, price_normal=14000, price_history=history)
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    signal = detect_list_inflation(item, now=now)
    assert signal is not None
    assert signal["baseline_normal"] == 10000
    assert signal["inflated_normal"] >= 14000
    assert signal["commercial_discount"] >= 25
    assert signal["real_savings_percent"] <= 5

    deal = pick_real_offer(
        [
            item,
            _offer(store="ripley", product_id="b", price=14000, price_normal=14000),
        ],
        comparacion=True,
        historial=True,
    )
    assert deal is None


def test_cross_store_similar_is_not_great_real_offer():
    """«Oferta» a 10.000 cuando otras tiendas están en 9.800–10.200."""
    deal = pick_real_offer(
        [
            _offer(store="falabella", product_id="a", price=10000, price_normal=15000),
            _offer(store="ripley", product_id="b", price=9800, price_normal=9800),
            _offer(store="paris", product_id="c", price=10200, price_normal=10200),
        ],
        comparacion=True,
        historial=False,
    )
    assert deal is None

    anchor = cross_store_anchor(
        _offer(store="falabella", product_id="a", price=10000, price_normal=15000),
        [
            _offer(store="ripley", product_id="b", price=9800),
            _offer(store="paris", product_id="c", price=10200),
        ],
        entity_confidence=0.9,
    )
    assert anchor is not None
    assert anchor["similar_to_market"] is True


def test_genuine_drop_still_qualifies():
    history = _hist(
        (40, 10000, 10000),
        (20, 10000, 10000),
        (5, 10000, 10000),
        (0, 6000, 10000),
    )
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
    assert deal["store"] == "falabella"
    assert deal["commercial_discount"] == 40.0
    assert deal["real_savings_percent"] >= 10
    assert not deal.get("list_inflation")
    assert "comparacion" in deal["kinds"]


def test_cyber_like_pre_event_inflation():
    """Subida de lista en la ventana previa a Cyber Octubre y «descuento» de vuelta."""
    now = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)
    history = _hist(
        (20, 200000, 200000),
        (16, 200000, 200000),
        (10, 260000, 260000),
        (5, 260000, 260000),
        (0, 205000, 260000),
    )
    item = _offer(
        store="falabella",
        product_id="tv",
        name="Smart TV 55 XYZ",
        brand="XYZ",
        price=205000,
        price_normal=260000,
        price_history=history,
    )
    signal = detect_pre_event_inflation(item, now=now)
    assert signal is not None
    assert signal["rise_percent"] >= 10
    assert "Cyber" in (signal.get("event") or signal["label"])

    integrity = offer_integrity(
        item,
        [_offer(store="ripley", product_id="tv2", price=210000, price_normal=210000)],
        entity_confidence=0.9,
        now=now,
    )
    assert "pre_event_inflation" in integrity["suspicion_flags"] or integrity.get("list_inflation")

    deal = pick_real_offer(
        [
            item,
            _offer(store="ripley", product_id="tv2", price=260000, price_normal=260000),
        ],
        comparacion=True,
        historial=True,
    )
    # No debe vender el −21% comercial como oferta real sin baja genuina.
    assert deal is None
