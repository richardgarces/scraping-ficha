"""Lista de compra multi-tienda: matriz lista × tiendas desde el catálogo Mongo.

No scrapea en la petición HTTP. Rellena celdas con el mejor match ≥80% por
tienda del grupo (p. ej. supermercados) y resume la canasta.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from typing import Any

from retail.quotes import QuoteLine, candidate_for
from retail.store_categories import list_store_categories, stores_for_group

MODE_QUOTE = "quote"
MODE_SHOPPING_LIST = "shopping_list"
EMPTY_CELL_LABEL = "sin stock o sin match"
LIST_REFRESH_SCORE = 90
LIST_FOLLOWING_SCORE = 96


def is_shopping_list(quote: dict) -> bool:
    return str(quote.get("mode") or MODE_QUOTE) == MODE_SHOPPING_LIST


def available_store_groups(*, repo: Any | None = None) -> list[dict[str, Any]]:
    """Grupos con sus tiendas conocidas (para el selector de la UI)."""
    rows = []
    for item in list_store_categories(repo=repo):
        stores = stores_for_group(item["id"], repo=repo)
        if not stores:
            continue
        rows.append({
            "id": item["id"],
            "title": item["title"],
            "store_ids": stores,
        })
    return rows


def resolve_list_stores(quote: dict, *, repo: Any | None = None) -> list[str]:
    explicit = [str(s).strip().lower() for s in (quote.get("store_ids") or []) if str(s).strip()]
    if explicit:
        return explicit
    group = str(quote.get("store_group") or "").strip().lower()
    if not group:
        raise ValueError("Elige una categoría de tiendas (por ejemplo supermercados).")
    stores = stores_for_group(group, repo=repo)
    if not stores:
        raise ValueError(f"No hay tiendas registradas en el grupo «{group}».")
    return stores


def _search_documents(repo: Any, line: QuoteLine) -> list[dict]:
    queries = [line.name]
    if line.gtin:
        queries.insert(0, line.gtin)
    words = [word for word in re.findall(r"[\w+-]+", line.name) if len(word) >= 3]
    queries.extend(words[:2])
    documents: dict[tuple[str, str], dict] = {}
    for query in queries[:4]:
        for doc in repo.find_by_query(query, limit=100):
            key = (str(doc.get("store") or ""), str(doc.get("product_id") or ""))
            if key[0] and key[1]:
                documents[key] = doc
    return list(documents.values())


def best_match_for_store(line: QuoteLine, documents: list[dict], store: str, now=None) -> dict | None:
    """Mejor candidato usable o, en su defecto, el de mayor confianza en esa tienda."""
    store = store.lower().strip()
    ranked: list[dict] = []
    for doc in documents:
        if str(doc.get("store") or "").lower() != store:
            continue
        candidate = candidate_for(line, doc, now=now)
        if candidate:
            ranked.append(candidate)
    if not ranked:
        return None
    ranked.sort(key=lambda row: (not row["usable"], -row["confidence"], row["price"]))
    return ranked[0]


def build_store_matches(repo: Any, quote: dict, *, now=None, enqueue_refresh: bool = True) -> dict[str, dict[str, dict]]:
    """Por cada ítem y tienda del set, propone el mejor match del catálogo."""
    stores = resolve_list_stores(quote, repo=repo)
    matches: dict[str, dict[str, dict]] = {}
    refresh_keys: list[tuple[str, str]] = []
    for index, raw in enumerate(quote["items"]):
        line = QuoteLine.model_validate(raw)
        docs = _search_documents(repo, line)
        per_store: dict[str, dict] = {}
        for store in stores:
            best = best_match_for_store(line, docs, store, now=now)
            if best:
                per_store[store] = {
                    "store": best["store"],
                    "product_id": best["product_id"],
                    "auto": True,
                    "confirmed": False,
                }
                refresh_keys.append((best["store"], best["product_id"]))
        matches[str(index)] = per_store
    if enqueue_refresh and refresh_keys:
        maybe_enqueue_matched_refresh(repo, refresh_keys)
    return matches


def maybe_enqueue_matched_refresh(repo: Any, keys: list[tuple[str, str]]) -> dict[str, int]:
    """Opcional: adelanta prioridad de scrape de SKUs matched (más si hay Siguiendo)."""
    priorities = getattr(repo, "scrape_priorities", None)
    if priorities is None:
        return {"boosted": 0, "following": 0}
    following: set[tuple[str, str]] = set()
    for coll_name in ("watches", "price_alerts"):
        coll = getattr(repo, coll_name, None) or getattr(getattr(repo, "db", None), coll_name, None)
        if coll is None:
            continue
        try:
            for row in coll.find({"active": True}, {"store": 1, "product_id": 1}):
                following.add((str(row.get("store") or ""), str(row.get("product_id") or "")))
        except Exception:
            pass
    now = datetime.now(timezone.utc)
    boosted = 0
    following_hits = 0
    seen: set[tuple[str, str]] = set()
    for store, product_id in keys:
        key = (store, product_id)
        if key in seen:
            continue
        seen.add(key)
        doc = None
        try:
            doc = repo.product_detail(store, product_id)
        except Exception:
            doc = None
        catalog_id = str((doc or {}).get("catalog_id") or "").strip()
        if not catalog_id:
            continue
        is_following = key in following
        score = LIST_FOLLOWING_SCORE if is_following else LIST_REFRESH_SCORE
        try:
            priorities.update_one(
                {"catalog_id": catalog_id},
                {
                    "$set": {
                        "score": score,
                        "tier": "high",
                        "next_due_at": now,
                        "updated_at": now,
                        "boost_reason": "lista_compra_siguiendo" if is_following else "lista_compra",
                    }
                },
                upsert=False,
            )
            boosted += 1
            if is_following:
                following_hits += 1
        except Exception:
            continue
    return {"boosted": boosted, "following": following_hits}


def _cell_from_candidate(candidate: dict | None) -> dict:
    if not candidate:
        return {
            "matched": False,
            "label": EMPTY_CELL_LABEL,
            "price": None,
            "subtotal": None,
            "confidence": None,
            "product_id": None,
            "name": None,
            "url": None,
            "issues": [],
            "usable": False,
            "confirmed": False,
        }
    return {
        "matched": True,
        "label": None,
        "store": candidate["store"],
        "product_id": candidate["product_id"],
        "name": candidate["name"],
        "price": candidate["price"],
        "confidence": candidate["confidence"],
        "match_method": candidate.get("match_method"),
        "observed_at": candidate.get("observed_at"),
        "issues": list(candidate.get("issues") or []),
        "usable": bool(candidate.get("usable")),
        "url": f"/producto?store={candidate['store']}&id={candidate['product_id']}",
        "confirmed": False,
    }


def shopping_matrix_report(
    quote: dict,
    store_matches: dict[str, dict[str, dict]],
    documents: dict[tuple[str, str], dict],
    stores: list[str] | None = None,
    now=None,
) -> dict:
    """Matriz fila=producto lista, columnas=tiendas + resumen de canasta."""
    now = now or datetime.now(timezone.utc)
    stores = list(stores or resolve_list_stores(quote))
    rows = []
    store_totals = {
        store: {"subtotal": 0, "matched_items": 0, "missing_items": 0, "missing_names": []}
        for store in stores
    }
    best_per_item = []

    for index, raw in enumerate(quote["items"]):
        line = QuoteLine.model_validate(raw)
        per_store = store_matches.get(str(index)) or {}
        cells = {}
        item_prices = []
        for store in stores:
            selected = per_store.get(store)
            candidate = None
            confirmed = False
            if selected:
                key = selected["store"], selected["product_id"]
                candidate = candidate_for(line, documents.get(key, {}), now=now)
                confirmed = bool(selected.get("confirmed"))
            cell = _cell_from_candidate(candidate)
            cell["confirmed"] = confirmed
            if candidate:
                cell["subtotal"] = candidate["price"] * line.quantity
                item_prices.append({
                    "store": store,
                    "price": candidate["price"],
                    "subtotal": cell["subtotal"],
                    "usable": cell["usable"],
                    "confidence": cell["confidence"],
                })
                store_totals[store]["subtotal"] += cell["subtotal"]
                store_totals[store]["matched_items"] += 1
            else:
                store_totals[store]["missing_items"] += 1
                store_totals[store]["missing_names"].append(line.name)
            cells[store] = cell

        best_item = None
        if item_prices:
            ranked = sorted(item_prices, key=lambda row: (not row["usable"], row["price"], -row["confidence"]))
            best_item = ranked[0]
        best_per_item.append({
            "index": index,
            "name": line.name,
            "best": best_item,
        })
        rows.append({
            "index": index,
            "item": raw,
            "cells": cells,
            "best_store": (best_item or {}).get("store"),
            "best_price": (best_item or {}).get("price"),
        })

    basket = []
    for store in stores:
        totals = store_totals[store]
        basket.append({
            "store": store,
            "subtotal": totals["subtotal"] if totals["matched_items"] else None,
            "matched_items": totals["matched_items"],
            "missing_items": totals["missing_items"],
            "missing_names": totals["missing_names"],
            "complete": totals["missing_items"] == 0 and totals["matched_items"] == len(quote["items"]),
        })

    def basket_rank(row: dict):
        if row["subtotal"] is None:
            return (3, 0, 0)
        # Prefer complete baskets, then more coverage, then lower total.
        return (0 if row["complete"] else 1, -row["matched_items"], row["subtotal"])

    ranked_basket = sorted(basket, key=basket_rank)
    best_store = next((row for row in ranked_basket if row["subtotal"] is not None), None)
    matched_cells = sum(
        1 for row in rows for store in stores if row["cells"][store]["matched"]
    )
    confirmed_cells = sum(
        1 for row in rows for store in stores if row["cells"][store].get("confirmed")
    )
    summary = {
        "mode": MODE_SHOPPING_LIST,
        "items": len(rows),
        "stores": stores,
        "store_group": quote.get("store_group") or "",
        "matched_cells": matched_cells,
        "confirmed_cells": confirmed_cells,
        "total_cells": len(rows) * len(stores),
        "best_store": (best_store or {}).get("store"),
        "best_store_subtotal": (best_store or {}).get("subtotal"),
        "best_store_complete": bool((best_store or {}).get("complete")),
        "best_store_missing": list((best_store or {}).get("missing_names") or []),
        "basket": ranked_basket,
        "best_per_item": best_per_item,
        "complete": bool(best_store and best_store.get("complete")),
        "status": "compared" if best_store and best_store.get("matched_items") else "review",
        "status_label": (
            "Comparada" if best_store and best_store.get("complete")
            else ("Revisión" if matched_cells else "Borrador")
        ),
        "note": (
            "Matriz lista × tiendas con precios del catálogo Mongo (máx. 48 h). "
            "Sin despacho. Celdas vacías = sin match ≥80% o sin stock usable. "
            "Confirma coincidencias dudosas antes de decidir la compra."
        ),
        "shipping_included": False,
        "realized_saving": None,
    }
    if quote.get("exported_at") and summary["complete"]:
        summary["status"] = "exported"
        summary["status_label"] = "Exportada"
    elif not matched_cells:
        summary["status"] = "draft"
        summary["status_label"] = "Borrador"
    return {
        "mode": MODE_SHOPPING_LIST,
        "stores": stores,
        "rows": rows,
        "summary": summary,
        "generated_at": now.isoformat(),
    }


def matrix_export_csv(report: dict) -> str:
    stores = report.get("stores") or []
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    header = ["Producto", "Cantidad", "Marca", "Mejor tienda", "Mejor precio CLP"]
    for store in stores:
        header.extend([f"{store} CLP", f"{store} confianza", f"{store} ficha"])
    writer.writerow(header)
    for row in report.get("rows") or []:
        item = row.get("item") or {}
        values = [
            item.get("name", ""),
            item.get("quantity", 1),
            item.get("brand", ""),
            row.get("best_store") or "",
            row.get("best_price"),
        ]
        for store in stores:
            cell = (row.get("cells") or {}).get(store) or {}
            if cell.get("matched"):
                values.extend([
                    cell.get("price"),
                    f"{int(round((cell.get('confidence') or 0) * 100))}%" if cell.get("confidence") is not None else "",
                    cell.get("url") or "",
                ])
            else:
                values.extend([EMPTY_CELL_LABEL, "", ""])
        writer.writerow([
            ("'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value)
            for value in values
        ])
    writer.writerow([])
    writer.writerow(["Resumen canasta"])
    writer.writerow(["Tienda", "Subtotal CLP", "Ítems con match", "Faltantes", "Completa"])
    for basket in (report.get("summary") or {}).get("basket") or []:
        writer.writerow([
            basket.get("store"),
            basket.get("subtotal"),
            basket.get("matched_items"),
            basket.get("missing_items"),
            "sí" if basket.get("complete") else "no",
        ])
    best = report.get("summary") or {}
    writer.writerow([])
    writer.writerow([
        "Mejor tienda canasta",
        best.get("best_store") or "",
        best.get("best_store_subtotal"),
        "completa" if best.get("best_store_complete") else "parcial",
    ])
    return "\ufeff" + output.getvalue()
