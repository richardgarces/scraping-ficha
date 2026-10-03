from types import SimpleNamespace

from fastapi.testclient import TestClient

from retail.auth import COOKIE, sign_session
from retail.web.app import app


def test_forecasts_api_requires_admin(anonymous_repo, monkeypatch):
    monkeypatch.setattr("retail.web.forecasts_api.connect_repo", lambda: anonymous_repo)
    client = TestClient(app)
    anonymous = client.get("/api/forecasts/sku-1", params={"store": "lider"})
    assert anonymous.status_code == 401

    user = {"id": "u1", "status": "approved", "role": "user"}
    anonymous_repo.find_user_by_id = lambda user_id: user
    anonymous_repo._public_user = lambda document: document
    client.cookies.set(COOKIE, sign_session("u1"))
    forbidden = client.get("/api/forecasts/sku-1", params={"store": "lider"})
    assert forbidden.status_code == 403


def test_forecasts_api_returns_404_for_admin_without_data(anonymous_repo, monkeypatch):
    monkeypatch.setattr(
        "retail.web.forecasts_api.current_user",
        lambda *args, **kwargs: {"role": "admin"},
    )

    class EmptyCursor:
        def sort(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def __iter__(self):
            return iter(())

    forecasts = SimpleNamespace(find=lambda *_a, **_k: EmptyCursor())
    collection = SimpleNamespace(find_one=lambda *_a, **_k: None)
    price_patterns = SimpleNamespace(find_one=lambda *_a, **_k: None)
    repo = SimpleNamespace(
        db=SimpleNamespace(get_collection=lambda _name: forecasts),
        collection=collection,
        price_patterns=price_patterns,
        close=lambda: None,
    )
    monkeypatch.setattr("retail.web.forecasts_api.connect_repo", lambda: repo)

    response = TestClient(app).get("/api/forecasts/sku-1", params={"store": "lider"})
    assert response.status_code == 404
