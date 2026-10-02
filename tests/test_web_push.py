from retail.web_push import normalize_subscription, push_message, vapid_keys


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


def test_subscription_requires_https_and_keeps_only_web_push_fields():
    result = normalize_subscription({
        "endpoint": "https://push.example/subscription/1",
        "keys": {"p256dh": "public-key", "auth": "secret", "ignored": "x"},
        "ignored": "x",
    })
    assert result["endpoint"] == "https://push.example/subscription/1"
    assert result["keys"] == {"p256dh": "public-key", "auth": "secret"}


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
    assert "Tienda Chile · $12.990" in message["body"]
    assert message["url"] == "https://lnk.meincart.cl/o/123456789"
    assert message["tag"] == "precio-audifonos"


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
