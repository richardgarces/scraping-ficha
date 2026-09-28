from fastapi import HTTPException
from fastapi.testclient import TestClient

from retail.web.app import app
from retail.web.reviews_api import ProductReviewInput


class FakeReviewRepo:
    def __init__(self, *, product=True):
        self.product = product
        self.closed = False
        self.saved = None

    def product_detail(self, store, product_id):
        return {"store": store, "product_id": product_id} if self.product else None

    def product_review_summary(self, store, product_id, **kwargs):
        return {
            "average": 4.5,
            "count": 2,
            "comment_count": 1,
            "reviews": [{"rating": 5, "comment": "Muy bueno", "author": "Ana"}],
            "mine": None,
            "args": kwargs,
        }

    def save_product_review(self, store, product_id, user_id, author, rating, comment):
        self.saved = (store, product_id, user_id, author, rating, comment)
        return {"rating": rating, "comment": comment, "author": author, "mine": True}

    def close(self):
        self.closed = True


def test_review_input_is_trimmed_and_rating_is_bounded():
    payload = ProductReviewInput(store=" falabella ", product_id=" sku-1 ", rating=5, comment=" Muy   bueno \n\n Lo recomiendo ")
    assert payload.store == "falabella"
    assert payload.product_id == "sku-1"
    assert payload.comment == "Muy bueno\nLo recomiendo"


def test_public_product_reviews_include_latest_comments(monkeypatch):
    repo = FakeReviewRepo()
    monkeypatch.setattr("retail.web.reviews_api._repo_or_503", lambda: repo)
    monkeypatch.setattr("retail.web.reviews_api.current_user", lambda request, store: None)

    response = TestClient(app).get("/api/product-reviews", params={"store": "falabella", "id": "sku-1"})

    assert response.status_code == 200
    assert response.json()["reviews"][0]["comment"] == "Muy bueno"
    assert response.json()["count"] == 2
    assert repo.closed is True


def test_logged_user_can_publish_or_update_one_review(monkeypatch):
    repo = FakeReviewRepo()
    monkeypatch.setattr("retail.web.reviews_api._repo_or_503", lambda: repo)
    monkeypatch.setattr(
        "retail.web.reviews_api.current_user",
        lambda request, store, **kwargs: {"id": "user-1", "name": "Ana"},
    )

    response = TestClient(app).post(
        "/api/product-reviews",
        json={"store": "falabella", "product_id": "sku-1", "rating": 4, "comment": "Cumple bien"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert repo.saved == ("falabella", "sku-1", "user-1", "Ana", 4, "Cumple bien")
    assert repo.closed is True


def test_review_requires_login_and_existing_product(monkeypatch):
    repo = FakeReviewRepo()
    monkeypatch.setattr("retail.web.reviews_api._repo_or_503", lambda: repo)

    def reject(*args, **kwargs):
        raise HTTPException(status_code=401, detail="Entra con tu cuenta para evaluar este producto.")

    monkeypatch.setattr("retail.web.reviews_api.current_user", reject)
    response = TestClient(app).post(
        "/api/product-reviews",
        json={"store": "falabella", "product_id": "sku-1", "rating": 4},
    )
    assert response.status_code == 401

    missing = FakeReviewRepo(product=False)
    monkeypatch.setattr("retail.web.reviews_api._repo_or_503", lambda: missing)
    monkeypatch.setattr(
        "retail.web.reviews_api.current_user",
        lambda request, store, **kwargs: {"id": "user-1", "name": "Ana"},
    )
    response = TestClient(app).post(
        "/api/product-reviews",
        json={"store": "falabella", "product_id": "missing", "rating": 4},
    )
    assert response.status_code == 404
