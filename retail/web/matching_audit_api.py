from __future__ import annotations

import csv
import io
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from retail.matching_audit import (
    arbitrate_matching_item,
    create_matching_audit_run,
    matching_audit_status,
    matching_audit_csv_rows,
    matching_audit_metrics,
    record_matching_review,
)
from retail.web.deps import current_user, repo_or_503

router = APIRouter()

_LABEL_NAMES = {
    "exact": "exacta",
    "variant": "variante",
    "not_equivalent": "no equivalente",
    "uncertain": "incierta",
}


def _run_id(raw: str) -> ObjectId:
    try:
        return ObjectId(raw)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Identificador de auditoría inválido.") from exc


def _admin(request: Request, repo: Any) -> dict[str, Any]:
    user = current_user(request, repo, required=True, admin=True) or {}
    if not matching_audit_status(repo)["enabled"]:
        raise HTTPException(status_code=404, detail="La auditoría de matching está desactivada.")
    return user


def _public_item(item: dict[str, Any]) -> dict[str, Any]:
    item["id"] = str(item.pop("_id"))
    item["run_id"] = str(item.get("run_id") or "")
    item["search_id"] = str(item.get("search_id") or "")
    for private_field in ("reviewer_ids", "arbitrator_id", "arbitration_note"):
        item.pop(private_field, None)
    return item


def _raise_audit_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.post("/api/admin/matching-audit/runs", status_code=201)
async def matching_audit_create_run(request: Request) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        user = _admin(request, repo)
        body = await request.json()
        raw_seed = body.get("seed") if isinstance(body, dict) else None
        try:
            seed = int(raw_seed) if raw_seed not in (None, "") else None
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="La semilla debe ser un entero.") from exc
        result = create_matching_audit_run(
            repo,
            created_by=str(user.get("id") or user.get("email") or "admin"),
            seed=seed,
        )
        return result
    finally:
        repo.close()


@router.get("/api/admin/matching-audit/runs")
def matching_audit_runs(
    request: Request, limit: int = Query(default=20, ge=1, le=50)
) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        _admin(request, repo)
        rows = list(
            repo.matching_audit_runs.find({}, {
                "created_by": 1, "created_at": 1, "status": 1, "seed": 1,
                "search_window_days": 1, "sampled_search_count": 1,
                "comparison_count": 1, "eligible_query_count": 1,
            }).sort("created_at", -1).limit(limit)
        )
        for row in rows:
            row["id"] = str(row.pop("_id"))
        return {"runs": rows}
    finally:
        repo.close()


@router.get("/api/admin/matching-audit/runs/{run_id}/metrics")
def matching_audit_run_metrics(request: Request, run_id: str) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        _admin(request, repo)
        ident = _run_id(run_id)
        run = repo.matching_audit_runs.find_one({"_id": ident})
        if not run:
            raise HTTPException(status_code=404, detail="Auditoría no encontrada.")
        return {
            "run": {
                "id": str(ident),
                "status": run.get("status"),
                "created_at": run.get("created_at"),
                "sampled_search_count": run.get("sampled_search_count", 0),
                "comparison_count": run.get("comparison_count", 0),
                "strata_allocations": run.get("strata_allocations", {}),
            },
            "metrics": matching_audit_metrics(repo, ident),
        }
    finally:
        repo.close()


@router.get("/api/admin/matching-audit/runs/{run_id}/review-queue")
def matching_audit_review_queue(
    request: Request, run_id: str, limit: int = Query(default=25, ge=1, le=50)
) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        user = _admin(request, repo)
        ident = _run_id(run_id)
        run = repo.matching_audit_runs.find_one({"_id": ident})
        if not run:
            raise HTTPException(status_code=404, detail="Auditoría no encontrada.")
        reviewer = str(user.get("id") or user.get("email") or "").strip()
        items = list(repo.matching_audit_items.find(
            {
                "run_id": ident,
                "status": {"$in": ["awaiting_reviews", "awaiting_second_review"]},
                "reviewer_ids": {"$ne": reviewer},
            }
        ).sort([("category", 1), ("store", 1), ("search_id", 1), ("position", 1)]).limit(limit))
        return {"items": [_public_item(item) for item in items]}
    finally:
        repo.close()


@router.post("/api/admin/matching-audit/runs/{run_id}/items/{item_id}/reviews")
async def matching_audit_review(
    request: Request, run_id: str, item_id: str
) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        user = _admin(request, repo)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Datos de revisión inválidos.")
        result = record_matching_review(
            repo,
            run_id=run_id,
            item_id=item_id,
            reviewer_id=str(user.get("id") or user.get("email") or ""),
            label=str(body.get("label") or ""),
            note=str(body.get("note") or ""),
        )
        return result
    except (ValueError, LookupError) as exc:
        _raise_audit_error(exc)
    finally:
        repo.close()


@router.get("/api/admin/matching-audit/runs/{run_id}/arbitration")
def matching_audit_disagreements(
    request: Request, run_id: str, limit: int = Query(default=50, ge=1, le=100)
) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        _admin(request, repo)
        ident = _run_id(run_id)
        if not repo.matching_audit_runs.find_one({"_id": ident}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Auditoría no encontrada.")
        items = list(repo.matching_audit_items.find(
            {"run_id": ident, "status": "disagreement"}
        ).sort([("category", 1), ("store", 1)]).limit(limit))
        reviews_by_item: dict[ObjectId, list[dict[str, Any]]] = {}
        if items:
            item_ids = [item["_id"] for item in items]
            for review in repo.matching_audit_reviews.find(
                {"run_id": ident, "item_id": {"$in": item_ids}}
            ).sort("created_at", 1):
                reviews_by_item.setdefault(review["item_id"], []).append(review)
        result = []
        for item in items:
            shaped = _public_item(item)
            shaped["reviews"] = [
                {
                    "reviewer_id": review.get("reviewer_id"),
                    "label": review.get("label"),
                    "label_name": _LABEL_NAMES.get(review.get("label"), "—"),
                    "note": review.get("note", ""),
                    "created_at": review.get("created_at"),
                }
                for review in reviews_by_item.get(ObjectId(shaped["id"]), [])
            ]
            result.append(shaped)
        return {"items": result}
    finally:
        repo.close()


@router.post("/api/admin/matching-audit/runs/{run_id}/items/{item_id}/arbitration")
async def matching_audit_arbitrate(
    request: Request, run_id: str, item_id: str
) -> dict[str, Any]:
    repo = repo_or_503()
    try:
        user = _admin(request, repo)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Datos de arbitraje inválidos.")
        return arbitrate_matching_item(
            repo,
            run_id=run_id,
            item_id=item_id,
            arbitrator_id=str(user.get("id") or user.get("email") or ""),
            label=str(body.get("label") or ""),
            note=str(body.get("note") or ""),
        )
    except (ValueError, LookupError) as exc:
        _raise_audit_error(exc)
    finally:
        repo.close()


@router.get("/api/admin/matching-audit/runs/{run_id}/export.csv")
def matching_audit_export_csv(request: Request, run_id: str) -> Response:
    repo = repo_or_503()
    try:
        _admin(request, repo)
        ident = _run_id(run_id)
        if not repo.matching_audit_runs.find_one({"_id": ident}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Auditoría no encontrada.")
        rows = matching_audit_csv_rows(repo, ident)
        output = io.StringIO(newline="")
        headers = list(rows[0]) if rows else [
            "search_id", "query", "category", "store", "frequency_count_30d",
            "frequency_bucket", "offer_id", "offer_name", "offer_url",
            "offer_price_all_payment", "offer_price_card",
            "offer_payment_conditions", "offer_shipping_cost", "offer_updated_at",
            "reviewer_1", "label_1", "note_1", "reviewer_2", "label_2",
            "note_2", "final_label", "arbitrator", "arbitration_note",
        ]
        writer = csv.DictWriter(output, fieldnames=headers, delimiter=";", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            safe = {}
            for key, value in row.items():
                text = str(value if value is not None else "")
                if text.lstrip().startswith(("=", "+", "-", "@")):
                    text = "'" + text
                safe[key] = text
            writer.writerow(safe)
        return Response(
            "\ufeff" + output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="matching-audit-{ident}.csv"'},
        )
    finally:
        repo.close()
