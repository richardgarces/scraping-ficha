import json

from retail.batch import config


class SettingsRepo:
    def __init__(self, saved=None):
        self.saved = saved

    def get_app_setting(self, key):
        assert key == "batch_schedule"
        return self.saved

    def save_app_setting(self, key, value):
        assert key == "batch_schedule"
        self.saved = dict(value)
        return self.saved


def test_schedule_is_saved_to_database_and_json_mirror(tmp_path, monkeypatch):
    path = tmp_path / "programacion.json"
    monkeypatch.setattr(config, "SCHEDULE_PATH", path)
    repo = SettingsRepo()

    saved = config.save_schedule(
        {"enabled": True, "hour": 9, "minute": 15, "source": "scrape", "pause": 1.5},
        repo,
    )

    assert repo.saved == saved
    assert json.loads(path.read_text()) == saved
    assert config.load_schedule(repo)["hour"] == 9
    assert config.load_schedule(repo)["minute"] == 15


def test_database_schedule_has_priority_over_json(tmp_path, monkeypatch):
    path = tmp_path / "programacion.json"
    path.write_text(json.dumps({"enabled": True, "hour": 6, "minute": 0}))
    monkeypatch.setattr(config, "SCHEDULE_PATH", path)
    repo = SettingsRepo({"enabled": True, "hour": 11, "minute": 30, "source": "db", "pause": 4})

    loaded = config.load_schedule(repo)

    assert loaded["hour"] == 11
    assert loaded["minute"] == 30
    assert loaded["source"] == "db"


def test_midnight_and_zero_pause_are_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCHEDULE_PATH", tmp_path / "programacion.json")
    repo = SettingsRepo()

    saved = config.save_schedule(
        {"enabled": True, "hour": 0, "minute": 0, "source": "both", "pause": 0},
        repo,
    )

    assert saved["hour"] == 0
    assert saved["minute"] == 0
    assert saved["pause"] == 0


def test_pause_state_is_saved_and_preserved_when_editing_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SCHEDULE_PATH", tmp_path / "programacion.json")
    repo = SettingsRepo()

    paused = config.save_schedule(
        {"enabled": True, "paused": True, "hour": 6, "minute": 0, "source": "scrape", "pause": 2},
        repo,
    )
    assert paused["paused"] is True

    edited = config.save_schedule(
        {"enabled": True, "hour": 7, "minute": 30, "source": "scrape", "pause": 2},
        repo,
    )
    assert edited["paused"] is True
