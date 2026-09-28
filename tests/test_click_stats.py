"""Clics de la web: ventanas en Santiago y sin inflar las visitas."""

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from retail.click_stats import parse_click_kind, record_click, summarize_click_rows
from retail.request_stats import should_count
from retail.web.app import app


class _Inserts:
    def __init__(self):
        self.docs = []

    def insert_one(self, document):
        self.docs.append(document)


def test_click_log_keeps_kind_and_page_without_query():
    store = _Inserts()
    when = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    saved = record_click(
        "Catalogo",
        "203.0.113.8",
        "cl",
        origin="https://precios.meincart.cl/hoy?q=secreto",
        when=when,
        collection=store,
    )
    assert saved["kind"] == "catalogo"
    assert saved["origin"] == "/hoy"
    assert saved["country"] == "CL"
    assert "secreto" not in str(saved)
    assert record_click("admin", collection=store) is None
    assert record_click("catalogo", origin="/estadisticas", collection=store) is None
    assert record_click("fecha", origin="/cron", collection=store) is None
    assert len(store.docs) == 1


def test_parse_click_kind_accepts_json_and_form():
    assert parse_click_kind(b'{"kind":"externo"}') == "externo"
    assert parse_click_kind(b"kind=fecha") == "fecha"
    assert parse_click_kind(b"") == ""
    assert parse_click_kind(b'{"kind":') == ""


def test_summarize_counts_windows_and_which_item_in_santiago():
    now = datetime(2026, 9, 16, 15, 0, tzinfo=timezone.utc)
    rows = [
        {"kind": "catalogo", "created_at": datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)},
        {"kind": "externo", "created_at": datetime(2026, 9, 16, 13, 0, tzinfo=timezone.utc)},
        {"kind": "fecha", "created_at": datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)},
        # 02:30 UTC es todavía el 15 en Santiago: no cuenta como hoy.
        {"kind": "hoy", "created_at": datetime(2026, 9, 16, 2, 30, tzinfo=timezone.utc)},
        {"kind": "cron", "created_at": datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)},
    ]
    stats = summarize_click_rows(rows, now=now)
    assert stats["timezone"] == "America/Santiago"
    assert stats["totals"]["today"] == 2
    assert stats["totals"]["days_7"] == 4
    assert stats["totals"]["days_30"] == 4
    assert stats["by_day"][-1] == {"day": "2026-09-16", "count": 2}
    assert stats["by_day"][-2]["count"] == 2
    by_kind = {item["kind"]: item for item in stats["items"]}
    assert [item["kind"] for item in stats["items"]] == [
        "catalogo",
        "hoy",
        "reales",
        "super",
        "tiendas",
        "fecha",
        "externo",
    ]
    assert by_kind["catalogo"]["today"] == 1
    assert by_kind["externo"]["days_30"] == 1
    assert by_kind["fecha"]["today"] == 0
    assert by_kind["fecha"]["days_7"] == 1
    assert by_kind["hoy"]["today"] == 0
    assert by_kind["hoy"]["days_7"] == 1
    assert by_kind["reales"]["days_30"] == 0
    assert "cron" not in by_kind


def test_click_endpoint_does_not_inflate_visits(monkeypatch):
    calls = []
    saved = []

    monkeypatch.setattr("retail.request_stats._live_collection", lambda: object())

    def fake_apply(collection, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr("retail.request_stats.apply_hit", fake_apply)

    def fake_record(kind, ip="", country="", *, origin="", when=None, collection=None):
        saved.append({"kind": kind, "ip": ip, "country": country, "origin": origin})
        return {"kind": kind} if kind == "externo" else None

    monkeypatch.setattr("retail.web.app.record_click", fake_record)
    client = TestClient(app)
    ok = client.post(
        "/api/clicks",
        content=b"kind=externo",
        headers={
            "content-type": "application/x-www-form-urlencoded",
            "x-forwarded-for": "203.0.113.9, 10.0.0.1",
            "cf-ipcountry": "cl",
            "referer": "https://precios.meincart.cl/producto?store=lider&id=1",
        },
    )
    assert ok.status_code == 200
    assert saved == [{"kind": "externo", "ip": "203.0.113.9", "country": "CL", "origin": "/producto"}]
    denied = client.post("/api/clicks", json={"kind": "no-existe"})
    assert denied.status_code == 400
    assert should_count("/api/clicks", method="POST") is False
    assert not calls
