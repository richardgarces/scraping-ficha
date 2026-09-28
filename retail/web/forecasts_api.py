from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from retail.forecast_presentation import forecast_summary
from retail.search import connect_repo

router = APIRouter()


@router.get("/api/forecasts/{product_id}")
def get_forecasts(product_id: str, store: str | None = Query(default=None)):
    """Devuelve pronósticos guardados para un `product_id` (últimos 20)."""
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
        summary = forecast_summary(rows[0], (current or {}).get("price")) if rows else None
        if summary is None and not patterns:
            raise HTTPException(status_code=404, detail="No usable forecast found for product")
        return {
            "product_id": product_id, "store": store, "summary": summary,
            "forecasts": rows, "patterns": patterns,
        }
    finally:
        repo.close()
