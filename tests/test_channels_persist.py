"""Canales de aviso: archivo + respaldo Mongo si se borra output/."""

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


def test_save_channels_writes_file_and_mongo(tmp_path, monkeypatch):
    path = tmp_path / "canales.local.json"
    monkeypatch.setattr(channels_config, "CHANNELS_PATH", path)
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
