"""Canales de aviso: archivo + respaldo Mongo + overlay .env."""

from __future__ import annotations

from retail.batch import config as channels_config


class _FakeRepo:
    def __init__(self):
        self.settings: dict = {}

    def get_app_setting(self, key: str):
        found = self.settings.get(key)
        return dict(found) if isinstance(found, dict) else None

    def save_app_setting(self, key: str, value: dict):
        self.settings[key] = dict(value)
        return dict(value)

    def close(self):
        return None


def _clear_channel_env(monkeypatch):
    for names in channels_config._CHANNEL_ENV_NAMES.values():
        for name in names:
            monkeypatch.delenv(name, raising=False)


def test_save_channels_writes_file_and_mongo(tmp_path, monkeypatch):
    path = tmp_path / "canales.local.json"
    monkeypatch.setattr(channels_config, "CHANNELS_PATH", path)
    _clear_channel_env(monkeypatch)
    repo = _FakeRepo()
    payload = channels_config.save_channels(
        {
            "telegram_bot_token": "123:abc",
            "telegram_chat_id": "99",
            "smtp_host": "",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "",
            "alert_email_to": "",
        },
        repo,
    )
    assert payload["telegram_bot_token"] == "123:abc"
    assert path.exists()
    assert repo.settings[channels_config.CHANNELS_SETTING_KEY]["telegram_bot_token"] == "123:abc"


def test_load_channels_heals_from_mongo_when_file_missing(tmp_path, monkeypatch):
    path = tmp_path / "canales.local.json"
    monkeypatch.setattr(channels_config, "CHANNELS_PATH", path)
    _clear_channel_env(monkeypatch)
    repo = _FakeRepo()
    repo.settings[channels_config.CHANNELS_SETTING_KEY] = {
        "telegram_bot_token": "999:recover",
        "telegram_chat_id": "42",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_password": "",
        "smtp_from": "",
        "alert_email_to": "",
    }
    loaded = channels_config.load_channels(repo)
    assert loaded["telegram_bot_token"] == "999:recover"
    assert loaded["telegram_chat_id"] == "42"
    assert path.exists()
    assert "999:recover" in path.read_text(encoding="utf-8")


def test_load_channels_env_wins_over_file(tmp_path, monkeypatch):
    path = tmp_path / "canales.local.json"
    monkeypatch.setattr(channels_config, "CHANNELS_PATH", path)
    _clear_channel_env(monkeypatch)
    channels_config.write_json(
        path,
        {
            "telegram_bot_token": "111:file",
            "telegram_chat_id": "1",
            "smtp_host": "smtp.file",
            "smtp_port": 587,
            "smtp_user": "",
            "smtp_password": "",
            "smtp_from": "",
            "alert_email_to": "",
        },
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "222:env")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app-pass")
    monkeypatch.setenv("SMTP_TO", "alerts@example.com")
    loaded = channels_config.load_channels(_FakeRepo())
    assert loaded["telegram_bot_token"] == "222:env"
    assert loaded["telegram_chat_id"] == "99"
    assert loaded["smtp_host"] == "smtp.gmail.com"
    assert loaded["smtp_password"] == "app-pass"
    assert loaded["alert_email_to"] == "alerts@example.com"


def test_merge_secrets_blank_does_not_wipe_env(tmp_path, monkeypatch):
    path = tmp_path / "canales.local.json"
    monkeypatch.setattr(channels_config, "CHANNELS_PATH", path)
    _clear_channel_env(monkeypatch)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "333:env")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    merged = channels_config.merge_secrets(
        {
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_user": "user@gmail.com",
            "smtp_password": "",
            "smtp_from": "",
            "alert_email_to": "",
        }
    )
    assert merged["telegram_bot_token"] == "333:env"
    assert merged["smtp_password"] == "secret"
    assert merged["smtp_host"] == "smtp.gmail.com"
    assert merged["smtp_user"] == "user@gmail.com"
