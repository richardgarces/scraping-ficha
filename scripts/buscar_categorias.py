#!/usr/bin/env python3
"""Busca categorías de celulares y supermercado en 3 tiendas a la vez.

    python scripts/buscar_categorias.py
    python scripts/buscar_categorias.py --mongo
    retail batch --catalogo retail/batch/catalogo_celulares_super.json --source scrape -n 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from retail.batch.catalog import load_catalog
from retail.batch.runner import run_batch

CATALOGO = Path("retail/batch/catalogo_celulares_super.json")
FALABELLA = Path("data/falabella_categorias.json")


def categorias_falabella() -> list[dict]:
    if not FALABELLA.exists():
        return []
    wanted = {
        item.get("falabella_category_id")
        for item in load_catalog(CATALOGO)["products"]
        if item.get("falabella_category_id")
    }
    payload = json.loads(FALABELLA.read_text(encoding="utf-8"))
    return [item for item in payload.get("categories") or [] if item.get("id") in wanted]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogo", type=Path, default=CATALOGO)
    parser.add_argument("--source", choices=["scrape", "db", "both"], default="scrape")
    parser.add_argument("-n", "--max", type=int, default=8)
    parser.add_argument("--pausa", type=float, default=2.0)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--mongo", action="store_true", help="Guardar las categorías Falabella en Mongo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.mongo:
        from retail.search import connect_repo

        cats = categorias_falabella()
        repo = connect_repo()
        if repo is None:
            print("Mongo no está disponible")
        else:
            try:
                saved = repo.save_categories("falabella", cats)
                print(f"mongo categorías: +{saved['upserted']} ~{saved['modified']} ({len(cats)} de celulares/súper)")
            finally:
                repo.close()

    summary = run_batch(
        catalog_path=args.catalogo,
        source=args.source,
        max_items=args.max,
        delay=args.delay,
        pause=args.pausa,
        limit=args.limit,
        dry_run=args.dry_run,
        persist=not args.dry_run,
    )
    print(
        f"listo: {len(summary.get('searches') or [])} búsquedas · "
        f"{summary.get('alert_count') or 0} alertas"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
