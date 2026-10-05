"""Jobs async Docling para cotizaciones (stub sin Docling)."""

from types import SimpleNamespace
from uuid import uuid4

from retail.quote_docling_jobs import enqueue_conversion, process_job, public_job


class _Jobs:
    def __init__(self):
        self.rows = {}

    def insert_one(self, document):
        self.rows[document["_id"]] = dict(document)

    def find_one(self, query):
        job = self.rows.get(query.get("_id"))
        if not job:
            return None
        if query.get("owner_id") and job.get("owner_id") != query["owner_id"]:
            return None
        return dict(job)

    def update_one(self, query, update):
        job = self.rows[query["_id"]]
        if "$set" in update:
            job.update(update["$set"])
        if "$inc" in update:
            for key, value in update["$inc"].items():
                job[key] = int(job.get(key) or 0) + value


def test_enqueue_and_stub_without_docling(tmp_path, monkeypatch):
    jobs = _Jobs()
    repo = SimpleNamespace(db={"quote_docling_jobs": jobs})
    job = enqueue_conversion(
        repo,
        owner_id="admin-1",
        title="Pinturas",
        source_name="lista.pdf",
        raw_bytes=b"%PDF-1.4 stub",
        root=tmp_path,
    )
    assert job["status"] == "queued"
    assert job["id"]
    stored = jobs.find_one({"_id": job["id"]})
    monkeypatch.setattr("retail.quote_docling_jobs._docling_available", lambda: False)
    result = process_job(repo, stored, root=tmp_path)
    assert result["status"] == "needs_docling"
    updated = jobs.find_one({"_id": job["id"]})
    assert updated["status"] == "needs_docling"
    assert "Docling" in updated["last_error"]
    assert public_job(updated)["status"] == "needs_docling"


def test_json_source_converts_without_ocr(tmp_path):
    import json

    from retail.quote_docling_jobs import process_job

    values = [["Descripción", "Cantidad", "Precio unitario"], ["Cable UTP 100 m", "1", "50000"]]
    cells = [
        {
            "start_row_offset_idx": r,
            "end_row_offset_idx": r + 1,
            "start_col_offset_idx": c,
            "end_col_offset_idx": c + 1,
            "text": value,
            "column_header": r == 0,
        }
        for r, row in enumerate(values)
        for c, value in enumerate(row)
    ]
    document = {
        "schema_name": "DoclingDocument",
        "pages": {"1": {}},
        "tables": [{"data": {"num_rows": 2, "num_cols": 3, "table_cells": cells}, "prov": [{"page_no": 1}]}],
    }
    source = tmp_path / "quote.json"
    source.write_text(json.dumps(document))
    jobs = _Jobs()
    repo = SimpleNamespace(db={"quote_docling_jobs": jobs})
    job_id = uuid4().hex
    jobs.insert_one({
        "_id": job_id,
        "owner_id": "a",
        "status": "queued",
        "title": "Cables",
        "supplier": "",
        "source_path": str(source),
        "attempts": 1,
        "tax_included": True,
        "valid_until": None,
    })
    result = process_job(repo, jobs.find_one({"_id": job_id}), root=tmp_path)
    assert result["status"] == "done"
    payload = json.loads((tmp_path / job_id / "result.json").read_text())
    assert payload["items"][0]["name"].startswith("Cable")
