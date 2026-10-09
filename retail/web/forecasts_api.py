from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from retail.forecast_outcomes import list_outcomes, outcome_stats, run_daily_outcome_pass
from retail.forecast_presentation import forecast_summary
from retail.search import connect_repo
from retail.web.deps import current_user

router = APIRouter()


@router.get("/api/forecasts/{product_id}")
def get_forecasts(request: Request, product_id: str, store: str | None = Query(default=None)):
    """Devuelve pronósticos guardados para un `product_id` (últimos 20). Solo admin."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        coll = repo.db.get_collection("forecasts")
        clean_id = str(product_id).strip()
        query = (
            {"forecast_key": f"{str(store).strip().lower()}:{clean_id}"}
            if store
            else {"$or": [{"product_id": clean_id}, {"source_document_id": clean_id}]}
        )
        cursor = coll.find(query).sort([("generated_at", -1), ("created_at", -1)]).limit(20)
        rows = []
        for item in cursor:
            item.pop("_id", None)
            # serializar datetimes a ISO si corresponde
            for k, v in list(item.items()):
                if hasattr(v, "isoformat"):
                    try:
                        item[k] = v.isoformat()
                    except Exception:
                        pass
            rows.append(item)
        current = repo.collection.find_one(
            {"store": str(store).strip().lower(), "product_id": clean_id},
            {"price": 1, "catalog_id": 1},
        ) if store else None
        pattern_doc = repo.price_patterns.find_one(
            {"product_key": f"{str(store).strip().lower()}:{clean_id}"},
            {"_id": 0, "patterns": 1, "updated_at": 1},
        ) if store else None
        patterns = list((pattern_doc or {}).get("patterns") or [])
        price_now = (current or {}).get("price")
        prefer = (
            "cyber_event_dense",
            "cyber_event_trend",
            "cyber_future_transfer",
            "timesfm",
            "last_value_baseline",
        )
        ranked = sorted(
            rows,
            key=lambda row: (
                prefer.index(str(row.get("model") or ""))
                if str(row.get("model") or "") in prefer
                else 99
            ),
        )
        summary = None
        future_summary = None
        for row in ranked:
            model = str(row.get("model") or "").lower()
            if model == "simulated":
                continue
            built = forecast_summary(row, price_now)
            if built is None:
                continue
            mode = str(built.get("mode") or "")
            if mode == "cyber_future" or model == "cyber_future_transfer":
                if future_summary is None:
                    future_summary = built
                continue
            if summary is None:
                summary = built
        if summary is None and future_summary is not None:
            summary = future_summary
        if summary is None and not patterns:
            raise HTTPException(status_code=404, detail="No usable forecast found for product")
        return {
            "product_id": product_id,
            "store": store,
            "summary": summary,
            "future_summary": future_summary,
            "forecasts": rows,
            "patterns": patterns,
        }
    finally:
        repo.close()


@router.get("/api/admin/forecast-outcomes")
def admin_forecast_outcomes(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=40, ge=1, le=100),
    status: str | None = Query(default=None),
    model: str | None = Query(default=None),
    q: str | None = Query(default=None),
):
    """Lista snapshots de pronósticos con estado de cumplimiento. Solo admin."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return list_outcomes(repo, page=page, size=size, status=status, model=model, q=q)
    finally:
        repo.close()


@router.get("/api/admin/forecast-outcomes/stats")
def admin_forecast_outcome_stats(request: Request):
    """Estadísticas agregadas de cumplimiento. Solo admin."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return outcome_stats(repo)
    finally:
        repo.close()


@router.post("/api/admin/forecast-outcomes/refresh")
def admin_forecast_outcomes_refresh(request: Request):
    """Backfill + evaluación on-demand (admin)."""
    current_user(request, admin=True)
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return run_daily_outcome_pass(repo)
    finally:
        repo.close()
