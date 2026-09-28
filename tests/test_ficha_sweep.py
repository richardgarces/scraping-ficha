from retail.ficha_sweep import (
    claim_notice,
    follows_product,
    lower_price_message,
    offer_decision,
    scope_other_stores,
)
from retail.models import Product


def _product(**kwargs) -> Product:
    data = {
        "product_id": "1",
        "sku_id": "1",
        "name": "Ozempic 1 unidad",
        "brand": "Novo",
        "store": "lider",
        "price": 80000,
    }
    data.update(kwargs)
    return Product(**data)


def test_lower_price_triggers_notice():
    hit = offer_decision(
        _product(store="lider", product_id="a", price=80000),
        _product(store="paris", product_id="b", price=70000),
        best_price=80000,
    )
    assert hit is not None
    assert hit["notice"] is True
    assert hit["add"] is True
    assert hit["price"] == 70000
    assert lower_price_message("Paris", 216990) == "Encontramos un precio menor en Paris: $216.990"


def test_higher_or_equal_price_does_not_notice():
    higher = offer_decision(
        _product(store="lider", product_id="a", price=80000),
        _product(store="paris", product_id="b", price=90000),
        best_price=80000,
    )
    assert higher is not None
    assert higher["notice"] is False
    assert higher["add"] is True
    equal = offer_decision(
        _product(store="lider", product_id="a", price=80000),
        _product(store="ripley", product_id="c", price=80000),
        best_price=80000,
    )
    assert equal is not None
    assert equal["notice"] is False


def test_different_pack_qty_is_not_a_match():
    """6 unidades no es el mismo producto aunque salga más barato."""
    hit = offer_decision(
        _product(store="lider", product_id="a", name="Ozempic 1 unidad", price=80000),
        _product(store="paris", product_id="b", name="Ozempic 6 unidades", price=40000),
        best_price=80000,
    )
    assert hit is None


def test_already_shown_store_price_is_not_a_new_notice():
    hit = offer_decision(
        _product(store="lider", product_id="a", price=80000),
        _product(store="paris", product_id="b", price=70000),
        best_price=80000,
        shown={("paris", 70000)},
    )
    assert hit is not None
    assert hit["notice"] is False


def test_scope_skips_current_store_and_uses_routed_subset(monkeypatch):
    monkeypatch.setattr(
        "retail.ficha_sweep.stores_for",
        lambda query, available: ["ahumada", "cruzverde", "salcobrand", "lider"],
    )
    chosen = scope_other_stores(
        "ozempic",
        "ahumada",
        ["ahumada", "cruzverde", "salcobrand", "lider", "falabella"],
    )
    assert "ahumada" not in chosen
    assert "falabella" not in chosen
    assert chosen[-1] == "salcobrand"
    assert set(chosen) == {"cruzverde", "lider", "salcobrand"}


def test_telegram_only_when_following_and_claim_is_once():
    document = {
        "store": "lider",
        "product_id": "a",
        "name": "Ozempic 1 unidad",
        "compare_code": "id:ozempic",
    }
    assert follows_product(None, document) is False
    assert follows_product([{"query": "tv", "active": True}], document) is False
    assert follows_product(
        [{"store": "lider", "product_id": "a", "active": True, "user_id": "u1"}],
        document,
    )
    assert claim_notice("u1", "lider", "a", "paris", 70000) is True
    assert claim_notice("u1", "lider", "a", "paris", 70000) is False


def test_lower_price_telegram_uses_internal_product_page(monkeypatch):
    import retail.batch.alerts as alerts
    import retail.ficha_sweep as sweep

    sent = []

    class Repo:
        def list_watches(self, **kwargs):
            return [{"store": "lider", "product_id": "base-telegram", "active": True}]

        def find_user_by_id(self, user_id):
            return {"id": user_id, "telegram_chat_id": "99"}

    class ImmediateThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    monkeypatch.setattr(sweep.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(
        alerts,
        "send_to_user",
        lambda user, text, **kwargs: sent.append(text) or True,
    )
    document = {
        "store": "lider",
        "product_id": "base-telegram",
        "name": "Ozempic 1 unidad",
    }
    offer = _product(
        store="paris",
        product_id="offer telegram",
        price=69000,
        url="https://www.paris.cl/producto-directo",
    )

    sweep._maybe_telegram(
        Repo(),
        {"id": "user-ficha-link"},
        document,
        offer,
        "Encontramos un precio menor",
    )

    assert len(sent) == 1
    assert "https://precios.meincart.cl/producto?store=paris&id=offer%20telegram" in sent[0]
    assert "paris.cl/producto-directo" not in sent[0]
