"""Estadísticas de peticiones: conteo, origen y agregados por día y hora."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from retail.request_stats import (
    apply_hit,
    client_country,
    client_ip,
    make_bucket,
    path_group,
    record_request,
    should_count,
    summarize_rows,
)
from retail.web.app import app


class _Buckets:
    def __init__(self):
        self.docs: dict[tuple, dict] = {}

    def update_one(self, filt, update, upsert=False):
        key = (filt["day"], filt["hour"], filt["ip"], filt["country"])
        doc = self.docs.get(key)
        if doc is None:
            assert upsert
            doc = {
                "day": filt["day"],
                "hour": filt["hour"],
                "ip": filt["ip"],
                "country": filt["country"],
                "count": 0,
                "groups": {},
            }
            self.docs[key] = doc
        for field, value in update["$inc"].items():
            if field == "count":
                doc["count"] += int(value)
            elif field.startswith("groups."):
                name = field.split(".", 1)[1]
                doc["groups"][name] = int(doc["groups"].get(name) or 0) + int(value)
            else:
                doc[field] = int(doc.get(field) or 0) + int(value)


def test_should_count_pages_and_search_not_static_or_stats():
    assert should_count("/")
    assert should_count("/catalogo")
    assert path_group("/analisis-producto") == "admin"
    assert should_count("/api/search")
    assert should_count("/api/catalog")
    assert should_count("/api/deals")
    assert should_count("/api/stores-report")
    assert not should_count("/static/styles.css")
    assert not should_count("/favicon.ico")
    assert not should_count("/api/health")
    assert not should_count("/api/admin/stats")
    assert not should_count("/api/clicks")
    assert not should_count("/api/clicks", method="POST")
    assert not should_count("/api/thumb")
    assert not should_count("/api/auth/me")
    assert not should_count("/", method="OPTIONS")


def test_origin_uses_forwarded_first_hop_and_country_header():
    headers = {"x-forwarded-for": "203.0.113.9, 10.0.0.8", "cf-ipcountry": "cl"}
    assert client_ip(headers, "127.0.0.1") == "203.0.113.9"
    assert client_country(headers) == "CL"
    assert client_ip({}, "10.1.2.3") == "10.1.2.3"
    assert client_country({"cf-ipcountry": "XX"}) == ""


def test_bucket_is_santiago_and_drops_query_string():
    when = datetime(2026, 9, 16, 2, 30, tzinfo=timezone.utc)
    bucket = make_bucket("/api/search?q=secreto&token=abc", "203.0.113.4", "cl", when=when)
    assert bucket["day"] == "2026-09-15"
    assert bucket["hour"] == 23
    assert bucket["group"] == "buscar"
    assert bucket["country"] == "CL"
    assert "secreto" not in str(bucket)
    assert "token" not in str(bucket)


def test_apply_hit_increments_same_origin_bucket():
    buckets = _Buckets()
    when = datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc)
    first = record_request("/?q=televisor", "203.0.113.4", "CL", when=when, collection=buckets)
    second = record_request("/api/catalog", "203.0.113.4", "CL", when=when, collection=buckets)
    assert first is not None and second is not None
    assert len(buckets.docs) == 1
    doc = next(iter(buckets.docs.values()))
    assert doc["count"] == 2
    assert doc["visits"] == 1
    assert doc["groups"]["buscar"] == 1
    assert doc["groups"]["catalogo"] == 1
    assert "televisor" not in str(doc)
    skipped = record_request("/api/admin/stats", "203.0.113.4", "CL", when=when, collection=buckets)
    assert skipped is None
    assert doc["count"] == 2
    apply_hit(buckets, day="2026-09-16", hour=8, ip="203.0.113.4", country="CL", group="otro")
    assert buckets.docs[("2026-09-16", 8, "203.0.113.4", "CL")]["count"] == 1


def test_summarize_groups_by_day_and_hour():
    now = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    rows = [
        {
            "day": "2026-09-16",
            "hour": 12,
            "ip": "203.0.113.4",
            "country": "CL",
            "count": 5,
            "visits": 4,
            "groups": {"buscar": 5},
        },
        {
            "day": "2026-09-15",
            "hour": 23,
            "ip": "198.51.100.2",
            "country": "",
            "count": 3,
            "groups": {"catalogo": 3},
        },
        {
            "day": "2026-09-16",
            "hour": 12,
            "ip": "198.51.100.9",
            "country": "AR",
            "count": 2,
            "groups": {"ofertas": 2},
        },
    ]
    stats = summarize_rows(rows, now=now)
    assert stats["timezone"] == "America/Santiago"
    assert stats["totals"]["today"] == 7
    assert stats["totals"]["days_7"] == 10
    assert stats["totals"]["days_30"] == 10
    assert len(stats["by_day"]) == 30
    assert stats["by_day"][-1] == {"day": "2026-09-16", "count": 7, "visitors": 2, "page_visits": 4}
    assert stats["by_day"][-2] == {"day": "2026-09-15", "count": 3, "visitors": 1, "page_visits": 0}
    assert stats["by_day"][0]["count"] == 0
    assert stats["visitors"] == {"today": 2, "days_7": 3, "days_30": 3}
    assert stats["page_visits"] == {"today": 4, "days_7": 4, "days_30": 4}
    assert len(stats["by_hour"]) == 24
    assert stats["by_hour"][12]["today"] == 7
    assert stats["by_hour"][12]["average"] == round(7 / 30, 1)
    assert stats["by_hour"][23]["today"] == 0
    assert stats["by_hour"][23]["average"] == round(3 / 30, 1)
    assert stats["origins"][0]["ip"] == "203.0.113.4"
    assert stats["origins"][0]["country"] == "CL"
    assert stats["origins"][0]["count"] == 5
    assert {item["group"] for item in stats["groups"]} == {"buscar", "catalogo", "ofertas"}


def test_middleware_increments_user_requests_only(monkeypatch):
    calls = []

    monkeypatch.setattr("retail.request_stats._live_collection", lambda: object())

    def fake_apply(collection, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("retail.request_stats.apply_hit", fake_apply)
    client = TestClient(app)
    home = client.get(
        "/?q=no-guardar",
        headers={"x-forwarded-for": "198.51.100.7, 10.0.0.1", "cf-ipcountry": "CL"},
    )
    assert home.status_code == 200
    client.get("/static/styles.css")
    client.get("/api/health")
    client.get("/favicon.ico")
    client.get("/catalogo")
    assert calls
    assert all("no-guardar" not in str(call) for call in calls)
    home_hits = [call for call in calls if call["group"] == "buscar"]
    assert home_hits and all(call["ip"] == "198.51.100.7" and call["country"] == "CL" for call in home_hits)
    assert {call["group"] for call in calls} == {"buscar", "catalogo"}
    assert not any(call["group"] == "admin" for call in calls)


def test_stats_page_and_api_require_admin(anonymous_repo):
    client = TestClient(app)
    denied = client.get("/api/admin/stats")
    assert denied.status_code == 401
    page = client.get("/estadisticas", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")
    html = __import__("pathlib").Path("retail/web/static/index.html").read_text()
    assert 'href="/estadisticas"' in html
    assert "data-admin" in html


def test_stats_script_is_isolated_from_shared_price_globals():
    """prices.js define `$`; estadísticas no debe redeclararlo en el ámbito global."""
    from pathlib import Path

    script = Path("retail/web/static/estadisticas.js").read_text(encoding="utf-8")
    page = Path("retail/web/static/estadisticas.html").read_text(encoding="utf-8")
    assert "(() => {" in script
    assert script.rstrip().endswith("})();")
    assert 'estadisticas.js?v=7' in page
