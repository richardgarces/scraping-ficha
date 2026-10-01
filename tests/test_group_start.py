from copy import deepcopy
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from retail.auth import COOKIE, sign_session
from retail.batch.group_scope import GroupBatchBusy, GroupBatchIdle, GroupBatchPaused
from retail.web import jobs
from retail.web.app import app


def test_start_group_requires_admin(anonymous_repo, monkeypatch):
    def forbidden_start(*args):
        pytest.fail("Una cuenta sin permisos no debe arrancar corridas")

    monkeypatch.setattr("retail.web.settings_api.start_group_batch", forbidden_start)
    client = TestClient(app)
    assert client.post("/api/admin/cron-batches/retail/start").status_code == 401
    user = {"id": "u1", "status": "approved", "role": "user"}
    anonymous_repo.find_user_by_id = lambda user_id: user
    anonymous_repo._public_user = lambda document: document
    client.cookies.set(COOKIE, sign_session("u1"))
    assert client.post("/api/admin/cron-batches/retail/start").status_code == 403


def test_start_group_api_accepts_only_the_selected_group(monkeypatch):
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})
    calls = []

    def start(group):
        calls.append(group)
        return {"ok": True, "running": True, "grupo": group, "run_id": "r1"}

    monkeypatch.setattr("retail.web.settings_api.start_group_batch", start)
    response = TestClient(app).post("/api/admin/cron-batches/farmacias/start")
    assert response.status_code == 202
    assert response.json()["grupo"] == "farmacias"
    assert calls == ["farmacias"]


@pytest.mark.parametrize("error,status", [
    (GroupBatchBusy("retail"), 409), (GroupBatchPaused(), 409),
    (ValueError("Grupo desconocido"), 400), (RuntimeError("Mongo offline"), 503),
])
def test_start_group_api_reports_failures(monkeypatch, error, status):
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})

    def start(group):
        raise error

    monkeypatch.setattr("retail.web.settings_api.start_group_batch", start)
    response = TestClient(app).post("/api/admin/cron-batches/retail/start")
    assert response.status_code == status
    assert response.json()["detail"]


def test_stop_group_api_targets_only_that_group(monkeypatch):
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})
    calls = []

    def stop(group):
        calls.append(group)
        return {"ok": True, "grupo": group, "message": "Deteniendo Farmacias. Las demás corridas siguen."}

    monkeypatch.setattr("retail.web.settings_api.stop_group_batch", stop)
    response = TestClient(app).post("/api/admin/cron-batches/farmacias/stop")
    assert response.status_code == 202
    assert calls == ["farmacias"]
    assert "Farmacias" in response.json()["message"]


def test_stop_group_api_requires_admin(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.settings_api.stop_group_batch", lambda group: pytest.fail(group))
    client = TestClient(app)
    assert client.post("/api/admin/cron-batches/retail/stop").status_code == 401


@pytest.mark.parametrize("error,status", [
    (GroupBatchIdle("retail"), 409),
    (ValueError("Grupo desconocido"), 400),
    (RuntimeError("Mongo offline"), 503),
])
def test_stop_group_api_reports_failures(monkeypatch, error, status):
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})

    def stop(group):
        raise error

    monkeypatch.setattr("retail.web.settings_api.stop_group_batch", stop)
    response = TestClient(app).post("/api/admin/cron-batches/retail/stop")
    assert response.status_code == status
    assert response.json()["detail"]


def test_pause_checkpoint_stops_only_the_flagged_run(monkeypatch):
    from retail.batch.config import wait_while_paused
    from retail.batch.group_scope import GroupBatchStopped

    monkeypatch.setattr("retail.batch.config.load_schedule", lambda repo: {"paused": True})
    flagged = SimpleNamespace(group_stop_requested=lambda run_id: run_id == "retail-run")
    with pytest.raises(GroupBatchStopped):
        wait_while_paused(flagged, "retail-run", poll_seconds=0.01)
    monkeypatch.setattr("retail.batch.config.load_schedule", lambda repo: {"paused": False})
    wait_while_paused(flagged, "farmacias-run", poll_seconds=0.01)


@pytest.fixture
def group_job(monkeypatch):
    schedule = {"source": "scrape", "pause": 0, "batch_budget_minutes": 45, "paused": False}
    runs, finished, threads, cursors = [], [], [], []
    repo = SimpleNamespace(
        close=lambda: None,
        start_batch_run=lambda doc: runs.append(doc) or "reserved-run",
        finish_batch_run=lambda run_id, **fields: finished.append((run_id, fields)),
        clear_group_batch_cursor=lambda group: cursors.append(("clear", group)),
        set_group_batch_cursor=lambda group, next_id: cursors.append(("set", group, next_id)),
        latest_group_batch_run=lambda group: {
            "status": "failed",
            "processed": 2,
            "searches": [{"id": "prod-a"}, {"id": "prod-resume"}],
        },
    )
    monkeypatch.setattr("retail.search.connect_repo", lambda: repo)
    monkeypatch.setattr("retail.batch.config.load_schedule", lambda store: schedule)
    monkeypatch.setattr("retail.store_categories.stores_for_group", lambda group, **kwargs: ["falabella", "paris"])
    monkeypatch.setattr("retail.store_categories.list_store_categories", lambda **kwargs: [{"id": "retail", "title": "Retail"}])

    class Thread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            threads.append(self)

        def start(self):
            # La corrida debe ser visible antes de iniciar el trabajo pesado.
            assert len(runs) == 1

    monkeypatch.setattr(jobs.threading, "Thread", Thread)
    return SimpleNamespace(
        schedule=schedule, runs=runs, finished=finished, threads=threads, cursors=cursors, repo=repo,
    )


def test_group_job_uses_saved_settings_and_reserves_before_start(group_job):
    original = deepcopy(group_job.schedule)
    result = jobs.start_group_batch(" RETAIL ")
    assert result["grupo"] == "retail"
    assert result["run_id"] == "reserved-run"
    assert group_job.runs[0]["scope"] == "grupo"
    assert group_job.runs[0]["phase"] == "starting"
    assert group_job.runs[0]["stores"] == ["falabella", "paris"]
    thread = group_job.threads[0].kwargs
    assert thread["args"] == ("retail", "reserved-run")
    assert thread["kwargs"] == {"source": "scrape", "pause": 0, "time_budget_minutes": 45, "persist": True}
    assert group_job.schedule == original


def test_paused_group_job_does_not_reserve_or_start(group_job):
    group_job.schedule["paused"] = True
    with pytest.raises(GroupBatchPaused):
        jobs.start_group_batch("retail")
    assert not group_job.runs
    assert not group_job.threads


def test_unknown_group_does_not_reserve_or_start(group_job):
    with pytest.raises(ValueError, match="Grupo desconocido"):
        jobs.start_group_batch("no-existe")
    assert not group_job.runs
    assert not group_job.threads


def test_group_job_without_stores_does_not_start(group_job, monkeypatch):
    monkeypatch.setattr("retail.store_categories.stores_for_group", lambda *a, **k: [])
    with pytest.raises(ValueError, match="no tiene tiendas"):
        jobs.start_group_batch("retail")
    assert not group_job.runs


def test_group_job_requires_database(monkeypatch):
    monkeypatch.setattr("retail.search.connect_repo", lambda: None)
    with pytest.raises(RuntimeError, match="MongoDB"):
        jobs.start_group_batch("retail")


@pytest.mark.parametrize("failure", ["create", "start"])
def test_group_job_releases_failed_worker_reservation(group_job, monkeypatch, failure):
    class BrokenThread:
        def __init__(self, **kwargs):
            if failure == "create":
                raise RuntimeError("No threads")

        def start(self):
            raise RuntimeError("No threads")

    monkeypatch.setattr(jobs.threading, "Thread", BrokenThread)
    with pytest.raises(RuntimeError, match="No se pudo iniciar"):
        jobs.start_group_batch("retail")
    assert group_job.finished[0][0] == "reserved-run"
    assert group_job.finished[0][1]["status"] == "failed"


def test_group_worker_marks_early_failure(group_job, monkeypatch):
    def fail(**kwargs):
        assert kwargs["grupo"] == "retail"
        assert kwargs["batch_run_id"] == "reserved-run"
        raise ValueError("Catálogo inválido")

    monkeypatch.setattr("retail.batch.runner.run_batch", fail)
    jobs._run_group("retail", "reserved-run", source="scrape")
    assert group_job.finished == [("reserved-run", {"status": "failed", "last_error": "Catálogo inválido"})]


def test_resume_product_id_prefers_current_then_last_search():
    from retail.batch.group_scope import resume_product_id

    assert resume_product_id({"current_id": "live", "searches": [{"id": "old"}]}) == "live"
    assert resume_product_id({"searches": [{"id": "a"}, {"id": "b"}]}) == "b"
    assert resume_product_id({"processed": 3, "searches": []}) is None
    assert resume_product_id(None) is None


def test_continue_places_cursor_on_last_progress(group_job):
    result = jobs.start_group_batch("retail", mode="continue")
    assert result["mode"] == "continue"
    assert "Continuando" in result["message"]
    assert group_job.cursors == [("set", "retail", "prod-resume")]
    assert group_job.runs[0]["resume_mode"] == "continue"


def test_restart_clears_cursor(group_job):
    result = jobs.start_group_batch("retail", mode="restart")
    assert result["mode"] == "restart"
    assert "Reiniciando" in result["message"]
    assert group_job.cursors == [("clear", "retail")]
    assert group_job.runs[0]["resume_mode"] == "restart"


def test_continue_without_progress_raises(group_job):
    from retail.batch.group_scope import GroupBatchNothingToResume

    group_job.repo.latest_group_batch_run = lambda group: {"status": "failed", "processed": 0, "searches": []}
    with pytest.raises(GroupBatchNothingToResume):
        jobs.start_group_batch("retail", mode="continue")
    assert not group_job.runs


def test_start_group_api_accepts_continue_mode(monkeypatch):
    monkeypatch.setattr("retail.web.settings_api.current_user", lambda *a, **k: {"role": "admin"})
    calls = []

    def start(group, mode=None):
        calls.append((group, mode))
        return {"ok": True, "running": True, "grupo": group, "mode": mode, "message": "ok"}

    monkeypatch.setattr("retail.web.settings_api.start_group_batch", start)
    response = TestClient(app).post(
        "/api/admin/cron-batches/retail/start",
        json={"mode": "continue"},
    )
    assert response.status_code == 202
    assert calls == [("retail", "continue")]
