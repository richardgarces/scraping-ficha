#!/usr/bin/env python3
"""Backfill + evaluación diaria de cumplimiento de pronósticos experimentales."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main() -> int:
    from retail.forecast_outcomes import run_daily_outcome_pass
    from retail.mongo import ProductRepository

    uri = os.environ.get("MONGODB_URI") or "mongodb://localhost:27017"
    db = os.environ.get("MONGODB_DB") or "scraping"
    repo = ProductRepository(uri, database=db)
    try:
        result = run_daily_outcome_pass(repo)
        backfill = result.get("backfill") or {}
        evaluate = result.get("evaluate") or {}
        print(
            "forecast outcomes:",
            f"backfill_scanned={backfill.get('scanned', 0)}",
            f"backfill_inserted={backfill.get('inserted', 0)}",
            f"checked={evaluate.get('checked', 0)}",
            f"hit={evaluate.get('hit', 0)}",
            f"miss={evaluate.get('miss', 0)}",
            f"pending={evaluate.get('pending', 0)}",
        )
    finally:
        repo.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
