"""Comparación reproducible con latencia simulada, sin consultar tiendas reales.

Ejecutar: python scripts/benchmark_search_categories.py --latency-ms 30 --repeats 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from unittest.mock import patch

from retail.index.products import stores_for
from retail.models import Product
from retail.registry import list_stores
from retail.search import scrape_all, scrape_category_probes


def benchmark(*, latency_ms: float, repeats: int) -> dict:
    available = [store.id for store in list_stores()]
    selected = stores_for("sal", available, client=False) or available
    others = [store for store in available if store not in selected]
    durations = {"exhaustive": [], "indexed_categories": []}
    counts = {}
    products = {}
    for _ in range(repeats):
        for mode in durations:
            calls = []

            def scrape(store, query, **kwargs):
                calls.append(store)
                time.sleep(latency_ms / 1000)
                if store not in {"lider", "unimarc", "ahumada"}:
                    return [], None
                return [Product(store=store, product_id=store, sku_id="sal", name="Sal de mesa", price=990)], None

            started = time.perf_counter()
            with patch("retail.search.scrape_store", scrape):
                if mode == "exhaustive":
                    found, _errors = scrape_all("sal", available, delay=0)
                else:
                    found, _errors = scrape_all("sal", selected, delay=0)
                    extra, _errors, _skipped = scrape_category_probes("sal", others, delay=0)
                    found.extend(product for items in extra.values() for product in items)
            durations[mode].append(time.perf_counter() - started)
            counts[mode] = len(calls)
            products[mode] = sorted((product.store, product.product_id) for product in found)
    baseline, indexed = (statistics.median(durations[key]) for key in durations)
    assert products["exhaustive"] == products["indexed_categories"]
    return {
        "scenario": "sal: coincidencias en supermercados/farmacias; otras categorías vacías",
        "simulated_latency_ms": latency_ms,
        "repeats": repeats,
        "stores": len(available),
        "calls": counts,
        "median_seconds": {key: round(statistics.median(value), 4) for key, value in durations.items()},
        "time_reduction_percent": round((baseline - indexed) * 100 / baseline, 1),
        "same_results": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-ms", type=float, default=30)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.latency_ms <= 0 or args.repeats <= 0:
        parser.error("latency-ms y repeats deben ser positivos")
    print(json.dumps(benchmark(latency_ms=args.latency_ms, repeats=args.repeats), ensure_ascii=False, indent=2))
