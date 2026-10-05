from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from retail.batch.rules import detect_offers, watch_alerts
from retail.pricing import chart_drawable, chart_history, cheaper_before, cheaper_elsewhere, mark_false_list_discounts, price_stats
from retail.thumbs import decode, shrink

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def points(*pairs):
    return [
        {"price": price, "scraped_at": (NOW - timedelta(days=days)).isoformat()}
        for days, price in pairs
    ]


def test_price_stats_marks_good_deal():
    history = points((60, 100000), (45, 100000), (30, 98000), (10, 100000))
    stats = price_stats(history, current=80000, now=NOW)
    assert stats["median"] == 100000
    assert stats["percent_vs_median"] == -20.0
    assert stats["level"] == "great"
    assert stats["previous"] == 100000
    assert stats["fake_discount"] is None


def test_price_stats_detects_inflated_discount():
    history = points((60, 100000), (40, 100000), (20, 100000), (3, 140000))
    stats = price_stats(history, current=101000, now=NOW)
    assert stats["fake_discount"]["baseline"] == 100000
    assert stats["fake_discount"]["inflated_from"] == 140000
    assert stats["level"] == "fake"


def test_chart_history_draws_a_flat_line_across_more_than_one_day():
    """Una sola medición de hace dos días igual cubre más de un día calendario."""
    tz = ZoneInfo("America/Santiago")
    now = datetime(2026, 9, 16, 18, tzinfo=tz)
    history = chart_history(
        [{"price": 216990, "scraped_at": datetime(2026, 9, 14, 15, tzinfo=tz).isoformat()}],
        now=now,
    )
    assert chart_drawable(history, now=now)
    assert [(item["day"], item["price"]) for item in history] == [
        ("2026-09-14", 216990),
        ("2026-09-15", 216990),
        ("2026-09-16", 216990),
    ]


def test_chart_history_stays_empty_on_a_single_calendar_day():
    tz = ZoneInfo("America/Santiago")
    now = datetime(2026, 9, 16, 18, tzinfo=tz)
    raw = [
        {"price": 249990, "scraped_at": datetime(2026, 9, 16, 10, tzinfo=tz).isoformat()},
        {"price": 216990, "scraped_at": datetime(2026, 9, 16, 18, tzinfo=tz).isoformat()},
    ]
    history = chart_history(raw, now=now)
    assert len(history) == 1
    assert history[0]["day"] == "2026-09-16"
    assert history[0]["price"] == 216990
    assert not chart_drawable(raw, now=now)
    assert chart_history([], now=now) == []


def test_chart_history_carries_the_price_through_unchanged_days():
    tz = ZoneInfo("America/Santiago")
    now = datetime(2026, 9, 16, 18, tzinfo=tz)
    history = chart_history(
        [
            {"price": 249990, "scraped_at": datetime(2026, 9, 14, 12, tzinfo=tz).isoformat()},
            {"price": 216990, "scraped_at": datetime(2026, 9, 16, 12, tzinfo=tz).isoformat()},
        ],
        now=now,
    )
    assert [(item["day"], item["price"]) for item in history] == [
        ("2026-09-14", 249990),
        ("2026-09-15", 249990),
        ("2026-09-16", 216990),
    ]


def test_chart_history_uses_santiago_not_utc_dates():
    tz = ZoneInfo("America/Santiago")
    now = datetime(2026, 9, 16, 18, tzinfo=tz)
    # 02:00 UTC del 16 todavía es el 15 en Santiago.
    history = chart_history(
        [{"price": 216990, "scraped_at": "2026-09-16T02:00:00+00:00"}],
        now=now,
    )
    assert [item["day"] for item in history] == ["2026-09-15", "2026-09-16"]
    assert chart_drawable(
        [{"price": 216990, "scraped_at": "2026-09-16T02:00:00+00:00"}],
        now=now,
    )


def test_price_stats_without_history():
    stats = price_stats([], current=50000, now=NOW)
    assert stats["median"] is None
    assert stats["level"] == "unknown"


def _offer(price, previous, stats):
    return {
        "name": "Galaxy S25 512GB",
        "store": "lider",
        "store_title": "Lider",
        "price": price,
        "previous_price": previous,
        "price_delta": price - previous,
        "compare_code": "id:samsung|s25|512gb",
        "price_stats": stats,
    }


def test_fake_discount_is_not_reported_as_offer():
    history = points((60, 100000), (40, 100000), (20, 100000), (3, 140000))
    stats = price_stats(history, current=101000, now=NOW)
    rules = {
        "enabled": ["price_drop_percent", "price_drop_amount"],
        "price_drop_percent": 10,
        "price_drop_amount": 20000,
        "ignore_fake_discounts": True,
    }
    result = {"groups": [{"comparable": False, "offers": [_offer(101000, 140000, stats)]}]}
    assert detect_offers(result, {"id": "s25", "query": "galaxy s25"}, rules) == []
    rules["ignore_fake_discounts"] = False
    assert detect_offers(result, {"id": "s25", "query": "galaxy s25"}, rules)


def test_below_median_rule_and_saving():
    history = points((60, 100000), (40, 100000), (20, 100000))
    stats = price_stats(history, current=80000, now=NOW)
    rules = {"enabled": ["below_median"], "below_median_percent": 12}
    result = {"groups": [{"comparable": False, "offers": [_offer(80000, 100000, stats)]}]}
    alerts = detect_offers(result, {"id": "s25", "query": "galaxy s25", "category": "smartphones"}, rules)
    assert [alert.rule for alert in alerts] == ["below_median"]
    assert alerts[0].saving == 0
    assert alerts[0].discount == 0
    assert alerts[0].reference_price is None
    assert alerts[0].analysis_reference_price == 100000
    assert alerts[0].category == "smartphones"


def test_watch_alert_on_target_price():
    stats = price_stats(points((30, 900000), (10, 900000)), current=690000, now=NOW)
    result = {
        "groups": [
            {
                "compare_code": "id:samsung|s25|512gb",
                "offers": [_offer(690000, 900000, stats) | {"price": 690000}],
            }
        ]
    }
    watch = {"id": "abc", "query": "galaxy s25", "compare_code": "id:samsung|s25|512gb", "target_price": 700000}
    alerts = watch_alerts(result, watch)
    assert len(alerts) == 1
    assert alerts[0].rule == "watch_target"
    assert "690.000" in alerts[0].message
    watch["target_price"] = 600000
    assert watch_alerts(result, watch) == []


def test_watch_alert_on_any_price_change_up_or_down():
    result = {
        "groups": [{
            "compare_code": "id:samsung|s25|512gb",
            "offers": [_offer(710000, 700000, {})],
        }]
    }
    watch = {
        "id": "abc",
        "query": "galaxy s25",
        "compare_code": "id:samsung|s25|512gb",
        "watch_changes": True,
        "last_seen_price": 700000,
    }
    alerts = watch_alerts(result, watch)
    assert len(alerts) == 1
    assert alerts[0].rule == "watch_change"
    assert alerts[0].previous_price == 700000
    assert "subió" in alerts[0].message
    watch["last_seen_price"] = 710000
    assert watch_alerts(result, watch) == []


def test_cheaper_before_reports_historical_low():
    hint = cheaper_before(points((30, 70000), (10, 100000)), 100000)
    assert hint is not None
    assert hint["price"] == 70000
    assert hint["on"] == "2026-08-14"
    assert hint["gap_percent"] == 30.0
    assert cheaper_before(points((30, 100000), (10, 80000)), 80000) is None
    assert cheaper_before(points((30, 99000)), 100000) is None


def test_cheaper_elsewhere_picks_the_other_store():
    cheap = {"store": "falabella", "store_title": "Falabella", "price": 80000}
    dear = {"store": "ripley", "store_title": "Ripley", "price": 100000}
    hint = cheaper_elsewhere(dear, [cheap, dear])
    assert hint is not None
    assert hint["store"] == "falabella"
    assert hint["price"] == 80000
    assert hint["gap_percent"] == 20.0
    assert cheaper_elsewhere(cheap, [cheap, dear]) is None
    assert cheaper_elsewhere(dear, [dear, {"store": "paris", "price": 99000}]) is None


def test_cheaper_elsewhere_uses_global_minimum_regardless_of_order():
    current = {"store": "entel", "product_id": "e2", "price": 279990}
    peers = [
        {"store": "pcfactory", "product_id": "pc", "price": 249990},
        current,
        {"store": "ebest", "product_id": "eb", "price": 199990},
    ]
    hint = cheaper_elsewhere(current, peers)
    assert hint is not None
    assert hint["store"] == "ebest"
    assert hint["price"] == 199990
    assert hint["gap_percent"] == 28.6
    assert cheaper_elsewhere(peers[-1], peers) is None


def test_cheaper_elsewhere_ignores_invalid_stale_and_unavailable_offers():
    current = {"store": "entel", "price": 279990}
    peers = [
        current,
        {"store": "stale", "price": 100000, "stale": True},
        {"store": "sold", "price": 120000, "availability": "Sin stock"},
        {"store": "zero", "price": 0},
        {"store": "valid", "price": "249990", "availability": "En stock"},
    ]
    hint = cheaper_elsewhere(current, peers)
    assert hint is not None
    assert hint["store"] == "valid"
    assert hint["price"] == 249990


def test_stats_track_age_and_lowest_ever():
    history = points((30, 100000), (20, 90000), (5, 90000))
    stats = price_stats(history, current=90000, now=NOW)
    assert stats["changed_days_ago"] == 20
    assert stats["is_lowest_ever"] is True
    assert "7" in stats["windows"] and "30" in stats["windows"] and "90" in stats["windows"]


def test_new_pages_and_apis_are_wired():
    from fastapi.testclient import TestClient

    from retail.web.app import app

    from pathlib import Path

    client = TestClient(app)
    for path, marker in [
        ("/hoy", "Ofertas de hoy"),
        ("/catalogo", "Catálogo"),
        ("/producto", "Ficha de producto"),
        ("/siguiendo", "Productos que sigo"),
    ]:
        page = client.get(path)
        assert page.status_code == 200, path
        assert marker in page.text, path
    for path in ("/reales", "/comparar?store=cugat&id=18221"):
        denied = client.get(path, follow_redirects=False)
        assert denied.status_code == 303, path
        assert denied.headers["location"].startswith("/entrar?next=")
    old_super = client.get("/super", follow_redirects=False)
    assert old_super.status_code == 302
    assert old_super.headers["location"] == "/reales?super=1"
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/deals",
        "/api/catalog",
        "/api/product",
        "/api/thumb",
        "/api/watches",
        "/api/categories",
        "/api/reales",
        "/api/super",
    } <= paths
    watch = client.post("/api/watches", json={"query": "tv lg", "name": "TV", "target_price": 100000})
    assert watch.status_code != 500
    assert watch.status_code in {200, 401, 503}
    reales = Path("retail/web/static/reales.html").read_text()
    assert "Ofertas en comparación" in reales
    assert "Bajó de precio" in reales
    assert "% vs otra tienda" in reales
    assert 'id="min-gap"' in reales
    assert "Super ofertas: descuento superior al 50%" in reales
    assert "reales.js?v=18" in reales
    hoy_js = Path("retail/web/static/hoy.js").read_text()
    assert "esta referencia histórica no es el precio normal publicado" in hoy_js


def test_deal_sort_orders_price_name_and_gap():
    from retail.mongo import ProductRepository

    rows = [
        {"name": "Beta", "price": 200, "saving": 10, "discount": 5, "gap_percent": 40},
        {"name": "Alfa", "price": 100, "saving": 50, "discount": 20, "gap_percent": 10},
    ]
    by_name = ProductRepository._sort_deals(list(rows), "name")
    assert [item["name"] for item in by_name] == ["Alfa", "Beta"]
    by_price = ProductRepository._sort_deals(list(rows), "price")
    assert [item["price"] for item in by_price] == [100, 200]
    by_gap = ProductRepository._sort_deals(list(rows), "gap")
    assert [item["gap_percent"] for item in by_gap] == [40, 10]
    drop = {
        "saving": 20000,
        "previous_price": 100000,
        "price": 80000,
        "extra": {},
    }
    assert ProductRepository._deal_discount(drop) == 20.0
    gap = {"saving": 50000, "price": 50000, "extra": {"gap_percent": 95.2}}
    assert ProductRepository._deal_discount(gap) == 95.2


def test_deal_discount_uses_semantic_reference_and_safe_invalid_values():
    from retail.mongo import ProductRepository

    below_median = {
        "rule": "below_median",
        "price": 95192,
        "price_normal": 118990,
        "reference_price": 118990,
        "analysis_reference_price": 190990,
        "previous_price": 118990,
        "saving": 23798,
        "extra": {"median": 190990, "percent_vs_median": -50.2},
    }
    assert ProductRepository._deal_discount(below_median) == 20.0
    assert ProductRepository._deal_saving(below_median) == 23798
    without_normal = {
        "rule": "below_median",
        "price": 95192,
        "saving": 95798,
        "extra": {"median": 190990, "percent_vs_median": -50.2},
    }
    assert ProductRepository._deal_discount(without_normal) == 0.0
    assert ProductRepository._deal_saving(without_normal) == 0
    assert ProductRepository._deal_discount({
        "rule": "price_drop_percent",
        "price": 80000,
        "previous_price": 100000,
        "reference_price": 100000,
        "saving": 20000,
        "extra": {},
    }) == 20.0
    assert ProductRepository._deal_discount({
        "rule": "common_discount",
        "price": 70000,
        "price_normal": 100000,
        "reference_price": 100000,
        "extra": {},
    }) == 30.0
    assert ProductRepository._deal_discount({
        "rule": "cross_store_gap",
        "price": 60000,
        "reference_price": 100000,
        "extra": {"comparison_price": 60000},
    }) == 40.0
    for reference in (None, 0):
        assert ProductRepository._deal_discount({
            "price": 80000, "saving": 20000, "reference_price": reference, "extra": {},
        }) == 0.0
    assert ProductRepository._deal_discount({
        "price": 100000, "reference_price": 90000, "saving": 99999, "extra": {},
    }) == 0.0


def test_thumbnail_shrinks_and_roundtrips():
    from PIL import Image
    import io

    buffer = io.BytesIO()
    Image.new("RGB", (900, 900), (200, 40, 40)).save(buffer, format="PNG")
    shrunk = shrink(buffer.getvalue(), "image/png", max_side=120)
    assert shrunk is not None
    payload, mime, width, height = shrunk
    assert mime == "image/jpeg"
    assert max(width, height) == 120
    assert len(payload) < len(buffer.getvalue())

    import base64

    stored = {"data": base64.b64encode(payload).decode("ascii"), "mime": mime}
    decoded = decode(stored)
    assert decoded is not None
    assert decoded[0] == payload
    assert decode(None) is None


def _mini_pc(store, **kwargs):
    row = {
        "name": "Mini PC Bmax B8 PRO AMD Ryzen 8745HS / 16GB",
        "store": store,
        "price": 665990,
    }
    row.update(kwargs)
    return row


def test_paris_list_discount_is_fake_when_lider_sells_same_as_normal():
    groups = [
        {
            "comparable": True,
            "offers": [
                _mini_pc("lider", store_title="Lider Chile"),
                _mini_pc(
                    "paris",
                    store_title="Paris Chile",
                    price_normal=866690,
                    discount_percent=23,
                ),
            ],
        }
    ]
    mark_false_list_discounts(groups)
    lider, paris = groups[0]["offers"]
    assert not lider.get("precio_normal")
    assert not lider.get("fake_discount")
    assert paris["price"] == 665990
    assert paris["precio_normal"] is True
    assert paris["fake_discount"] is True
    assert paris["false_discount_store"] == "lider"


def test_keeps_discount_when_every_store_shows_one():
    groups = [
        {
            "comparable": True,
            "offers": [
                _mini_pc("lider", price_normal=866690, discount_percent=23),
                _mini_pc("paris", price_normal=866690, discount_percent=23),
            ],
        }
    ]
    mark_false_list_discounts(groups)
    assert not groups[0]["offers"][0].get("precio_normal")
    assert not groups[0]["offers"][1].get("precio_normal")


def test_keeps_real_discount_when_peer_is_more_expensive():
    groups = [
        {
            "comparable": True,
            "offers": [
                _mini_pc("lider", price=800000),
                _mini_pc("paris", price_normal=866690, discount_percent=23),
            ],
        }
    ]
    mark_false_list_discounts(groups)
    assert not groups[0]["offers"][1].get("precio_normal")


def test_strips_when_peer_is_cheaper_without_discount():
    groups = [
        {
            "comparable": True,
            "offers": [
                _mini_pc("lider", price=650000),
                _mini_pc("paris", price_normal=866690, discount_percent=23),
            ],
        }
    ]
    mark_false_list_discounts(groups)
    assert groups[0]["offers"][1]["precio_normal"] is True


def test_product_card_exposes_offer_and_normal_histories_separately():
    from retail.web.insights_api import _card

    card = _card(
        {
            "store": "lider",
            "product_id": "sku-1",
            "name": "Producto",
            "price": 8000,
            "price_normal": 10000,
            "updated_at": "2026-09-22T12:00:00+00:00",
            "price_history": [
                {
                    "price": 9000,
                    "price_offer": 9000,
                    "price_normal": 11000,
                    "price_basis": "all_payment",
                    "scraped_at": "2026-09-20T12:00:00+00:00",
                },
                {
                    "price": 8000,
                    "price_offer": 8000,
                    "price_normal": 10000,
                    "price_basis": "all_payment",
                    "scraped_at": "2026-09-21T12:00:00+00:00",
                },
            ],
        }
    )

    assert [row["price"] for row in card["history_offer"]] == [9000, 8000]
    assert [row["price"] for row in card["history_normal"]] == [11000, 10000]
