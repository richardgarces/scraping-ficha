"""Estado de crons/lotes: progreso en Mongo y API solo admin."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from retail.batch.cron_status import (
    build_cron_batch_status,
    derive_group_status,
    progress_payload,
)
from retail.batch.schedule import group_slots
from retail.web.app import app


def test_group_slots_keep_midnight_as_a_valid_start(monkeypatch):
    monkeypatch.setattr(
        "retail.batch.schedule.enabled_group_ids",
        lambda _schedule: ["retail", "farmacias", "supermercados"],
    )
    slots = group_slots(
        {
            "enabled": True,
            "hour": 0,
            "minute": 0,
            "groups": {"stagger_minutes": 45},
        }
    )
    assert slots == [
        ("retail", 0, 0),
        ("farmacias", 0, 45),
        ("supermercados", 1, 30),
    ]


class FakeBatchRuns:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self._n = 0

    def insert_one(self, document):
        self._n += 1
        oid = str(self._n)
        row = dict(document)
        row["_id"] = oid
        self.docs[oid] = row

        class Res:
            inserted_id = oid

        return Res()

    def update_one(self, filt, update):
        oid = str(filt["_id"])
        doc = self.docs[oid]
        if "$set" in update:
            doc.update(update["$set"])
        if "$inc" in update:
            for key, value in update["$inc"].items():
                doc[key] = int(doc.get(key) or 0) + int(value)
        if "$push" in update:
            for key, value in update["$push"].items():
                doc.setdefault(key, []).append(value)

    def find(self):
        return FakeCursor(list(self.docs.values()))

    def find_one(self, filt, sort=None):
        rows = list(self.docs.values())
        found = []
        for row in rows:
            if filt.get("tienda") and row.get("tienda") != filt.get("tienda"):
                continue
            if filt.get("status") and row.get("status") != filt.get("status"):
                continue
            found.append(row)
        if sort:
            key = sort[0][0]
            reverse = sort[0][1] == -1 or str(sort[0][1]).lower() in {"desc", "descending"}
            found.sort(key=lambda item: str(item.get(key) or ""), reverse=reverse)
        return found[0] if found else None

    def aggregate(self, pipeline):
        # Soporta latest_batch_runs_by_grupo y latest_batch_runs_by_tienda.
        match = {}
        group_field = "grupo"
        for stage in pipeline or []:
            if "$match" in stage:
                match = stage["$match"]
            group = (stage.get("$group") or {}).get("_id")
            if group == "$tienda":
                group_field = "tienda"
            elif group == "$grupo":
                group_field = "grupo"
        rows = [dict(item) for item in self.docs.values()]
        if group_field == "tienda" or match.get("tienda"):
            rows = [
                r
                for r in rows
                if isinstance(r.get("tienda"), str)
                and r.get("tienda")
                and r.get("scope") != "basico"
                and r.get("job") != "scraping_basico"
            ]
        else:
            rows = [
                r
                for r in rows
                if isinstance(r.get("grupo"), str)
                and r.get("grupo")
                and r.get("scope") not in {"tienda", "basico"}
                and r.get("job") != "scraping_basico"
                and not r.get("tienda")
            ]
        rows.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
        seen = set()
        out = []
        for row in rows:
            key = row[group_field]
            if key in seen:
                continue
            seen.add(key)
            out.append({"_id": key, "doc": row})
        return out


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeRepo:
    def __init__(self):
        self.batch_runs = FakeBatchRuns()

    def start_batch_run(self, data):
        from retail.mongo import ProductRepository

        # Reusa la lógica real sobre FakeBatchRuns
        return ProductRepository.start_batch_run(self, data)

    def update_batch_run(self, run_id, **fields):
        from retail.mongo import ProductRepository

        return ProductRepository.update_batch_run(self, run_id, **fields)

    def append_batch_search(self, run_id, row):
        from retail.mongo import ProductRepository

        return ProductRepository.append_batch_search(self, run_id, row)

    def finish_batch_run(self, run_id, **fields):
        from retail.mongo import ProductRepository

        return ProductRepository.finish_batch_run(self, run_id, **fields)

    def latest_batch_runs_by_grupo(self):
        from retail.mongo import ProductRepository

        return ProductRepository.latest_batch_runs_by_grupo(self)

    def latest_batch_runs_by_tienda(self):
        from retail.mongo import ProductRepository

        return ProductRepository.latest_batch_runs_by_tienda(self)

    def _public_batch_run(self, item):
        from retail.mongo import ProductRepository

        return ProductRepository._public_batch_run(self, item)

    def close(self):
        return None


class _Oid(str):
    pass


def test_batch_run_progress_upsert(monkeypatch):
    monkeypatch.setattr("bson.ObjectId", lambda value: _Oid(str(value)))
    repo = FakeRepo()
    run_id = repo.start_batch_run(
        {
            "started_at": "2026-09-15T10:00:00+00:00",
            "catalog": "test",
            "items": 2,
            "grupo": "tecnologia",
            "stores": ["falabella", "paris"],
            "phase": "index",
        }
    )
    assert run_id == "1"
    doc = repo.batch_runs.docs[run_id]
    assert doc["status"] == "running"
    assert doc["phase"] == "index"

    repo.update_batch_run(run_id, phase="products", current_query="iphone 16", current_id="iphone-16")
    assert doc["current_query"] == "iphone 16"
    assert doc["phase"] == "products"

    repo.append_batch_search(
        run_id,
        {"id": "iphone-16", "query": "iphone 16", "offers": 3, "saved": {"upserted": 2, "modified": 1}},
    )
    assert doc["processed"] == 1
    assert doc["saved_upserted"] == 2

    repo.finish_batch_run(run_id, status="done", alert_count=1)
    assert doc["status"] == "done"
    assert doc["phase"] == "done"
    assert doc["current_query"] is None

    by_grupo = repo.latest_batch_runs_by_grupo()
    assert "tecnologia" in by_grupo
    assert by_grupo["tecnologia"]["processed"] == 1
    assert by_grupo["tecnologia"]["stores_total"] == 2

    repo.start_batch_run(
        {
            "started_at": "2026-09-15T12:00:00+00:00",
            "items": 1,
            "grupo": "tecnologia",
            "tienda": "falabella",
            "stores": ["falabella"],
            "scope": "tienda",
        }
    )
    by_grupo = repo.latest_batch_runs_by_grupo()
    assert by_grupo["tecnologia"]["stores"] == ["falabella", "paris"]
    assert by_grupo["tecnologia"].get("tienda") in (None, "")
    by_store = repo.latest_batch_runs_by_tienda()
    assert by_store["falabella"]["stores"] == ["falabella"]
    assert by_store["falabella"]["scope"] == "tienda"


def test_derive_group_status_today():
    today = "2026-09-15"
    running = {
        "status": "running",
        "started_at": "2026-09-14T12:00:00+00:00",
        "items": 10,
        "processed": 3,
        "phase": "products",
        "current_query": "notebook",
    }
    assert derive_group_status(running, today=today) == "running"
    progress = progress_payload(running)
    assert progress["processed"] == 3
    assert progress["percent"] == 30.0

    done_today = {"status": "done", "started_at": "2026-09-15T09:00:00-03:00"}
    assert derive_group_status(done_today, today=today) == "done"

    failed_legacy = {"status": "error", "started_at": "2026-09-15T09:00:00-03:00"}
    assert derive_group_status(failed_legacy, today=today) == "failed"

    done_yesterday = {"status": "done", "started_at": "2026-09-14T09:00:00-03:00"}
    assert derive_group_status(done_yesterday, today=today) == "idle"


def test_build_cron_batch_status_uses_mongo(monkeypatch):
    monkeypatch.setattr("bson.ObjectId", lambda value: _Oid(str(value)))
    repo = FakeRepo()
    repo.start_batch_run(
        {
            "started_at": datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).isoformat(),
            "items": 4,
            "grupo": "tecnologia",
            "stores": ["falabella"],
            "phase": "products",
            "current_query": "galaxy",
        }
    )
    # Marcar processed a mano como si append hubiera corrido
    repo.batch_runs.docs["1"]["processed"] = 1

    monkeypatch.setattr(
        "retail.batch.cron_status.list_store_categories",
        lambda repo=None: [
            {"id": "tecnologia", "title": "Tecnología", "store_ids": ["falabella", "paris"]},
            {"id": "retail", "title": "Retail", "store_ids": ["lider"]},
        ],
    )
    monkeypatch.setattr(
        "retail.batch.cron_status.group_slots",
        lambda schedule=None: [("tecnologia", 6, 0), ("retail", 6, 45)],
    )
    monkeypatch.setattr(
        "retail.batch.cron_status.load_schedule",
        lambda: {"enabled": True, "hour": 6, "minute": 0, "groups": {"stagger_minutes": 45}},
    )
    monkeypatch.setattr(
        "retail.batch.cron_status.schedule_status",
        lambda: {
            "enabled": True,
            "source": "scrape",
            "pause": 3,
            "backend": "host",
            "groups": {"stagger_minutes": 45},
            "hint": "hint",
        },
    )

    payload = build_cron_batch_status(repo=repo, today="2026-09-15")
    assert payload["any_running"] is True
    by_id = {item["id"]: item for item in payload["groups"]}
    assert by_id["tecnologia"]["status"] == "running"
    assert by_id["tecnologia"]["progress"]["current_query"] == "galaxy"
    assert by_id["tecnologia"]["schedule"]["label"] == "06:00"
    assert by_id["retail"]["status"] == "idle"
    assert by_id["retail"]["schedule"]["label"] == "06:45"
    assert payload["store_jobs"] == []
    assert any(item["id"] == "falabella" for item in payload["stores"])


def test_store_job_progress_does_not_mark_the_group(monkeypatch):
    monkeypatch.setattr("bson.ObjectId", lambda value: _Oid(str(value)))
    repo = FakeRepo()
    repo.start_batch_run(
        {
            "started_at": datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc).isoformat(),
            "items": 3,
            "tienda": "ahumada",
            "groups": ["farmacias"],
            "stores": ["ahumada"],
            "scope": "tienda",
            "phase": "products",
            "current_query": "paracetamol",
        }
    )
    repo.batch_runs.docs["1"]["processed"] = 1
    monkeypatch.setattr(
        "retail.batch.cron_status.list_store_categories",
        lambda repo=None: [{"id": "farmacias", "title": "Farmacias", "store_ids": ["ahumada", "cruzverde"]}],
    )
    monkeypatch.setattr("retail.batch.cron_status.group_slots", lambda schedule=None: [("farmacias", 7, 0)])
    monkeypatch.setattr(
        "retail.batch.cron_status.load_schedule",
        lambda: {"enabled": True, "hour": 7, "minute": 0, "groups": {}},
    )
    monkeypatch.setattr(
        "retail.batch.cron_status.schedule_status",
        lambda: {"enabled": True, "source": "scrape", "pause": 2, "backend": "host", "groups": {}, "hint": ""},
    )
    payload = build_cron_batch_status(repo=repo, today="2026-09-15")
    assert payload["groups"][0]["status"] == "idle"
    job = payload["store_jobs"][0]
    assert job["id"] == "ahumada"
    assert job["status"] == "running"
    assert job["progress"]["current_query"] == "paracetamol"
    assert job["progress"]["stores_total"] == 1
    assert payload["any_running"] is True


def test_cron_page_and_api_are_admin_only():
    client = TestClient(app)
    page = client.get("/cron", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].startswith("/entrar")
    assert "next=" in page.headers["location"]
    api = client.get("/api/admin/cron-batches")
    assert api.status_code == 401
    denied = client.get("/api/admin/cron-batches/abc/alerts")
    assert denied.status_code == 401
    control = client.post("/api/admin/cron-control", json={"action": "pause"})
    assert control.status_code == 401


def test_public_run_alert_is_the_saved_offer_not_a_channel():
    from retail.mongo import ProductRepository

    row = ProductRepository.public_run_alert(
        {
            "_id": "a1",
            "name": "Zapatilla",
            "store": "falabella",
            "price": 19990,
            "previous_price": 29990,
            "rule": "price_drop_percent",
            "saving": 10000,
            "message": "Bajó 33.3%",
            "url": "https://example.test/p",
            "query": "zapatilla",
            "extra": {"product_id": "sku-1", "drop": 10000},
            "email": "secreto@example.test",
            "telegram_chat_id": "99",
        }
    )
    assert row["name"] == "Zapatilla"
    assert row["store"] == "falabella"
    assert row["price"] == 19990
    assert row["previous_price"] == 29990
    assert row["rule"] == "price_drop_percent"
    assert "Bajó" in row["rule_label"]
    assert row["channel"] is None
    assert row["product_id"] == "sku-1"
    blob = " ".join(str(value) for value in row.values())
    assert "secreto@example.test" not in blob
    assert "telegram" not in blob


def test_cron_batch_alerts_returns_the_run_count(monkeypatch):
    monkeypatch.setattr(
        "retail.web.settings_api.current_user",
        lambda *args, **kwargs: {"role": "admin", "id": "1"},
    )

    class Repo:
        def alerts_for_batch_run(self, run_id):
            assert run_id == "64b1"
            return {
                "run_id": "64b1",
                "grupo": "retail",
                "tienda": None,
                "started_at": "2026-09-16T09:00:04+00:00",
                "alert_count": 256,
                "total": 256,
                "truncated": False,
                "items": [
                    {
                        "id": "a1",
                        "name": "Polera",
                        "store": "falabella",
                        "price": 9990,
                        "previous_price": 14990,
                        "rule": "price_drop_percent",
                        "rule_label": "Bajó de precio (%)",
                        "channel": None,
                        "product_id": "p1",
                    }
                ],
            }

        def close(self):
            return None

    monkeypatch.setattr("retail.web.settings_api.connect_repo", lambda: Repo())
    monkeypatch.setattr(
        "retail.web.settings_api.list_stores",
        lambda: [type("S", (), {"id": "falabella", "title": "Falabella"})()],
    )
    response = TestClient(app).get("/api/admin/cron-batches/64b1/alerts")
    assert response.status_code == 200
    payload = response.json()
    assert payload["alert_count"] == 256
    assert payload["total"] == 256
    assert payload["items"][0]["store_title"] == "Falabella"
    assert payload["items"][0]["channel"] is None
