from retail.web_push import (
    normalize_subscription,
    push_click_url,
    push_message,
    vapid_for_webpush,
    vapid_keys,
)


class SettingsRepo:
    def __init__(self):
        self.value = None

    def get_app_setting(self, key):
        return self.value

    def save_app_setting(self, key, value):
        self.value = dict(value)
        return self.value


def test_vapid_keys_are_generated_once_and_have_browser_public_format():
    repo = SettingsRepo()
    first = vapid_keys(repo)
    second = vapid_keys(repo)
    assert first == second
    assert first["private_key"].startswith("-----BEGIN PRIVATE KEY-----")
    assert len(first["public_key"]) == 87


def test_pem_private_key_loads_for_pywebpush_without_asn1_error():
    """pywebpush 2 rechaza el PEM que guardamos; hay que entregarle un Vapid."""
    from py_vapid import Vapid

    repo = SettingsRepo()
    keys = vapid_keys(repo)
    signer = vapid_for_webpush(keys["private_key"])
    assert isinstance(signer, Vapid)
    numbers = signer.public_key.public_numbers()
    raw = b"\x04" + numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    import base64
    public = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    assert public == keys["public_key"]
    # El PEM tal cual no es una clave que from_string pueda abrir.
    try:
        Vapid.from_string(keys["private_key"])
    except Exception:
        return
    raise AssertionError("from_string aceptó un PEM; el adaptador ya no haría falta")


def test_subscription_requires_https_and_keeps_only_web_push_fields():
    result = normalize_subscription({
        "endpoint": "https://push.example/subscription/1",
        "keys": {"p256dh": "public-key", "auth": "secret", "ignored": "x"},
        "ignored": "x",
    })
    assert result["endpoint"] == "https://push.example/subscription/1"
    assert result["keys"] == {"p256dh": "public-key", "auth": "secret"}


def test_push_message_includes_https_product_image_and_app_icon():
    message = push_message({
        "name": "Audífonos",
        "message": "Bajó de precio",
        "image_url": "https://cdn.example/audifonos.jpg",
    })
    assert message["image"] == "https://cdn.example/audifonos.jpg"
    assert message["icon"] == "/static/brand/icon-192.png"


def test_push_message_omits_image_when_there_is_no_photo():
    message = push_message({"name": "Audífonos", "message": "Bajó de precio"})
    assert "image" not in message
    assert message["icon"] == "/static/brand/icon-192.png"


def test_push_message_never_sends_a_challenge_url():
    blocked = push_message({
        "name": "TV",
        "message": "Oferta",
        "image_url": "https://www.lider.cl/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page",
        "product_image_url": "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/turnstile",
    })
    assert "image" not in blocked
    fallback = push_message({
        "name": "TV",
        "message": "Oferta",
        "image_url": "https://www.lider.cl/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page",
        "product_image_url": "https://cdn.example/tv.jpg",
    })
    assert fallback["image"] == "https://cdn.example/tv.jpg"


def test_push_message_uses_product_photo_when_screenshot_is_only_local(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFER_SCREENSHOT_PUBLIC", "0")
    photo = tmp_path / "lider_tv.png"
    photo.write_bytes(b"png")
    message = push_message({
        "name": "TV",
        "message": "Oferta",
        "image_url": str(photo),
        "product_image_url": "https://cdn.example/tv.jpg",
    })
    assert message["image"] == "https://cdn.example/tv.jpg"
    assert "offer-shots" not in message["image"]


def test_push_message_publishes_screenshot_when_the_site_serves_it(tmp_path, monkeypatch):
    monkeypatch.setenv("OFFER_SCREENSHOT_PUBLIC", "1")
    monkeypatch.setenv("OFFER_SCREENSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    photo = tmp_path / "lider_p1_20261003.png"
    photo.write_bytes(b"png")
    outside = tmp_path.parent / "fuera.png"
    outside.write_bytes(b"png")
    published = push_message({
        "name": "TV",
        "message": "Oferta",
        "image_url": str(photo),
        "product_image_url": "https://cdn.example/tv.jpg",
    })
    assert published["image"] == "https://precios.meincart.cl/offer-shots/lider_p1_20261003.png"
    hidden = push_message({
        "name": "TV",
        "message": "Oferta",
        "image_url": str(outside),
        "product_image_url": "https://cdn.example/tv.jpg",
    })
    assert hidden["image"] == "https://cdn.example/tv.jpg"
    outside.unlink(missing_ok=True)


def test_daily_push_and_service_worker_carry_the_same_image(monkeypatch, tmp_path):
    from retail.batch import alerts
    from retail.batch.rules import Alert

    monkeypatch.setenv("OFFER_SCREENSHOT_PUBLIC", "1")
    monkeypatch.setenv("OFFER_SCREENSHOT_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    photo = tmp_path / "lider_p1_20261003.png"
    photo.write_bytes(b"png")
    sent = []

    def capture(user, payload, **kwargs):
        from retail.web_push import push_message as build

        sent.append(build(payload))
        return True

    monkeypatch.setattr("retail.web_push.send_user_push", capture)

    def use_screenshot(payload):
        payload["image_url"] = str(photo)
        return payload

    monkeypatch.setattr(alerts, "apply_offer_screenshot", use_screenshot)
    deal = Alert(
        catalog_id="tv", query="tv", rule="common_discount", name="TV",
        store="lider", price=100000, previous_price=200000, message="50%",
        url=None, compare_code="tv-img",
        extra={"percent": 50, "product_id": "p1"},
        image_url="https://cdn.example/tv.jpg",
    )
    user = {
        "id": "u1",
        "push_subscriptions": [{"endpoint": "https://push.example/1", "keys": {"p256dh": "a", "auth": "b"}}],
        "notification_preferences": {"channels": ["push"], "kinds": ["common"]},
    }
    assert alerts.dispatch_user_alerts([deal], [user], system_channels=["push"]) == 1
    assert sent[0]["image"] == "https://precios.meincart.cl/offer-shots/lider_p1_20261003.png"
    script = __import__("pathlib").Path("retail/web/static/push-sw.js").read_text(encoding="utf-8")
    client = __import__("pathlib").Path("retail/web/static/siguiendo.js").read_text(encoding="utf-8")
    assert "options.image = image" in script
    assert "notificationImage" in script
    assert "/push-sw-v3.js" in client
    assert "push-sw-v2.js" not in client
    assert "trustedPushTarget" in script


def test_offer_shot_route_serves_one_file_and_hides_the_directory(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from retail.web.app import app
    from retail.web.anti_scraping import inspect_request

    monkeypatch.setenv("OFFER_SCREENSHOT_DIR", str(tmp_path))
    (tmp_path / "lider_p1_20261003.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 16)
    secret = tmp_path / "notas.txt"
    secret.write_text("secreto", encoding="utf-8")
    client = TestClient(app)
    image = client.get("/offer-shots/lider_p1_20261003.png")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/png")
    assert image.content.startswith(b"\x89PNG")
    assert client.get("/offer-shots/notas.txt").status_code == 404
    assert client.get("/offer-shots/no-esta.png").status_code == 404
    leaked = client.get("/offer-shots/..%2Fnotas.txt")
    assert leaked.status_code == 404
    assert b"secreto" not in leaked.content
    assert inspect_request(
        "/offer-shots/lider_p1_20261003.png", "GET", {"user-agent": ""}, {}, None,
    ) is None
    worker = client.get("/push-sw-v3.js")
    assert worker.status_code == 200
    assert "options.image" in worker.text
    assert "trustedPushTarget" in worker.text
    assert client.get("/push-sw-v1.js").text == worker.text
    assert client.get("/push-sw-v2.js").text == worker.text


def test_push_message_links_to_internal_product_card():
    message = push_message({
        "name": "Audífonos",
        "store": "tienda",
        "price": 12990,
        "message": "Bajó de precio",
        "short_url": "https://lnk.meincart.cl/o/123456789",
        "extra": {"store_title": "Tienda Chile"},
    }, tag="audifonos")
    assert message["title"] == "Audífonos"
    assert "Tienda · $12.990" in message["body"]
    assert message["url"] == "https://lnk.meincart.cl/o/123456789"
    assert message["tag"] == "precio-audifonos"


def test_push_click_url_prefers_ficha_over_siguiendo(monkeypatch):
    monkeypatch.setenv("PUBLIC_SITE_URL", "https://precios.meincart.cl")
    assert push_click_url({
        "store": "falabella",
        "product_id": "iphone-x",
        "url": "https://www.falabella.com/product/iphone-x",
    }).endswith("/producto?store=falabella&id=iphone-x")
    assert push_click_url({"url": "/producto?store=paris&id=tv-1"}) == "/producto?store=paris&id=tv-1"
    assert push_click_url({
        "short_url": "https://lnk.meincart.cl/o/abc",
        "store": "falabella",
        "product_id": "x",
    }) == "https://lnk.meincart.cl/o/abc"
    assert push_click_url({"name": "sin oferta"}) == "/siguiendo"


def test_save_rules_accepts_push_channel(tmp_path, monkeypatch):
    from retail.batch import config

    target = tmp_path / "reglas.json"
    monkeypatch.setattr(config, "default_rules_path", lambda: target)
    saved = config.save_rules({
        "enabled": ["price_drop_percent"],
        "channels": ["log", "push", "invalid"],
        "price_drop_percent": 10,
    })
    assert saved["channels"] == ["log", "push"]
    assert "push" in target.read_text()
