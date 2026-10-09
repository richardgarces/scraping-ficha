from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from retail.forecast_outcomes import (
    build_outcome_snapshot,
    evaluate_outcome_document,
    list_outcomes,
    outcome_stats,
    snapshot_forecast_docs,
)
from retail.web.app import app


def _forecast_doc(**overrides):
    base = {
        "forecast_key": "lider:sku-tv",
        "store": "lider",
        "product_id": "sku-tv",
        "name": "Smart TV",
        "model": "timesfm",
        "horizon": 5,
        "generated_at": datetime(2026, 10, 1, 15, tzinfo=timezone.utc),
        "point_forecast": [90000, 88000, 86000, 85000, 84000],
        "quantiles": {"0.1": [80000] * 5, "0.9": [95000] * 5},
        "metadata": {"observation_count": 45},
    }
    base.update(overrides)
    return base


def test_build_outcome_snapshot_skips_simulated_and_empty():
    assert build_outcome_snapshot({"model": "simulated", "point_forecast": [1, 2]}) is None
    assert build_outcome_snapshot({"model": "timesfm", "point_forecast": []}) is None


def test_evaluate_hit_when_price_enters_range():
    snap = build_outcome_snapshot(_forecast_doc(), baseline_price=100000)
    assert snap is not None
    assert snap["status"] == "pending"
    assert snap["trend"] == "down"
    gen = snap["generated_at"]
    history = [
        {"price": 100000, "scraped_at": (gen - timedelta(days=1)).isoformat()},
        {"price": 87000, "scraped_at": (gen + timedelta(days=2, hours=3)).isoformat()},
    ]
    updates = evaluate_outcome_document(snap, history, now=gen + timedelta(days=3))
    assert updates["status"] == "hit"
    assert updates["days_to_hit"] == 2
    assert updates["hit_reason"] == "range"
    assert updates["eta_days"] == 0


def test_evaluate_miss_when_horizon_ends_without_hit():
    snap = build_outcome_snapshot(
        _forecast_doc(
            point_forecast=[100000, 100000, 100000],
            horizon=3,
            quantiles={"0.1": [99000] * 3, "0.9": [101000] * 3},
        ),
        baseline_price=100000,
    )
    gen = snap["generated_at"]
    history = [
        {"price": 120000, "scraped_at": (gen + timedelta(days=1)).isoformat()},
        {"price": 121000, "scraped_at": (gen + timedelta(days=2)).isoformat()},
        {"price": 122000, "scraped_at": (gen + timedelta(days=3)).isoformat()},
    ]
    updates = evaluate_outcome_document(snap, history, now=gen + timedelta(days=4))
    assert updates["status"] == "miss"
    assert updates["days_to_hit"] is None
    assert updates["days_elapsed"] == 3


def test_evaluate_pending_tracks_eta_and_elapsed():
    snap = build_outcome_snapshot(_forecast_doc(), baseline_price=100000)
    gen = snap["generated_at"]
    updates = evaluate_outcome_document(snap, [], now=gen + timedelta(days=1, hours=2))
    assert updates["status"] == "pending"
    assert updates["days_elapsed"] == 1
    assert updates["eta_days"] >= 0


def test_directional_hit_without_tight_range():
    snap = build_outcome_snapshot(
        {
            "forecast_key": "ripley:x",
            "store": "ripley",
            "product_id": "x",
            "name": "Item",
            "model": "last_value_baseline",
            "horizon": 4,
            "generated_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            "point_forecast": [90, 88, 86, 84],
            "quantiles": {},
            "metadata": {"observation_count": 10},
        },
        baseline_price=100,
    )
    # Without quantiles, range becomes ±2% of expected (~87); use clear drop.
    gen = snap["generated_at"]
    history = [{"price": 80, "scraped_at": (gen + timedelta(days=1)).isoformat()}]
    updates = evaluate_outcome_document(snap, history, now=gen + timedelta(days=2))
    assert updates["status"] == "hit"
    assert updates["hit_reason"] in {"range", "direction_down"}


def test_snapshot_forecast_docs_is_idempotent():
    stored = []

    class Coll:
        def create_index(self, *a, **k):
            return None

        def find_one(self, query, *_a, **_k):
            for item in stored:
                if all(item.get(k) == query.get(k) for k in query):
                    return {"_id": "1"}
            return None

        def insert_one(self, doc):
            stored.append(doc)
            return SimpleNamespace(inserted_id="1")

    repo = SimpleNamespace(
        forecast_outcomes=Coll(),
        collection=SimpleNamespace(find_one=lambda *a, **k: {"price": 100000}),
        db=None,
    )
    docs = [_forecast_doc()]
    assert snapshot_forecast_docs(repo, docs) == 1
    assert snapshot_forecast_docs(repo, docs) == 0
    assert len(stored) == 1


def test_list_and_stats_helpers():
    rows = [
        {
            "forecast_key": "a:1",
            "model": "timesfm",
            "status": "hit",
            "generated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
            "days_to_hit": 2,
            "eta_days": 0,
            "name": "A",
            "store": "a",
            "product_id": "1",
        },
        {
            "forecast_key": "b:2",
            "model": "timesfm",
            "status": "miss",
            "generated_at": datetime(2026, 10, 2, tzinfo=timezone.utc),
            "days_to_hit": None,
            "eta_days": 0,
            "name": "B",
            "store": "b",
            "product_id": "2",
        },
        {
            "forecast_key": "c:3",
            "model": "cyber_event_dense",
            "status": "pending",
            "generated_at": datetime(2026, 10, 3, tzinfo=timezone.utc),
            "days_to_hit": None,
            "eta_days": 3,
            "name": "C",
            "store": "c",
            "product_id": "3",
        },
    ]

    class Cursor:
        def __init__(self, items):
            self._items = items

        def sort(self, *_a, **_k):
            return self

        def skip(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def __iter__(self):
            return iter(self._items)

    class Coll:
        def create_index(self, *a, **k):
            return None

        def count_documents(self, query):
            if not query:
                return len(rows)
            status = query.get("status")
            return sum(1 for row in rows if row.get("status") == status)

        def find(self, query=None, *_a, **_k):
            query = query or {}
            items = rows
            if query.get("status"):
                items = [row for row in rows if row["status"] == query["status"]]
            return Cursor([{**row} for row in items])

        def aggregate(self, *_a, **_k):
            return [
                {
                    "_id": "timesfm",
                    "total": 2,
                    "hit": 1,
                    "miss": 1,
                    "pending": 0,
                    "days": [2, None],
                },
                {
                    "_id": "cyber_event_dense",
                    "total": 1,
                    "hit": 0,
                    "miss": 0,
                    "pending": 1,
                    "days": [None],
                },
            ]

        def distinct(self, *_a, **_k):
            return []

    repo = SimpleNamespace(forecast_outcomes=Coll(), db=None)
    listed = list_outcomes(repo, page=1, size=40)
    assert listed["total"] == 3
    assert len(listed["items"]) == 3
    stats = outcome_stats(repo)
    assert stats["total"] == 3
    assert stats["by_status"]["hit"] == 1
    assert stats["hit_rate"] == 50.0
    assert stats["median_days_to_hit"] == 2
    assert any(item["model"] == "timesfm" for item in stats["by_model"])


def test_pronosticos_page_requires_admin():
    client = TestClient(app)
    page = client.get("/pronosticos", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")


def test_pronosticos_page_assets_and_nav_links():
    html = Path("retail/web/static/pronosticos.html").read_text(encoding="utf-8")
    js = Path("retail/web/static/pronosticos.js").read_text(encoding="utf-8")
    assert "Cumplimiento" in html
    assert "outcome-stats" in html
    assert "pronosticos.js?v=1" in html
    assert "/api/admin/forecast-outcomes" in js
    assert "días a cumplir" in js
    index = Path("retail/web/static/index.html").read_text(encoding="utf-8")
    assert 'href="/pronosticos"' in index
    assert "data-admin" in index


def test_forecast_outcomes_api_requires_admin(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.forecasts_api.connect_repo", lambda: anonymous_repo)
    monkeypatch.setattr("retail.web.deps.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    denied = client.get("/api/admin/forecast-outcomes")
    assert denied.status_code == 401


def test_forecast_outcomes_api_returns_list_for_admin(monkeypatch):
    monkeypatch.setattr(
        "retail.web.forecasts_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1"},
    )
    repo = SimpleNamespace(
        forecast_outcomes=SimpleNamespace(),
        close=lambda: None,
    )

    def fake_list(*_a, **_k):
        return {
            "items": [{
                "forecast_key": "lider:1",
                "name": "TV",
                "status": "pending",
                "model": "timesfm",
                "eta_days": 3,
            }],
            "total": 1,
            "page": 1,
            "size": 40,
        }

    monkeypatch.setattr("retail.web.forecasts_api.list_outcomes", fake_list)
    monkeypatch.setattr("retail.web.forecasts_api.connect_repo", lambda: repo)
    monkeypatch.setattr(
        "retail.web.forecasts_api.outcome_stats",
        lambda *_a, **_k: {"total": 1, "by_status": {"pending": 1}, "hit_rate": None, "by_model": []},
    )

    client = TestClient(app)
    response = client.get("/api/admin/forecast-outcomes")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    stats = client.get("/api/admin/forecast-outcomes/stats")
    assert stats.status_code == 200
    assert stats.json()["total"] == 1
