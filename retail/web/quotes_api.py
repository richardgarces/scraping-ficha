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
from retail.shopping_list import (MODE_SHOPPING_LIST, available_store_groups,
                                  build_store_matches, is_shopping_list,
                                  matrix_export_csv, refresh_quote_prices,
                                  resolve_list_stores, shopping_matrix_report)
from retail.web.deps import current_user, require_admin_html

def private_response(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(dependencies=[Depends(private_response)])


class CsvInput(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    supplier: str = Field(default="", max_length=150)
    source_name: str = Field(default="lista.csv", max_length=200)
    text: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES)
    tax_included: bool | None = None
    mode: Literal["quote", "shopping_list"] = "quote"
    store_group: str = Field(default="", max_length=80)
    store_ids: list[str] = Field(default_factory=list, max_length=50)


class Selection(BaseModel):
    index: int = Field(ge=0, lt=100)
    store: str = Field(min_length=1, max_length=80)
    product_id: str = Field(min_length=1, max_length=300)
    version: int = Field(ge=1)
    confirm: bool = True


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


def _load_documents(repo, keys: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    documents = {}
    for key in keys:
        if key in documents or not key[0] or not key[1]:
            continue
        doc = repo.product_detail(*key)
        if doc:
            documents[key] = doc
    return documents


def _report(repo, quote):
    if is_shopping_list(quote):
        store_matches = quote.get("store_matches") or {}
        keys = []
        for per_store in store_matches.values():
            for selection in (per_store or {}).values():
                if not isinstance(selection, dict):
                    continue
                store = str(selection.get("store") or "").strip()
                product_id = str(selection.get("product_id") or "").strip()
                if store and product_id:
                    keys.append((store, product_id))
        stores = quote.get("resolved_stores") or resolve_list_stores(quote, repo=repo)
        documents = _load_documents(repo, keys)
        return shopping_matrix_report(quote, store_matches, documents, stores=stores)
    selections = quote.get("selections") or {}
    keys = [(selection["store"], selection["product_id"]) for selection in selections.values()]
    documents = _load_documents(repo, keys)
    return comparison_report(quote, selections, documents)


def _apply_status(repo, quote, report):
    if is_shopping_list(quote):
        status = report["summary"].get("status") or "draft"
        if quote.get("exported_at") and report["summary"].get("complete"):
            status = "exported"
            report["summary"]["status"] = status
            report["summary"]["status_label"] = "Exportada"
    else:
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
    }.get(status, report["summary"].get("status_label") or status)
    return quote, report


def _create(repo, user, payload: QuoteInput, *, event_kind: str = "import"):
    if repo.db.business_quotes.count_documents({"owner_id": user["id"]}, limit=201) >= 200:
        raise HTTPException(status_code=409, detail="El piloto admite hasta 200 cotizaciones por cuenta.")
    document = payload.model_dump(mode="json")
    if document.get("mode") == MODE_SHOPPING_LIST:
        if not document.get("store_group") and not document.get("store_ids"):
            raise HTTPException(status_code=422, detail="Elige una categoría de tiendas para la lista de compra.")
        # IVA / precio de referencia no son obligatorios en este modo.
        document.setdefault("tax_included", True)
    document.update(
        _id=uuid.uuid4().hex,
        owner_id=user["id"],
        version=1,
        status="draft",
        created_at=datetime.now(timezone.utc).isoformat(),
        selections={},
        store_matches={},
        resolved_stores=[],
    )
    if document.get("mode") == MODE_SHOPPING_LIST:
        try:
            stores = resolve_list_stores(document, repo=repo)
            document["resolved_stores"] = stores
            document["store_matches"] = build_store_matches(repo, document)
            report = _report(repo, document)
            document["status"] = report["summary"].get("status") or "review"
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    repo.db.business_quotes.insert_one(document)
    _record_event(repo, kind=event_kind, user=user, quote_id=document["_id"],
                  detail={"items": len(document["items"]), "source_kind": document.get("source_kind"),
                          "mode": document.get("mode"), "store_group": document.get("store_group")})
    return _public(document)


@router.get("/cotizaciones", include_in_schema=False)
def quotes_page(request: Request):
    gate = require_admin_html(request, next_path="/cotizaciones")
    if gate is not None:
        return gate
    from retail.web.app import STATIC
    return FileResponse(STATIC / "cotizaciones.html", headers={"Cache-Control": "no-store"})


@router.post("/api/quotes", status_code=201)
def create_quote(request: Request, payload: QuoteInput):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
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
        user = current_user(request, repo, admin=True)
        try:
            items = parse_csv_quote(payload.text, payload.source_name)
            if payload.mode == MODE_SHOPPING_LIST:
                tax = True if payload.tax_included is None else payload.tax_included
            else:
                tax = payload.tax_included
            quote = QuoteInput(
                title=payload.title,
                supplier=payload.supplier,
                source_name=payload.source_name,
                source_kind="csv",
                source_sha256=source_hash(payload.text),
                tax_included=tax,
                mode=payload.mode,
                store_group=payload.store_group,
                store_ids=payload.store_ids,
                items=items,
            )
            return _create(repo, user, quote, event_kind="import")
        except ValueError as exc:
            _record_event(repo, kind="error", user=user, detail={"where": "import_csv", "message": str(exc)[:300]})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        repo.close()


@router.get("/api/quotes/store-groups")
def quote_store_groups(request: Request):
    """Categorías de tiendas disponibles para el modo lista de compra."""
    repo = _repository()
    try:
        current_user(request, repo, admin=True)
        return {"groups": available_store_groups(repo=repo)}
    finally:
        repo.close()


@router.post("/api/quotes/{quote_id}/rebuild-matrix")
def rebuild_matrix(request: Request, quote_id: str):
    """Vuelve a buscar matches por tienda desde el catálogo Mongo actual."""
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        quote = _owned(repo, user, quote_id)
        if not is_shopping_list(quote):
            raise HTTPException(status_code=422, detail="Solo aplica al modo lista de compra.")
        version = int(quote.get("version") or 1)
        try:
            stores = resolve_list_stores(quote, repo=repo)
            matches = build_store_matches(repo, quote)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"], "version": version},
            {"$set": {
                "store_matches": matches,
                "resolved_stores": stores,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, "$inc": {"version": 1}},
        )
        if not result.matched_count:
            raise HTTPException(status_code=409, detail="La lista cambió. Recárgala antes de regenerar.")
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        _record_event(repo, kind="rebuild_matrix", user=user, quote_id=quote_id,
                      detail={"matched_cells": report["summary"].get("matched_cells"),
                              "stores": stores})
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.post("/api/quotes/{quote_id}/refresh-prices")
def refresh_prices(request: Request, quote_id: str):
    """Sube prioridad de scrape de los SKUs matcheados (sin scrapear en la petición)."""
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        quote = _owned(repo, user, quote_id)
        result = refresh_quote_prices(repo, quote)
        _record_event(
            repo,
            kind="refresh_prices",
            user=user,
            quote_id=quote_id,
            detail={
                "boosted": result.get("boosted"),
                "following": result.get("following"),
                "targets": result.get("targets"),
            },
        )
        return {"ok": True, **result}
    finally:
        repo.close()


@router.get("/api/quotes")
def list_quotes(request: Request):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
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


@router.post("/api/quotes/convert-jobs", status_code=201)
async def enqueue_docling_job(request: Request):
    """Encola conversión PDF/imagen fuera de la petición (worker Docling)."""
    from retail.quote_docling_jobs import enqueue_conversion

    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=400, detail="Adjunta un PDF, imagen o JSON Docling.")
        raw = await upload.read()
        title = str(form.get("title") or getattr(upload, "filename", None) or "Cotización")
        supplier = str(form.get("supplier") or "")
        tax_raw = form.get("tax_included")
        tax_included = True if str(tax_raw).lower() in {"1", "true", "on", "yes"} else None
        valid_until = str(form.get("valid_until") or "") or None
        try:
            job = enqueue_conversion(
                repo,
                owner_id=user["id"],
                title=title,
                supplier=supplier,
                source_name=str(getattr(upload, "filename", None) or "documento.pdf"),
                raw_bytes=raw,
                tax_included=tax_included,
                valid_until=valid_until,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        _record_event(repo, kind="docling_enqueue", user=user, detail={"job_id": job["id"], "status": job["status"]})
        return job
    finally:
        repo.close()


@router.get("/api/quotes/convert-jobs/{job_id}")
def docling_job_status(request: Request, job_id: str):
    from retail.quote_docling_jobs import get_job

    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        job = get_job(repo, job_id, owner_id=user["id"])
        if not job:
            raise HTTPException(status_code=404, detail="Conversión no encontrada.")
        return job
    finally:
        repo.close()


@router.post("/api/quotes/convert-jobs/{job_id}/import", status_code=201)
def import_docling_job_result(request: Request, job_id: str):
    """Carga el JSON resultante del job en una cotización revisable."""
    from retail.quote_docling_jobs import load_result_json
    from retail.quotes import QuoteInput

    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        try:
            payload = load_result_json(repo, job_id, owner_id=user["id"])
            quote = QuoteInput.model_validate(payload)
            created = _create(repo, user, quote, event_kind="import")
            _record_event(repo, kind="docling_import", user=user, quote_id=created["id"], detail={"job_id": job_id})
            return created
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}")
def get_quote(request: Request, quote_id: str):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}/candidates/{index}")
def get_candidates(request: Request, quote_id: str, index: int, store: str | None = None):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
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
        wanted = (store or "").strip().lower()
        rows = []
        for doc in documents.values():
            if wanted and str(doc.get("store") or "").lower() != wanted:
                continue
            candidate = candidate_for(line, doc)
            if candidate:
                rows.append(candidate)
        rows.sort(key=lambda row: (not row["usable"], -row["confidence"], row["price"]))
        return {"candidates": rows[:20], "review_required": True, "store": wanted or None}
    finally:
        repo.close()


@router.put("/api/quotes/{quote_id}")
def edit_quote(request: Request, quote_id: str, payload: QuoteEdit):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        existing = _owned(repo, user, quote_id)
        values = payload.model_dump(mode="json", exclude={"version"})
        values.update(selections={}, store_matches={}, updated_at=datetime.now(timezone.utc).isoformat(),
                      status="review", exported_at=None)
        if values.get("mode") == MODE_SHOPPING_LIST or is_shopping_list(existing):
            values["mode"] = MODE_SHOPPING_LIST
            try:
                values["resolved_stores"] = resolve_list_stores(values, repo=repo)
                values["store_matches"] = build_store_matches(repo, {**existing, **values})
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"], "version": payload.version},
            {"$set": values, "$inc": {"version": 1}},
        )
        if not result.matched_count:
            raise HTTPException(status_code=409, detail="La cotización cambió. Recárgala antes de guardar.")
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        _record_event(repo, kind="review", user=user, quote_id=quote_id,
                      detail={"items": len(quote["items"]), "mode": quote.get("mode")})
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.put("/api/quotes/{quote_id}/selection")
def select_candidate(request: Request, quote_id: str, payload: Selection):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        quote = _owned(repo, user, quote_id)
        if payload.index >= len(quote["items"]):
            raise HTTPException(status_code=404, detail="Producto no encontrado.")
        doc = repo.product_detail(payload.store, payload.product_id)
        line = QuoteLine.model_validate(quote["items"][payload.index])
        if not doc or not candidate_for(line, doc):
            raise HTTPException(status_code=422, detail="La variante no es compatible con el producto solicitado.")
        if is_shopping_list(quote):
            allowed = set(quote.get("resolved_stores") or resolve_list_stores(quote, repo=repo))
            if payload.store not in allowed:
                raise HTTPException(status_code=422, detail="La tienda no pertenece al set de la lista.")
            result = repo.db.business_quotes.update_one(
                {"_id": quote_id, "owner_id": user["id"], "version": payload.version},
                {"$set": {
                    f"store_matches.{payload.index}.{payload.store}": {
                        "store": payload.store,
                        "product_id": payload.product_id,
                        "auto": False,
                        "confirmed": payload.confirm,
                    },
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, "$inc": {"version": 1}},
            )
        else:
            result = repo.db.business_quotes.update_one(
                {"_id": quote_id, "owner_id": user["id"], "version": payload.version},
                {"$set": {f"selections.{payload.index}": {"store": payload.store, "product_id": payload.product_id},
                          "updated_at": datetime.now(timezone.utc).isoformat()}, "$inc": {"version": 1}},
            )
        if not result.matched_count:
            raise HTTPException(status_code=409, detail="La cotización cambió. Recárgala antes de confirmar.")
        quote = _owned(repo, user, quote_id)
        quote, report = _apply_status(repo, quote, _report(repo, quote))
        detail = {
            "index": payload.index, "store": payload.store, "product_id": payload.product_id,
            "mode": quote.get("mode"), "status": quote["status"],
        }
        if is_shopping_list(quote):
            detail["matched_cells"] = report["summary"].get("matched_cells")
            detail["confirmed_cells"] = report["summary"].get("confirmed_cells")
        else:
            detail.update({
                "confirmed_items": report["summary"]["confirmed_items"],
                "compared_items": report["summary"]["compared_items"],
                "potential_saving": report["summary"]["potential_saving"],
            })
        _record_event(repo, kind="confirm", user=user, quote_id=quote_id, detail=detail)
        return {"quote": _public(quote), "report": report}
    finally:
        repo.close()


@router.get("/api/quotes/{quote_id}/export.csv")
def export_quote(request: Request, quote_id: str):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
        quote = _owned(repo, user, quote_id)
        report = _report(repo, quote)
        if is_shopping_list(quote):
            body = matrix_export_csv(report)
            filename = f"lista-compra-{quote_id}.csv"
            export_detail = {
                "mode": MODE_SHOPPING_LIST,
                "matched_cells": report["summary"].get("matched_cells"),
                "best_store": report["summary"].get("best_store"),
                "best_store_subtotal": report["summary"].get("best_store_subtotal"),
                "complete": report["summary"].get("complete"),
            }
        else:
            output = io.StringIO()
            writer = csv.writer(output, delimiter=";")
            writer.writerow([
                "Producto", "Cantidad", "Unidad",
                "Referencia unitario CLP", "Referencia total CLP",
                "Mercado unitario CLP", "Mercado total CLP",
                "Diferencia sin despacho CLP",
                "Tienda", "Fecha precio mercado", "Stale", "Motivo match",
                "Estado", "Revisión", "Evidencia",
            ])
            for row in report["rows"]:
                selected = row["selected"] or {}
                evidence = row["item"].get("evidence") or {}
                qty = row["item"].get("quantity") or 1
                ref_unit = row["item"].get("unit_price")
                market_unit = selected.get("price")
                values = [
                    row["item"]["name"], qty, row["item"].get("unit") or "unidad",
                    ref_unit, row["reference_subtotal"],
                    market_unit, row["market_subtotal"],
                    row["potential_saving"],
                    selected.get("store", ""),
                    selected.get("observed_at") or "",
                    "sí" if selected.get("stale") else ("no" if selected else ""),
                    selected.get("match_reason") or "",
                    report["summary"]["status_label"],
                    " | ".join(row["issues"]),
                    f"{evidence.get('source', '')} fila {evidence.get('row', '')}",
                ]
                writer.writerow([("'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value)
                                 if isinstance(value, str) else value for value in values])
            writer.writerow([])
            writer.writerow(["Nota", report["summary"].get("shipping_note") or "Sin despacho: totales solo productos."])
            body = "\ufeff" + output.getvalue()
            filename = f"cotizacion-{quote_id}.csv"
            export_detail = {
                "compared_items": report["summary"]["compared_items"],
                "potential_saving": report["summary"]["potential_saving"],
                "complete": report["summary"]["complete"],
            }
        exported_at = datetime.now(timezone.utc).isoformat()
        quote["exported_at"] = exported_at
        quote, report = _apply_status(repo, quote, report)
        export_detail["status"] = quote["status"]
        repo.db.business_quotes.update_one(
            {"_id": quote_id, "owner_id": user["id"]},
            {"$set": {"exported_at": exported_at, "status": quote["status"]}},
        )
        _record_event(repo, kind="export", user=user, quote_id=quote_id, detail=export_detail)
        return Response(body, media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                 "Cache-Control": "no-store"})
    finally:
        repo.close()

@router.post("/api/quotes/{quote_id}/feedback")
def quote_feedback(request: Request, quote_id: str, payload: PilotEvent):
    repo = _repository()
    try:
        user = current_user(request, repo, admin=True)
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
