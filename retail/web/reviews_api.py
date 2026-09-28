from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from retail.search import connect_repo
from retail.web.deps import current_user

router = APIRouter()


class ProductReviewInput(BaseModel):
    store: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=300)
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=600)

    @field_validator("store", "product_id")
    @classmethod
    def clean_key(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("Falta identificar el producto.")
        return clean

    @field_validator("comment")
    @classmethod
    def clean_comment(cls, value: str) -> str:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.strip().splitlines()]
        return "\n".join(line for line in lines if line)


def _repo_or_503():
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    return repo


def _ensure_product(repo, store: str, product_id: str) -> None:
    if repo.product_detail(store, product_id) is None:
        raise HTTPException(status_code=404, detail="No tenemos ese producto guardado.")


@router.get("/api/product-reviews")
def product_reviews(
    request: Request,
    store: str = Query(..., min_length=1, max_length=80),
    id: str = Query(..., min_length=1, max_length=300),
    limit: int = Query(default=3, ge=1, le=100),
    skip: int = Query(default=0, ge=0, le=10000),
) -> dict:
    repo = _repo_or_503()
    try:
        _ensure_product(repo, store, id)
        user = current_user(request, repo)
        user_id = str(user.get("id") or "") if user else None
        return repo.product_review_summary(store, id, user_id=user_id, limit=limit, skip=skip)
    finally:
        repo.close()


@router.post("/api/product-reviews")
def save_product_review(payload: ProductReviewInput, request: Request) -> dict:
    repo = _repo_or_503()
    try:
        user = current_user(
            request,
            repo,
            required=True,
            detail="Entra con tu cuenta para evaluar este producto.",
        )
        _ensure_product(repo, payload.store, payload.product_id)
        user_id = str(user.get("id") or "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Entra con tu cuenta para evaluar este producto.")
        review = repo.save_product_review(
            payload.store,
            payload.product_id,
            user_id,
            str(user.get("name") or "Usuario").strip() or "Usuario",
            payload.rating,
            payload.comment,
        )
        summary = repo.product_review_summary(
            payload.store,
            payload.product_id,
            user_id=user_id,
            limit=3,
        )
        return {"ok": True, "review": review, **summary}
    finally:
        repo.close()
