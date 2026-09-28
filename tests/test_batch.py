from fastapi.testclient import TestClient

from retail.batch.catalog import load_catalog
from retail.batch.rules import detect_offers, load_rules
from retail.batch.schedule import cron_line
from retail.web.app import app


def test_search_runs_eight_stores_at_a_time():
    from retail.search import SEARCH_TIMEOUT, STORE_WORKERS

    assert STORE_WORKERS == 8
    assert SEARCH_TIMEOUT == 12.0


def test_celulares_super_catalog():
    from pathlib import Path

    catalog = load_catalog(Path("retail/batch/catalogo_celulares_super.json"))
    ids = [item["id"] for item in catalog["products"]]
    assert len(ids) == len(set(ids))
    cats = {item["category"] for item in catalog["products"]}
    assert "smartphones" in cats
    assert "supermercado" in cats
    assert {"falabella", "lider", "tottus"} <= set(catalog["default_stores"])
    assert any("celular" in item["query"] for item in catalog["products"])
    assert any(item["query"] == "leche" for item in catalog["products"])


def test_catalog_has_unique_electronics():
    catalog = load_catalog()
    ids = [item["id"] for item in catalog["products"]]
    assert len(ids) == 1000
    assert len(ids) == len(set(ids))
    assert any("s25" in item["query"] for item in catalog["products"])
    assert any("iphone" in item["query"] for item in catalog["products"])
    categories = {item["category"] for item in catalog["products"]}
    assert len(categories) >= 10


def test_price_drop_and_cross_store_rules():
    rules = load_rules()
    result = {
        "groups": [
            {
                "comparable": True,
                "offers": [
                    {
                        "name": "Galaxy S25 512GB",
                        "store": "lider",
                        "store_title": "Lider",
                        "price": 500000,
                        "previous_price": 1000000,
                        "price_delta": -500000,
                        "url": "https://example.cl/s25",
                        "compare_code": "id:samsung|s25|512gb",
                    },
                    {
                        "name": "Galaxy S25 512GB",
                        "store": "falabella",
                        "store_title": "Falabella",
                        "price": 950000,
                        "previous_price": 950000,
                        "price_delta": 0,
                        "compare_code": "id:samsung|s25|512gb",
                    },
                ],
            }
        ]
    }
    alerts = detect_offers(result, {"id": "galaxy-s25-512", "query": "celular galaxy s25 512gb"}, rules)
    rules_hit = {item.rule for item in alerts}
    assert any("price_drop" in rule for rule in rules_hit)
    assert "cross_store_gap" in rules_hit
    assert alerts[0].price == 500000


def test_rules_ignore_small_moves():
    rules = load_rules()
    result = {
        "groups": [
            {
                "comparable": False,
                "offers": [
                    {
                        "name": "SSD",
                        "store": "pcfactory",
                        "price": 59000,
                        "previous_price": 60000,
                        "price_delta": -1000,
                        "compare_code": "id:ssd",
                    }
                ],
            }
        ]
    }
    assert detect_offers(result, {"id": "ssd-1tb", "query": "disco ssd 1tb nvme"}, rules) == []


def _history(pairs):
    """Puntos (días atrás, precio) tal como los guarda Mongo."""
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 13, tzinfo=timezone.utc)
    return [
        {"price": price, "scraped_at": (now - timedelta(days=ago)).isoformat()}
        for ago, price in pairs
    ], now


def test_buy_or_wait_says_what_is_missing_instead_of_guessing():
    from retail.pricing import buy_or_wait

    points, now = _history([(3, 100000), (2, 100000), (0, 89990)])
    answer = buy_or_wait(points, 89990, now=now)
    assert not answer["ready"]
    assert answer["advice"] == "sin_datos"
    assert answer["missing_days"] == 11
    assert "11" in answer["reason"]


def test_buy_or_wait_recommends_buying_at_the_historical_low():
    from retail.pricing import buy_or_wait

    points, now = _history([(60, 120000), (40, 110000), (20, 115000), (0, 99990)])
    answer = buy_or_wait(points, 99990, now=now)
    assert answer["ready"]
    assert answer["advice"] == "comprar"
    assert answer["position_percent"] == 0
    assert "más bajo" in answer["reason"]


def test_buy_or_wait_recommends_waiting_when_a_drop_is_due():
    from retail.pricing import buy_or_wait

    # Baja cada 20 días, de la última hace 3, y llegó a estar en $70.000.
    points, now = _history(
        [(63, 100000), (43, 70000), (33, 100000), (23, 88000), (13, 100000), (3, 87000), (0, 87000)]
    )
    answer = buy_or_wait(points, 87000, now=now)
    assert answer["advice"] == "esperar"
    assert answer["typical_days_between_drops"] == 20
    assert answer["days_since_last_drop"] == 3
    assert answer["typical_drop_percent"] is not None
    assert "20 días" in answer["reason"]


def test_drops_only_counts_falls():
    from retail.pricing import drop_events, drops, series

    points, _ = _history([(4, 100), (3, 90), (2, 120), (1, 80), (0, 80)])
    rows = series(points)
    assert [percent for _, percent in drops(rows)] == [10.0, 33.3]
    events = drop_events(rows)
    assert len(events) == len(drops(rows))
    assert [(item["previous_price"], item["price"]) for item in events] == [(100, 90), (120, 80)]
    assert drop_events(series([])) == []


def test_drop_list_length_matches_the_counted_number_not_watched_products():
    from retail.web.insights_api import counted_drop_rows

    one, _ = _history([(4, 10000), (1, 8000)])
    twice, _ = _history([(4, 100), (3, 90), (2, 120), (1, 80), (0, 80)])
    flat, _ = _history([(4, 5000), (1, 5000)])
    rose, _ = _history([(3, 1000), (0, 1400)])
    docs = [
        {"store": "fashionspark", "product_id": "a", "name": "Vestido", "url": "https://tienda.test/a", "price": 8000, "price_history": one},
        {"store": "fashionspark", "product_id": "b", "name": "Polera", "url": "", "price": 80, "price_history": twice},
        {"store": "fashionspark", "product_id": "c", "name": "Vigilado", "price": 5000, "price_history": flat},
        {"store": "fashionspark", "product_id": "d", "name": "Subió", "price": 1400, "price_history": rose},
        {"store": "mk", "product_id": "e", "name": "Otra tienda", "price": 8000, "price_history": one},
    ]
    listed = [row for doc in docs if doc["store"] == "fashionspark" for row in counted_drop_rows(doc)]
    counted = sum(len(counted_drop_rows(doc)) for doc in docs if doc["store"] == "fashionspark")
    # 1 + 2 bajas. Los dos vigilados sin baja no entran, ni la otra tienda.
    assert counted == 3
    assert len(listed) == counted
    assert {row["name"] for row in listed} == {"Vestido", "Polera"}
    vestido = next(row for row in listed if row["product_id"] == "a")
    assert vestido["previous_price"] == 10000
    assert vestido["price"] == 8000
    assert vestido["dropped_at"]
    assert vestido["url"] == "https://tienda.test/a"
    assert all(row["store"] == "fashionspark" for row in listed)


def test_inflated_drops_are_counted_from_the_same_drop_rows():
    from retail.pricing import classified_drop_events, series

    points, _ = _history([(20, 100), (15, 100), (10, 100), (5, 200), (0, 100)])
    rows = classified_drop_events(series(points))

    fake_drops = sum(1 for row in rows if row["inflated"])
    percent = fake_drops * 100 / len(rows)
    assert len(rows) == 1
    assert fake_drops == 1
    assert percent == 100


def test_history_records_one_point_per_day_and_every_change():
    from retail.mongo import should_record

    # Nada guardado todavía: el primer precio siempre entra.
    assert should_record(None, 10000, "2026-09-13")
    # La misma corrida vuelve a encontrar el producto en otra categoría.
    assert not should_record((10000, "2026-09-13"), 10000, "2026-09-13")
    # Bajó dentro del mismo día: eso sí es historia.
    assert should_record((10000, "2026-09-13"), 8990, "2026-09-13")
    # Día nuevo sin cambio: se deja la marca para poder medir cuánto duró.
    assert should_record((10000, "2026-09-13"), 10000, "2026-09-14")
    # Un producto sin precio no inventa movimiento.
    assert not should_record((None, "2026-09-13"), None, "2026-09-13")
    # También se registra si cambia el precio normal aunque la oferta siga igual.
    assert should_record((10000, "2026-09-13", 12000), 10000, "2026-09-13", 13000)
    assert not should_record((10000, "2026-09-13", 12000), 10000, "2026-09-13", 12000)


def test_digest_groups_by_category_and_leads_with_saving():
    from retail.batch.alerts import digest_text
    from retail.batch.rules import Alert

    alertas = [
        Alert(
            catalog_id=f"c{index}",
            query=f"q{index}",
            rule="price_drop_percent",
            name=nombre,
            store=tienda,
            price=precio,
            previous_price=precio + ahorro,
            message="bajó",
            url="http://x",
            compare_code=None,
            extra={"product_id": f"p{index}"},
            saving=ahorro,
            category=categoria,
        )
        for index, (nombre, tienda, precio, ahorro, categoria) in enumerate(
            [
                ("Sofá chico", "paris", 90000, 10000, "Decohogar"),
                ("Notebook gamer", "falabella", 500000, 300000, "Tecnología"),
                ("Olla", "lider", 9000, 1000, "Decohogar"),
            ]
        )
    ]
    texto = digest_text(alertas, title="Ofertas del 2026-09-14", top=2)
    assert "3 ofertas" in texto
    # El de mayor ahorro manda, y su categoría aparece primero.
    assert texto.index("TECNOLOGÍA") < texto.index("DECOHOGAR")
    assert "−$300.000" in texto
    assert "Olla" not in texto  # quedó fuera del top 2
    assert "y 1 más" in texto
    assert "https://precios.meincart.cl/producto?store=falabella&id=p1" in texto
    assert "http://x" not in texto
    assert len(texto) <= 3800


def test_digest_is_quiet_without_alerts_or_push_channels():
    from retail.batch.alerts import send_digest

    assert send_digest([], ["telegram"], title="x") == []
    assert send_digest([object()], ["log", "file"], title="x") == []


def test_individual_notification_includes_price_discount_image_and_link():
    from retail.batch.alerts import _notification_text, _payload
    from retail.batch.rules import Alert

    alert = Alert(
        catalog_id="c1", query="audífonos", rule="price_drop_percent",
        name="Audífonos Lite", store="paris", price=64990,
        previous_price=99990, message="Bajó 35%", url="https://tienda.cl/p/1",
        compare_code=None, extra={
            "percent": 35.0,
            "previous_price": 99990,
            "store_title": "Paris",
            "product_id": "1",
        },
        saving=35000, category="tecnología", image_url="https://tienda.cl/img.jpg",
    )
    payload = _payload(alert)
    message = _notification_text(payload)
    assert "Audífonos Lite" in message
    assert "Precio para todo medio de pago: $64.990" in message
    assert "Descuento: 35%" in message
    assert "https://precios.meincart.cl/producto?store=paris&id=1" in message
    assert payload["image_url"] == "https://tienda.cl/img.jpg"


def test_catalog_footwear_filter_requires_shoe_related_product_data():
    import re

    from retail.mongo import catalog_browse_filter

    query = catalog_browse_filter("calzado")
    pattern = re.compile(query["catalog_category"]["$regex"], re.I)
    assert pattern.fullmatch("calzado")
    alternatives = query["$and"][0]["$or"]
    assert {next(iter(item)) for item in alternatives} == {"name", "category"}


def test_catalog_category_filter_ignores_accents_and_case():
    import re

    from retail.mongo import catalog_browse_filter

    query = catalog_browse_filter("Ferretería")
    pattern = re.compile(query["catalog_category"]["$regex"], re.I)
    assert pattern.fullmatch("ferreteria")
    assert pattern.fullmatch("FERRETERÍA")


def test_telegram_skips_without_token_and_logs(monkeypatch, capsys):
    from retail.batch import alerts

    monkeypatch.setattr(alerts, "destination_chats", lambda: [])
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(alerts, "load_channels", lambda: {})
    assert alerts._telegram_text("hola") is False
    assert "no se envía" in capsys.readouterr().out


def test_telegram_open_sets_timeout_before_resolve(monkeypatch):
    """do_open lee Request.timeout; sin eso getChat falla al resolver @usuario."""
    from retail.batch import alerts

    seen = {}

    class FakeResponse:
        def read(self):
            return b'{"ok": true, "result": {"id": 7}}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_do_open(self, http_class, req, **http_conn_args):
        seen["timeout"] = req.timeout
        seen["extra"] = http_conn_args
        seen["cls"] = http_class
        return FakeResponse()

    monkeypatch.setattr(alerts.HTTPSHandler, "do_open", fake_do_open)
    alerts._resolved_chats.clear()
    payload = alerts._telegram_api("token", "getChat", {"chat_id": "@usuario"})
    assert payload.get("ok") is True
    assert seen["timeout"] == 20
    assert "timeout" not in seen["extra"]
    assert seen["cls"] is alerts._IPv4HTTPSConnection
    assert alerts._resolve_chat("token", "@usuario") == "7"
    assert "Request" not in str(payload)


def test_telegram_resolves_username_before_send(monkeypatch):
    from retail.batch import alerts

    calls = []

    def fake_api(token, method, params):
        calls.append((method, params.get("chat_id")))
        if method == "getChat":
            return {"ok": True, "result": {"id": 4242, "type": "private"}}
        return {"ok": True, "result": {}}

    monkeypatch.setattr(alerts, "_telegram_api", fake_api)
    monkeypatch.setattr(alerts, "destination_chats", lambda: ["@guardado"])
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    alerts._resolved_chats.clear()
    assert alerts._telegram_text("aviso") is True
    assert calls[0] == ("getChat", "@guardado")
    assert calls[1] == ("sendMessage", "4242")


def test_global_telegram_skips_a_chat_that_receives_personal_alerts(monkeypatch):
    from retail.batch import alerts

    sent = []
    monkeypatch.setattr(alerts, "_secret", lambda *args: "token")
    monkeypatch.setattr(alerts, "destination_chats", lambda: ["99"])
    monkeypatch.setattr(alerts, "_user_chats", ["99"])
    monkeypatch.setattr(
        alerts,
        "_send_telegram",
        lambda token, chat, text, image_url=None: sent.append(chat) or True,
    )

    assert alerts._telegram_text("aviso") is False
    assert sent == []


def test_telegram_sends_product_image_and_falls_back_to_text(monkeypatch):
    from retail.batch import alerts

    calls = []

    def fake_api(token, method, params):
        calls.append((method, params))
        if method == "sendPhoto":
            return {"ok": False, "description": "wrong file identifier"}
        return {"ok": True, "result": {}}

    monkeypatch.setattr(alerts, "_telegram_api", fake_api)
    assert alerts._send_telegram("token", "99", "Oferta", image_url="https://example.com/producto.jpg") is True
    assert calls[0][0] == "sendPhoto"
    assert calls[0][1]["photo"] == "https://example.com/producto.jpg"
    assert calls[1][0] == "sendMessage"


def test_long_telegram_photo_is_sent_as_one_message_and_keeps_product_link(monkeypatch):
    from retail.batch import alerts

    calls = []
    monkeypatch.setattr(
        alerts,
        "_telegram_api",
        lambda token, method, params: calls.append((method, params)) or {"ok": True, "result": {}},
    )
    text = "Ofertas\n" + ("detalle " * 200) + "\n🔗 Ficha: https://lnk.meincart.cl/o/123"
    assert alerts._send_telegram("token", "99", text, image_url="https://example.com/producto.jpg") is True
    assert [method for method, _params in calls] == ["sendPhoto"]
    assert len(calls[0][1]["caption"]) <= 1024
    assert "https://lnk.meincart.cl/o/123" in calls[0][1]["caption"]


def test_email_notification_includes_product_image(monkeypatch):
    from retail.batch import alerts

    sent = []

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr(alerts, "load_channels", lambda: {"smtp_host": "smtp.example", "smtp_from": "bot@example.com"})
    monkeypatch.setattr(alerts.smtplib, "SMTP", FakeSMTP)
    assert alerts.send_email(
        "ana@example.com",
        "Oferta",
        "Bajó de precio",
        image_url="https://example.com/producto.jpg",
    ) is True
    html = sent[0].get_body(preferencelist=("html",)).get_content()
    assert '<img src="https://example.com/producto.jpg"' in html


def test_user_telegram_fields_are_used_when_present():
    from retail.batch.alerts import user_telegram_chats

    class Users:
        def find(self, query, projection):
            return [
                {"telegram_chat_id": "99"},
                {"telegram": {"username": "@cuenta"}},
                {"email": "sin-telegram@example.com"},
            ]

    class Repo:
        users = Users()

    assert user_telegram_chats(Repo()) == ["99", "@cuenta"]


def test_real_offers_digest_skips_already_sent(tmp_path, monkeypatch):
    from retail.batch import alerts

    sent = []
    monkeypatch.setattr(alerts, "_telegram_text", lambda text, **kwargs: sent.append(text) or True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(alerts, "destination_chats", lambda: ["99"])

    class Repo:
        def real_offers(self, **kwargs):
            return {
                "items": [
                    {"name": "Shampoo", "store": "lider", "product_id": "shampoo-1", "price": 6000, "gap": 4000, "gap_percent": 40, "compare_code": "abc", "rival_store": "paris", "url": "http://x"},
                ]
            }

    state = tmp_path / "reales.json"
    assert alerts.notify_real_offers(Repo(), title="Ofertas reales", state_path=state) == 1
    assert "Shampoo" in sent[0]
    assert "https://precios.meincart.cl/producto?store=lider&id=shampoo-1" in sent[0]
    assert "http://x" not in sent[0]
    assert alerts.notify_real_offers(Repo(), title="Ofertas reales", state_path=state) == 0


def test_real_offers_telegram_requires_forty_percent(tmp_path, monkeypatch):
    from retail.batch import alerts

    sent = []
    monkeypatch.setattr(alerts, "_telegram_text", lambda text, **kwargs: sent.append(text) or True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(alerts, "destination_chats", lambda: ["99"])

    class Repo:
        def real_offers(self, **kwargs):
            return {"items": [
                {"name": "Casi", "store": "a", "product_id": "1", "price": 6100, "gap_percent": 39.9, "compare_code": "casi"},
                {"name": "Sí", "store": "b", "product_id": "2", "price": 6000, "gap_percent": 40, "compare_code": "si"},
            ]}

    assert alerts.notify_real_offers(Repo(), title="Ofertas", state_path=tmp_path / "state.json") == 1
    assert len(sent) == 1
    assert "Sí" in sent[0]
    assert "Casi" not in sent[0]


def test_cron_scripts_rebuild_product_index():
    from pathlib import Path

    local = Path("scripts/ofertas-diarias.sh").read_text()
    bmax = Path("scripts/ofertas-diarias-bmax.sh").read_text()
    assert "retail indice" in local
    assert "retail indice" in bmax
    assert "retail batch" in local
    assert "retail batch" in bmax
    assert "--grupo" in local
    assert "--grupo" in bmax


def test_bmax_retail_cron_always_runs_the_complete_catalog():
    from pathlib import Path

    bmax = Path("scripts/ofertas-diarias-bmax.sh").read_text()
    assert '[[ "$g" == "retail" ]]' in bmax
    assert "ADAPTIVE_SCRAPING=0" in bmax
    assert 'RETAIL_FULL_BATCH_BUDGET_MINUTES:-0' in bmax
    assert '--presupuesto-minutos "$budget"' in bmax


def test_bmax_cron_does_not_duplicate_lines_already_redirected_by_crontab():
    from pathlib import Path

    bmax = Path("scripts/ofertas-diarias-bmax.sh").read_text()
    assert 'tee -a "$LOG"' not in bmax


def test_remote_sync_preserves_live_bind_mount_directory_inodes():
    from pathlib import Path

    push = Path("scripts/remote/00-pack-and-push-app.sh").read_text()
    assert "rsync -a --delete" in push
    assert '"\\$STAGE_DIR/" "\\$REMOTE_DIR/"' in push
    assert "find \"\\$REMOTE_DIR\" -mindepth 1 -maxdepth 1" not in push


def test_cron_line_per_group():
    from retail.batch.schedule import cron_line, cron_lines, group_slots

    line = cron_line(8, 30, "tecnologia")
    assert line.startswith("30 8 * * *")
    assert "ofertas-diarias.sh tecnologia" in line
    slots = group_slots(
        {
            "hour": 6,
            "minute": 0,
            "groups": {"mode": "per_group", "stagger_minutes": 45, "enabled": ["retail", "tecnologia"]},
        }
    )
    assert slots[0] == ("retail", 6, 0)
    assert slots[1][0] == "tecnologia"
    assert slots[1][1:] == (6, 45)
    lines = cron_lines(
        {
            "hour": 6,
            "minute": 0,
            "groups": {"mode": "per_group", "stagger_minutes": 45, "enabled": ["retail"]},
        }
    )
    assert len(lines) == 1
    assert "retail" in lines[0]


def test_store_categories_registry_payload_and_normalize():
    from retail.registry import GROUP_ORDER, STORE_GROUP
    from retail.store_categories import normalize_group, registry_payloads, stores_for_group

    rows = registry_payloads()
    assert [row["id"] for row in rows] == list(GROUP_ORDER)
    tech = next(row for row in rows if row["id"] == "tecnologia")
    assert "pcfactory" in tech["store_ids"]
    assert normalize_group("Tecnologia") == "tecnologia"
    stores = stores_for_group("autos")
    assert "chileautos" in stores or STORE_GROUP.get("chileautos") == "autos"


def test_run_batch_refreshes_product_index(monkeypatch):
    from retail.batch import runner

    called: list[bool] = []

    monkeypatch.setattr(
        runner,
        "refresh_product_index",
        lambda: called.append(True) or {"backend": "redis", "source": "mongo", "count": 71},
    )
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    summary = runner.run_batch(persist=False, dry_run=False, limit=0)
    assert called == [True]
    assert summary["product_index"]["source"] == "mongo"


def test_dry_run_skips_product_index_refresh(monkeypatch):
    from retail.batch import runner

    called: list[bool] = []
    monkeypatch.setattr(runner, "refresh_product_index", lambda: called.append(True))
    runner.run_batch(dry_run=True, limit=1)
    assert called == []


def test_dry_run_grupo_filters_stores(monkeypatch):
    from retail.batch import runner

    monkeypatch.setattr(
        "retail.store_categories.refresh_store_categories"
        if False
        else "retail.batch.runner.refresh_store_categories",
        lambda: {"source": "registry", "count": 1, "upserted": 0},
    )
    monkeypatch.setattr(
        "retail.store_categories.stores_for_group",
        lambda grupo, **kwargs: ["pcfactory", "belkin"],
    )
    monkeypatch.setattr(
        "retail.store_categories.filter_products_for_group",
        lambda products, grupo, **kwargs: products[:2],
    )
    monkeypatch.setattr("retail.store_categories.normalize_group", lambda g, **kwargs: "tecnologia")
    summary = runner.run_batch(dry_run=True, grupo="tecnologia", limit=10)
    assert summary["grupo"] == "tecnologia"
    assert summary["stores"] == ["pcfactory", "belkin"]
    assert len(summary["searches"]) == 2


def test_catalog_origin_store_and_resume_cursor():
    from retail.batch.catalog import catalog_origin_store
    from retail.batch.runner import _rotate_products

    products = [
        {"id": "prod-lider-123", "query": "leche"},
        {"id": "prod-jumbo-456", "query": "arroz"},
        {"id": "generic-1", "query": "televisor"},
    ]
    assert catalog_origin_store(products[0]) == "lider"
    assert catalog_origin_store(products[2]) is None
    assert [item["id"] for item in _rotate_products(products, "prod-jumbo-456")] == [
        "prod-jumbo-456",
        "generic-1",
        "prod-lider-123",
    ]


def test_group_batch_interleaves_stores_and_parallelizes_only_distinct_stores(monkeypatch):
    import threading
    import time

    from retail.batch import runner

    products = [
        {"id": "prod-lider-1", "query": "leche uno", "category": "alimentos"},
        {"id": "prod-lider-2", "query": "leche dos", "category": "alimentos"},
        {"id": "prod-jumbo-1", "query": "arroz uno", "category": "alimentos"},
        {"id": "prod-jumbo-2", "query": "arroz dos", "category": "alimentos"},
    ]
    monkeypatch.setenv("BATCH_PRODUCT_WORKERS", "2")
    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {"source": "test"})
    monkeypatch.setattr("retail.store_categories.normalize_group", lambda value: "supermercados")
    monkeypatch.setattr(
        "retail.store_categories.stores_for_group", lambda value: ["lider", "jumbo"]
    )
    monkeypatch.setattr(
        "retail.store_categories.filter_products_for_group", lambda catalog, value: products
    )
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)

    lock = threading.Lock()
    active = 0
    maximum = 0
    calls: list[str] = []

    def fake_search(query, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            calls.append(kwargs["stores"][0])
        time.sleep(0.03)
        with lock:
            active -= 1
        return {
            "offer_count": 0,
            "comparable_count": 0,
            "groups": [],
            "saved": {},
            "warnings": [],
            "store_errors": [],
        }

    monkeypatch.setattr(runner, "search_products", fake_search)
    summary = runner.run_batch(
        grupo="supermercados", persist=False, pause=0, time_budget_minutes=1
    )
    assert summary["product_workers"] == 2
    assert maximum == 2
    assert set(calls[:2]) == {"lider", "jumbo"}
    assert len(summary["searches"]) == 4


def test_group_batch_does_not_parallelize_two_products_from_same_store(monkeypatch):
    import threading
    import time

    from retail.batch import runner

    products = [
        {"id": "prod-lider-1", "query": "leche uno", "category": "alimentos"},
        {"id": "prod-lider-2", "query": "leche dos", "category": "alimentos"},
    ]
    monkeypatch.setenv("BATCH_PRODUCT_WORKERS", "2")
    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {"source": "test"})
    monkeypatch.setattr("retail.store_categories.normalize_group", lambda value: "supermercados")
    monkeypatch.setattr("retail.store_categories.stores_for_group", lambda value: ["lider"])
    monkeypatch.setattr(
        "retail.store_categories.filter_products_for_group", lambda catalog, value: products
    )
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)

    lock = threading.Lock()
    active = 0
    maximum = 0

    def fake_search(query, **kwargs):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {
            "offer_count": 0,
            "comparable_count": 0,
            "groups": [],
            "saved": {},
            "warnings": [],
            "store_errors": [],
        }

    monkeypatch.setattr(runner, "search_products", fake_search)
    runner.run_batch(grupo="supermercados", persist=False, pause=0, time_budget_minutes=1)
    assert maximum == 1


def test_group_batch_queries_imported_product_only_in_its_origin_store(monkeypatch):
    from retail.batch import runner

    seen = []
    product = {"id": "prod-lider-123", "query": "leche entera", "category": "alimentos"}
    monkeypatch.setattr(runner, "refresh_store_categories", lambda: {"source": "test"})
    monkeypatch.setattr("retail.store_categories.normalize_group", lambda value: "supermercados")
    monkeypatch.setattr(
        "retail.store_categories.stores_for_group", lambda value: ["lider", "jumbo", "tottus"]
    )
    monkeypatch.setattr(
        "retail.store_categories.filter_products_for_group", lambda products, value: [product]
    )
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)

    def fake_search(query, **kwargs):
        seen.append(kwargs)
        return {
            "offer_count": 0,
            "comparable_count": 0,
            "groups": [],
            "saved": {},
            "warnings": [],
            "store_errors": [],
        }

    monkeypatch.setattr(runner, "search_products", fake_search)
    summary = runner.run_batch(
        grupo="supermercados", persist=False, pause=0, time_budget_minutes=1
    )
    assert len(summary["searches"]) == 1
    assert seen[0]["stores"] == ["lider"]
    assert seen[0]["max_items"] == 3
    assert seen[0]["persist"] is False
    assert seen[0]["fresh"] is True
    assert seen[0]["background_side_effects"] is False
    assert seen[0]["wait_for_all"] is True


def test_schedule_preserves_batch_budget(tmp_path, monkeypatch):
    from retail.batch import config

    monkeypatch.setattr(config, "SCHEDULE_PATH", tmp_path / "programacion.json")

    class Repo:
        saved = None

        def get_app_setting(self, key):
            return self.saved

        def save_app_setting(self, key, value):
            self.saved = value

    repo = Repo()
    first = config.save_schedule(
        {"enabled": True, "hour": 0, "minute": 0, "batch_budget_minutes": 75}, repo
    )
    second = config.save_schedule({"enabled": True, "hour": 1, "minute": 0}, repo)
    assert first["batch_budget_minutes"] == 75
    assert second["batch_budget_minutes"] == 75


def test_cron_line_and_settings_page():
    from retail.batch.schedule import cron_line

    line = cron_line(8, 30)
    assert line.startswith("30 8 * * *")
    assert "ofertas-diarias.sh" in line
    client = TestClient(app)
    settings = client.get("/api/settings")
    assert settings.status_code == 401
    page = client.get("/ofertas", follow_redirects=False)
    assert page.status_code == 303
    assert "/entrar" in page.headers.get("location", "")
    login = client.get("/entrar")
    assert login.status_code == 200
    assert "Inscribirse" in login.text
    assert "Crear cuenta" in login.text
    home = client.get("/")
    assert home.status_code == 200
    assert "history-panel" in home.text
    assert 'data-admin hidden' in home.text
