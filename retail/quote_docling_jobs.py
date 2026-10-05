"""Cola async PDF→JSON Docling para cotizaciones (fuera del request web).

El worker puede correr en Soyo/scraping donde Docling esté instalado
(`pip install -e '.[documents]'`). En BMAX sin Docling el job queda en
``needs_docling`` y se documenta usar ``scripts/convert_quote_document.py``.
"""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

JOB_COLLECTION = "quote_docling_jobs"
LEASE_SECONDS = 600
MAX_ATTEMPTS = 3
STATUSES = (
    "queued",
    "processing",
    "done",
    "failed",
    "needs_docling",
    "retry",
)

# Relativo al repo; en contenedor suele montarse /app o similar.
DEFAULT_UPLOAD_ROOT = Path(os.environ.get("QUOTE_DOCLING_ROOT") or "output/quote_docling")


def chile_now() -> datetime:
    return datetime.now(timezone.utc)


def job_dir(root: Path, job_id: str) -> Path:
    return root / job_id


def public_job(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": document.get("_id") or document.get("id"),
        "status": document.get("status"),
        "title": document.get("title") or "",
        "supplier": document.get("supplier") or "",
        "source_name": document.get("source_name") or "",
        "attempts": int(document.get("attempts") or 0),
        "last_error": document.get("last_error") or "",
        "result_path": document.get("result_path") or "",
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "finished_at": document.get("finished_at"),
        "metadata": document.get("metadata") or {},
    }


def enqueue_conversion(
    repo: Any,
    *,
    owner_id: str,
    title: str,
    supplier: str = "",
    source_name: str = "documento.pdf",
    raw_bytes: bytes,
    tax_included: bool | None = None,
    valid_until: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    if not owner_id:
        raise ValueError("Falta el propietario del job.")
    if not raw_bytes:
        raise ValueError("El archivo está vacío.")
    if len(raw_bytes) > 20_000_000:
        raise ValueError("El documento supera 20 MB.")
    suffix = Path(source_name).suffix.lower() or ".pdf"
    if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".json"}:
        raise ValueError("Usa PDF, imagen o JSON Docling.")
    job_id = uuid.uuid4().hex
    base = root or DEFAULT_UPLOAD_ROOT
    folder = job_dir(base, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    source_path = folder / f"source{suffix}"
    source_path.write_bytes(raw_bytes)
    now = chile_now()
    document = {
        "_id": job_id,
        "owner_id": owner_id,
        "status": "queued",
        "title": str(title or "").strip()[:150] or "Cotización",
        "supplier": str(supplier or "").strip()[:150],
        "source_name": str(source_name or source_path.name)[:200],
        "source_path": str(source_path),
        "result_path": "",
        "tax_included": tax_included,
        "valid_until": valid_until,
        "attempts": 0,
        "available_at": now,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "last_error": "",
        "metadata": {},
    }
    repo.db[JOB_COLLECTION].insert_one(document)
    return public_job(document)


def get_job(repo: Any, job_id: str, *, owner_id: str | None = None) -> dict[str, Any] | None:
    query: dict[str, Any] = {"_id": job_id}
    if owner_id:
        query["owner_id"] = owner_id
    found = repo.db[JOB_COLLECTION].find_one(query)
    return public_job(found) if found else None


def load_result_json(repo: Any, job_id: str, *, owner_id: str) -> dict[str, Any]:
    job = repo.db[JOB_COLLECTION].find_one({"_id": job_id, "owner_id": owner_id})
    if not job:
        raise FileNotFoundError("Job no encontrado.")
    if job.get("status") != "done":
        raise ValueError(f"El job aún no está listo (estado: {job.get('status')}).")
    path = Path(str(job.get("result_path") or ""))
    if not path.is_file():
        raise FileNotFoundError("No está el JSON resultante.")
    return json.loads(path.read_text(encoding="utf-8"))


def _docling_available() -> bool:
    try:
        import docling  # noqa: F401

        return True
    except Exception:
        return False


def process_job(repo: Any, job: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Procesa un job reclamado. Stub si Docling no está instalado."""
    now = chile_now()
    job_id = job["_id"]
    source = Path(str(job.get("source_path") or ""))
    if not source.is_file():
        _fail(repo, job, "Falta el archivo de origen.")
        return {"status": "failed"}
    if source.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"} and not _docling_available():
        message = (
            "Docling no está instalado en este entorno. "
            "Ejecuta en Soyo/scraping: python scripts/convert_quote_document.py "
            f"{source} --output {job_dir(root or DEFAULT_UPLOAD_ROOT, job_id) / 'result.json'} "
            f"--title {job.get('title')!r}"
        )
        repo.db[JOB_COLLECTION].update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "needs_docling",
                    "last_error": message[:800],
                    "updated_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "worker": socket.gethostname(),
                }
            },
        )
        return {"status": "needs_docling"}
    try:
        from retail.quote_documents import convert_document

        quote, metadata = convert_document(
            source,
            title=job.get("title") or "Cotización",
            supplier=job.get("supplier") or "",
            tax_included=job.get("tax_included"),
            valid_until=job.get("valid_until"),
        )
        out = job_dir(root or DEFAULT_UPLOAD_ROOT, job_id) / "result.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(quote.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        repo.db[JOB_COLLECTION].update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "done",
                    "result_path": str(out),
                    "metadata": metadata,
                    "last_error": "",
                    "updated_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                    "worker": socket.gethostname(),
                }
            },
        )
        return {"status": "done", "result_path": str(out)}
    except ImportError as exc:
        repo.db[JOB_COLLECTION].update_one(
            {"_id": job_id},
            {
                "$set": {
                    "status": "needs_docling",
                    "last_error": f"Docling no disponible: {exc}"[:800],
                    "updated_at": now.isoformat(),
                    "finished_at": now.isoformat(),
                }
            },
        )
        return {"status": "needs_docling"}
    except Exception as exc:
        _retry_or_fail(repo, job, exc)
        return {"status": "retry"}


def _fail(repo: Any, job: dict[str, Any], message: str) -> None:
    repo.db[JOB_COLLECTION].update_one(
        {"_id": job["_id"]},
        {
            "$set": {
                "status": "failed",
                "last_error": message[:800],
                "updated_at": chile_now().isoformat(),
                "finished_at": chile_now().isoformat(),
            }
        },
    )


def _retry_or_fail(repo: Any, job: dict[str, Any], exc: Exception) -> None:
    attempts = int(job.get("attempts") or 1)
    failed = attempts >= MAX_ATTEMPTS
    now = chile_now()
    update: dict[str, Any] = {
        "status": "failed" if failed else "retry",
        "last_error": f"{type(exc).__name__}: {exc}"[:800],
        "updated_at": now.isoformat(),
    }
    if not failed:
        update["available_at"] = now + timedelta(seconds=min(900, 30 * (2 ** (attempts - 1))))
    else:
        update["finished_at"] = now.isoformat()
    repo.db[JOB_COLLECTION].update_one({"_id": job["_id"]}, {"$set": update})


def claim_jobs(repo: Any, limit: int = 1) -> list[dict[str, Any]]:
    from pymongo import ReturnDocument

    now = chile_now()
    claimed = []
    for _ in range(max(1, limit)):
        job = repo.db[JOB_COLLECTION].find_one_and_update(
            {
                "$or": [
                    {"status": {"$in": ["queued", "retry"]}, "available_at": {"$lte": now}},
                    {"status": "processing", "lease_until": {"$lte": now}},
                ],
                "attempts": {"$lt": MAX_ATTEMPTS},
            },
            {
                "$set": {
                    "status": "processing",
                    "claimed_at": now.isoformat(),
                    "lease_until": now + timedelta(seconds=LEASE_SECONDS),
                    "worker": socket.gethostname(),
                    "updated_at": now.isoformat(),
                },
                "$inc": {"attempts": 1},
            },
            sort=[("available_at", 1), ("created_at", 1)],
            return_document=ReturnDocument.AFTER,
        )
        if not job:
            break
        claimed.append(job)
    return claimed


def run_once(repo: Any, limit: int = 1) -> dict[str, int]:
    metrics = {"processed": 0, "done": 0, "needs_docling": 0, "failed": 0, "errors": 0}
    for job in claim_jobs(repo, limit):
        try:
            result = process_job(repo, job)
            metrics["processed"] += 1
            status = result.get("status")
            if status in metrics:
                metrics[status] += 1
        except Exception:
            metrics["errors"] += 1
    return metrics


def worker_loop(repo: Any, poll_seconds: float = 3.0) -> None:
    while True:
        metrics = run_once(repo)
        if metrics["processed"] or metrics["errors"]:
            print(f"quote-docling-worker {metrics}", flush=True)
        else:
            time.sleep(poll_seconds)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    args = parser.parse_args()
    from retail.mongo import ProductRepository

    repo = ProductRepository()
    try:
        if args.once:
            print(f"quote-docling-worker {run_once(repo, args.limit)}", flush=True)
            return
        worker_loop(repo)
    finally:
        repo.close()


if __name__ == "__main__":
    main()
