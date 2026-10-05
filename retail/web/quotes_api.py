"""Private purchasing pilot; imported references never modify retail prices."""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from retail.quotes import (MAX_SOURCE_BYTES, QuoteInput, QuoteLine, candidate_for,
                           comparison_report, parse_csv_quote, resolve_quote_status,
                           source_hash)
from retail.search import connect_repo
from retail.web.deps import current_user, require_login_html

def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_response)])


class CsvInput(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    supplier: str = Field(default="", max_length=150)
    source_name: str = Field(default="lista.csv", max_length=200)
    text: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    tax_included: bool | None = None


class Selection(BaseModel):
    index: int = Field(ge=0, lt=100)
    store: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=300)
    version: int = Field(ge=1)


class QuoteEdit(QuoteInput):
    version: int = Field(ge=1)


class PilotEvent(BaseModel):
    kind: Literal["useful", "needs_correction"]


def _repository():
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    return repo


def _owned(repo, user: dict, quote_id: str):
    quote = repo.db.business_quotes.find_one({"_id": quote_id, "owner_id": user["id"]})
    if not quote:
        raise HTTPException(status_code=404, detail="Cotización no encontrada.")
    return quote


def _public(quote):
    return {**{key: value for key, value in quote.items() if key not in {"_id", "owner_id"}}, "id": quote["_id"]}


def _record_event(repo, *, kind: str, user: dict, quote_id: str = "", detail: dict[str, Any] | None = None):
    repo.db.business_quote_events.insert_one({
        "_id": uuid.uuid4().hex,
        "kind": kind,
        "owner_id": user["id"],
        "quote_id": quote_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "detail": detail or {},
    })


def _report(repo, quote):
    selections = quote.get("selections") or {}
    documents = {}
    for selection in selections.values():
        key = selection["store"], selection["product_id"]
        if key not in documents:
            doc = repo.product_detail(*key)
            if doc:
                documents[key] = doc
    return comparison_report(quote, selections, documents)


def _apply_status(repo, quote, report):
    status = resolve_quote_status(quote, report)
    if quote.get("status") != status:
        repo.db.business_quotes.update_one(
            {"_id": quote["_id"], "owner_id": quote["owner_id"]},
            {"$set": {"status": status}},
        )
        quote["status"] = status
    report["summary"]["status"] = status
    report["summary"]["status_label"] = {
        "draft": "Borrador", "review": "Revisión", "compared": "Comparada", "exported": "Exportada",
    }[status]
    return quote, report


def _create(repo, user, payload: QuoteInput, *, event_kind: str = "import"):
    if repo.db.business_quotes.count_documents({"owner_id": user["id"]}, limit=201) >= 200:
        raise HTTPException(status_code=409, detail="El piloto admite hasta 200 cotizaciones por cuenta.")
    document = payload.model_dump(mode="json")
    document.update(
        _id=uuid.uuid4().hex,
        owner_id=user["id"],
        version=1,
        status="draft",
        created_at=datetime.now(timezone.utc).isoformat(),
        selections={},
    )
    repo.db.business_quotes.insert_one(document)
    _record_event(repo, kind=event_kind, user=user, quote_id=document["_id"],
                  detail={"items": len(document["items"]), "source_kind": document.get("source_kind")})
    return _public(document)


@router.get("/cotizaciones", include_in_schema=False)
def quotes_page(request: Request):
    gate = require_login_html(request, next_path="/cotizaciones")
    if gate is not None:
        return gate
    from retail.web.app import STATIC
    return FileResponse(STATIC / "cotizaciones.html", headers={"Cache-Control": "no-store"})


@router.post("/api/quotes", status_code=201)
def create_quote(request: Request, payload: QuoteInput):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        try:
            return _create(repo, user, payload, event_kind="import")
        except HTTPException:
            raise
        except Exception as exc:
            _record_event(repo, kind="error", user=user, detail={"where": "import_json", "message": str(exc)[:300]})
            raise
    finally:
        repo.close()


@router.post("/api/quotes/import-csv", status_code=201)
def import_csv(request: Request, payload: CsvInput):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        try:
            items = parse_csv_quote(payload.text, payload.source_name)
            quote = QuoteInput(title=payload.title, supplier=payload.supplier,
                               source_name=payload.source_name, source_kind="csv",
                               source_sha256=source_hash(payload.text), tax_included=payload.tax_included,
                               items=items)
            return _create(repo, user, quote, event_kind="import")
        except ValueError as exc:
            _record_event(repo, kind="error", user=user, detail={"where": "import_csv", "message": str(exc)[:300]})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        repo.close()


@router.get("/api/quotes")
def list_quotes(request: Request):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        quotes = []
        for row in repo.db.business_quotes.find(
            {"owner_id": user["id"]}, {"items": 0, "selections": 0},
        ).sort("created_at", -1).limit(50):
            public = _public(row)
            public["status"] = row.get("status") or resolve_quote_status(row)
            quotes.append(public)
        return {"quotes": quotes}
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}")
def get_quote(request: Request, quote_id: str):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}/candidates/{index}")
def get_candidates(request: Request, quote_id: str, index: int):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        quote = _owned(repo, user, quote_id)
        if not 0 <= index < len(quote["items"]):
            raise HTTPException(status_code=404, detail="Producto no encontrado.")
        line = QuoteLine.model_validate(quote["items"][index])
        queries = [line.name]
        if line.gtin:
            queries.insert(0, line.gtin)
        words = [word for word in re.findall(r"[\w+-]+", line.name) if len(word) >= 3]
        queries.extend(words[:2])
        documents = {}
        for query in queries[:4]:
            for doc in repo.find_by_query(query, limit=100):
                documents[(doc.get("store"), doc.get("product_id"))] = doc
        rows = [candidate for doc in documents.values() if (candidate := candidate_for(line, doc))]
        rows.sort(key=lambda row: (not row["usable"], -row["confidence"], row["price"]))
        return {"candidates": rows[:20], "review_required": True}
    finally:
        repo.close()


@router.put("/api/quotes/{quote_id}")
def edit_quote(request: Request, quote_id: str, payload: QuoteEdit):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        _owned(repo, user, quote_id)
        values = payload.model_dump(mode="json", exclude={"version"})
        values.update(selections={}, updated_at=datetime.now(timezone.utc).isoformat(),
                      status="review", exported_at=None)
        result = repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"], "version": payload.version},
            {"$set": values, "$inc": {"version": 1}},
        )
        if not result.matched_count:
            raise HTTPException(status_code=409, detail="La cotización cambió. Recárgala antes de guardar.")
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        _record_event(repo, kind="review", user=user, quote_id=quote_id,
                      detail={"items": len(quote["items"])})
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.put("/api/quotes/{quote_id}/selection")
def select_candidate(request: Request, quote_id: str, payload: Selection):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        quote = _owned(repo, user, quote_id)
        if payload.index >= len(quote["items"]):
            raise HTTPException(status_code=404, detail="Producto no encontrado.")
        doc = repo.product_detail(payload.store, payload.product_id)
        line = QuoteLine.model_validate(quote["items"][payload.index])
        if not doc or not candidate_for(line, doc):
            raise HTTPException(status_code=422, detail="La variante no es compatible con el producto solicitado.")
        result = repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"], "version": payload.version},
            {"$set": {f"selections.{payload.index}": {"store": payload.store, "product_id": payload.product_id},
                      "updated_at": datetime.now(timezone.utc).isoformat()}, "$inc": {"version": 1}},
        )
        if not result.matched_count:
            raise HTTPException(status_code=409, detail="La cotización cambió. Recárgala antes de confirmar.")
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        _record_event(repo, kind="confirm", user=user, quote_id=quote_id, detail={
            "index": payload.index, "store": payload.store, "product_id": payload.product_id,
            "confirmed_items": report["summary"]["confirmed_items"],
            "compared_items": report["summary"]["compared_items"],
            "potential_saving": report["summary"]["potential_saving"],
            "status": quote["status"],
        })
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}/export.csv")
def export_quote(request: Request, quote_id: str):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        quote = _owned(repo, user, quote_id)
        report = _report(repo, quote)
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(["Producto", "Cantidad", "Referencia CLP", "Mercado CLP", "Diferencia sin despacho CLP",
                         "Tienda", "Estado", "Revisión", "Evidencia"])
        for row in report["rows"]:
            selected = row["selected"] or {}
            evidence = row["item"].get("evidence") or {}
            values = [row["item"]["name"], row["item"]["quantity"], row["reference_subtotal"],
                      row["market_subtotal"], row["potential_saving"], selected.get("store", ""),
                      report["summary"]["status_label"],
                      " | ".join(row["issues"]), f"{evidence.get('source', '')} fila {evidence.get('row', '')}"]
            writer.writerow([("'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value)
                             if isinstance(value, str) else value for value in values])
        exported_at = datetime.now(timezone.utc).isoformat()
        quote["exported_at"] = exported_at
        quote, report = _apply_status(repo, quote, report)
        repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"]},
            {"$set": {"exported_at": exported_at, "status": quote["status"]}},
        )
        _record_event(repo, kind="export", user=user, quote_id=quote_id, detail={
            "compared_items": report["summary"]["compared_items"],
            "potential_saving": report["summary"]["potential_saving"],
            "complete": report["summary"]["complete"],
            "status": quote["status"],
        })
        return Response("\ufeff" + output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="cotizacion-{quote_id}.csv"',
                                 "Cache-Control": "no-store"})
    finally:
        repo.close()


@router.post("/api/quotes/{quote_id}/feedback")
def quote_feedback(request: Request, quote_id: str, payload: PilotEvent):
    repo = _repository()
    try:
        user = current_user(request, repo, required=True)
        _owned(repo, user, quote_id)
        repo.db.business_quotes.update_one({"_id": quote_id, "owner_id": user["id"]},
                                          {"$set": {"feedback": payload.kind}})
        _record_event(repo, kind="feedback", user=user, quote_id=quote_id, detail={"kind": payload.kind})
        return {"ok": True}
    finally:
        repo.close()


@router.get("/api/admin/purchasing-metrics")
def purchasing_metrics(request: Request):
    repo = _repository()
    try:
        current_user(request, repo, admin=True)
        quotes = repo.db.business_quotes
        events = repo.db.business_quote_events

        def event_count(kind: str) -> int:
            return events.count_documents({"kind": kind})

        export_saving = 0
        for event in events.find({"kind": "export"}, {"detail": 1}):
            detail = event.get("detail") or {}
            if isinstance(detail.get("potential_saving"), (int, float)):
                export_saving += int(detail["potential_saving"])
        matches = event_count("confirm")
        return {
            "created_quotes": quotes.count_documents({}),
            "imports": event_count("import"),
            "reviewed_quotes": quotes.count_documents({"status": {"$in": ["review", "compared", "exported"]}}),
            "compared_quotes": quotes.count_documents({"status": {"$in": ["compared", "exported"]}}),
            "exported_quotes": quotes.count_documents({"status": "exported"}),
            "confirmed_rows": matches,
            "matches": matches,
            "exports": event_count("export"),
            "errors": event_count("error"),
            "potential_saving_exported": export_saving,
            "useful_quotes": quotes.count_documents({"feedback": "useful"}),
            "needs_correction_quotes": quotes.count_documents({"feedback": "needs_correction"}),
            "note": "No mide ventas ni ahorro realizado. El ahorro potencial exportado suma las exportaciones registradas.",
        }
    finally:
        repo.close()
