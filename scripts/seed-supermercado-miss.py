#!/usr/bin/env python3
"""Siembra catálogo grocery en jumbo/santa_isabel (y opcional otras) vía search_products.

Uso (en host con red a tiendas / FlareSolverr):
  python scripts/seed-supermercado-miss.py
  python scripts/seed-supermercado-miss.py --stores jumbo,santa_isabel --max-items 6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_QUERIES = [
    "azúcar granulada 1 kg",
    "azúcar 1.5 kg",
    "aceite maravilla 1 l",
    "leche entera 1 l",
    "arroz grado 1 1 kg",
    "harina 1 kg",
    "fideos spaghetti 400 g",
    "café molido 250 g",
    "té bolsas",
    "papel higiénico",
    "detergente líquido",
    "shampoo",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stores", default="jumbo,santa_isabel")
    parser.add_argument("--max-items", type=int, default=6)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--queries-file", default="")
    args = parser.parse_args()
    stores = [s.strip().lower() for s in args.stores.split(",") if s.strip()]
    queries = list(DEFAULT_QUERIES)
    if args.queries_file:
        path = Path(args.queries_file)
        queries = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    from retail.search import search_products

    ok = 0
    for index, query in enumerate(queries, start=1):
        print(f"[{index}/{len(queries)}] {query} → {', '.join(stores)}", flush=True)
        try:
            result = search_products(
                query,
                source="scrape",
                stores=stores,
                max_items=max(1, args.max_items),
                delay=args.delay,
                persist=True,
                wait_for_all=True,
                persist_meta={"seed_supermercado": True, "list_query": query},
            )
            items = result.get("items") or result.get("products") or []
            print(f"    hits={len(items)}", flush=True)
            ok += 1
        except Exception as exc:
            print(f"    error: {exc}", flush=True)
    print(f"done ok={ok}/{len(queries)}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
