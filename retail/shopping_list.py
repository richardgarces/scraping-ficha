"""Lista de compra multi-tienda: matriz lista × tiendas desde el catálogo Mongo.

No scrapea en la petición HTTP. Rellena celdas con el mejor match por tienda
del grupo (identidad ≥80% o, si la línea es corta/genérica, query ⊆ nombre/marca)
y resume la canasta. Los matches por subconjunto quedan sin confirmar para revisión.
"""
from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from retail.pricing import buy_or_wait, parse_moment
from retail.quotes import QuoteLine, candidate_for, column_key, product_from_document
from retail.quote_units import unit_price_for_quote
from retail.relevance import equivalent_tokens, fold, score_product, tokenize
from retail.search_cache import rewrite_search_query
from retail.store_categories import list_store_categories, stores_for_group

MODE_QUOTE = "quote"
MODE_SHOPPING_LIST = "shopping_list"
EMPTY_CELL_LABEL = "sin stock o sin match"
LIST_REFRESH_SCORE = 90
LIST_FOLLOWING_SCORE = 96
PRICE_MAX_AGE_HOURS = 48
# Confianza mostrada cuando el ítem de la lista es un subconjunto del nombre/marca
# (p. ej. «azúcar» → «Azúcar granulada Iansa»). Bajo el umbral de identidad 80%.
LIST_QUERY_SUBSET_CONFIDENCE = 0.72
# Quita "x 6 un", "pack de 12", etc. del nombre para buscar el producto base.
_PACK_NOISE_RE = re.compile(
    r"\b(?:x\s*\d+\s*(?:un(?:idades?)?|u|und|packs?)?|pack\s*(?:de\s*)?\d+|\d+\s*(?:un(?:idades?)?|u)\s*(?:por\s*)?pack)\b",
    re.I,
)


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


def _line_search_query(line: QuoteLine) -> str:
    """Nombre (+ marca) normalizado: acentos/caso/alias (iansa↔ianza)."""
    name = _PACK_NOISE_RE.sub(" ", line.name or "")
    name = re.sub(r"\s+", " ", name).strip()
    parts = [rewrite_search_query(name)]
    if line.brand:
        parts.append(rewrite_search_query(line.brand))
    return " ".join(part for part in parts if part).strip()


def _price_age_hours(observed: datetime | None, now: datetime | None = None) -> float | None:
    if not observed:
        return None
    now = now or datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return max(0.0, (now - observed).total_seconds() / 3600.0)


def _is_stale_issue(issues: list[str] | None) -> bool:
    return any("fecha reciente" in str(item).lower() or "48 hora" in str(item).lower() for item in (issues or []))


def _match_reason(candidate: dict) -> str:
    method = str(candidate.get("match_method") or "")
    confidence = candidate.get("confidence")
    pct = f"{int(round(float(confidence) * 100))}%" if confidence is not None else ""
    if method == "query_subset":
        return f"Nombre contiene las palabras de la lista{f' · {pct}' if pct else ''}"
    if pct:
        return f"Identidad {pct}"
    return "Coincidencia de catálogo"


def _search_documents(repo: Any, line: QuoteLine) -> list[dict]:
    primary = _line_search_query(line)
    queries = [primary] if primary else []
    if line.gtin:
        queries.insert(0, line.gtin)
    # Tokens sueltos ayudan cuando la frase completa no pega en $text.
    queries.extend(tokenize(primary)[:3])
    documents: dict[tuple[str, str], dict] = {}
    for query in list(dict.fromkeys(queries))[:5]:
        if not query:
            continue
        for doc in repo.find_by_query(query, limit=100):
            key = (str(doc.get("store") or ""), str(doc.get("product_id") or ""))
            if key[0] and key[1]:
                documents[key] = doc
    return list(documents.values())


def _token_positively_present(token: str, name: str, brand: str) -> bool:
    """True si el token aparece en marca o en el nombre fuera de «sin {token}»."""
    brand_fold = fold(brand)
    name_fold = fold(name)
    for alt in equivalent_tokens(token):
        if alt in brand_fold.split() or brand_fold == alt:
            return True
        if alt not in name_fold:
            continue
        stripped = re.sub(rf"\bsin\s+{re.escape(alt)}\b", " ", name_fold)
        words = stripped.split()
        if alt in words or any(word.startswith(alt) and len(word) <= len(alt) + 2 for word in words):
            return True
    return False


def _query_subset_rank(query: str, name: str, brand: str) -> float:
    """Prioriza nombre que empieza por el ítem y marca; castiga «sin azúcar» etc."""
    hay = fold(name)
    brand_fold = fold(brand)
    score = 0.0
    for token in tokenize(query):
        for alt in equivalent_tokens(token):
            if re.search(rf"\bsin\s+{re.escape(alt)}\b", hay):
                score -= 0.4
            if hay.startswith(alt + " ") or hay == alt:
                score += 0.35
            elif f" {alt} " in f" {hay} ":
                score += 0.12
            if alt in brand_fold.split() or brand_fold == alt:
                score += 0.15
    return score


def _query_subset_candidate(line: QuoteLine, doc: dict, now: datetime | None = None) -> dict | None:
    """Match laxo: las palabras de la lista están en nombre/marca (case/acentos OK)."""
    if not doc:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        product = product_from_document(doc)
    except (TypeError, ValueError, OverflowError):
        return None
    if not product.store or not product.product_id:
        return None
    query = _line_search_query(line)
    if not query:
        return None
    relevance = score_product(query, product)
    if not relevance.accepted:
        return None
    tokens = tokenize(query)
    if tokens and not all(
        _token_positively_present(token, product.name or "", product.brand or "")
        for token in tokens
    ):
        # Evita «chicle sin azúcar» cuando la lista pide «azúcar».
        return None
    price = product.price_all_payment or product.price
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    observed = parse_moment(doc.get("updated_at") or doc.get("scraped_at"))
    if observed and observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    fresh = bool(
        observed and now - timedelta(hours=PRICE_MAX_AGE_HOURS) <= observed <= now + timedelta(minutes=10)
    )
    availability = column_key(product.availability)
    unavailable = product.stock == 0 or availability in {
        "agotado", "sinstock", "outofstock", "unavailable", "nodisponible",
    }
    verified_stock = isinstance(product.stock, int) and not isinstance(product.stock, bool) and product.stock >= line.quantity
    available = verified_stock or (
        line.quantity == 1 and availability in {"disponible", "available", "instock", "enstock"}
    )
    unit_ok, unit_price, unit_issues = unit_price_for_quote(line.unit, int(price), product)
    issues = list(unit_issues)
    age_hours = _price_age_hours(observed, now)
    if not fresh:
        issues.append(f"Precio sin fecha reciente (máximo {PRICE_MAX_AGE_HOURS} horas).")
    if unavailable:
        issues.append("Producto sin stock.")
    elif not available:
        issues.append("Cantidad disponible por confirmar.")
    if product.currency != "CLP":
        issues.append("La moneda del catálogo no es CLP.")
    comparable_price = unit_price if unit_ok and unit_price else int(price)
    rank = _query_subset_rank(query, product.name or "", product.brand or "")
    confidence = round(
        min(0.79, max(LIST_QUERY_SUBSET_CONFIDENCE, 0.55 + 0.25 * float(relevance.score) + max(0.0, rank) * 0.1)),
        3,
    )
    candidate = {
        "store": product.store,
        "product_id": product.product_id,
        "name": product.name,
        "price": comparable_price,
        "currency": product.currency,
        "confidence": confidence,
        "match_method": "query_subset",
        "rank_boost": rank,
        "observed_at": observed.isoformat() if observed else None,
        "price_age_hours": round(age_hours, 1) if age_hours is not None else None,
        "stale": not fresh,
        "shipping_cost": product.shipping_cost,
        "shipping_region": product.shipping_region,
        "stock": product.stock,
        "issues": issues,
        "usable": not issues and product.currency == "CLP",
        "advice": buy_or_wait(doc.get("price_history"), int(price), now=now),
        "unit": line.unit,
        "unit_compatible": unit_ok,
        "catalog_pack_price": int(price),
    }
    candidate["match_reason"] = _match_reason(candidate)
    return candidate


def list_candidate_for(line: QuoteLine, doc: dict, now=None) -> dict | None:
    """Identidad ≥80% si aplica; si no, subconjunto de nombre/marca (lista corta)."""
    if not doc:
        return None
    strict = candidate_for(line, doc, now=now)
    if strict:
        return strict
    return _query_subset_candidate(line, doc, now=now)


def best_match_for_store(line: QuoteLine, documents: list[dict], store: str, now=None) -> dict | None:
    """Mejor candidato usable o, en su defecto, el de mayor confianza en esa tienda."""
    store = store.lower().strip()
    ranked: list[dict] = []
    for doc in documents:
        if str(doc.get("store") or "").lower() != store:
            continue
        candidate = list_candidate_for(line, doc, now=now)
        if candidate:
            ranked.append(candidate)
    if not ranked:
        return None
    ranked.sort(
        key=lambda row: (
            not row["usable"],
            -float(row.get("rank_boost") or 0.0),
            -row["confidence"],
            row["price"],
        )
    )
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
            else:
                store_docs = [
                    doc for doc in docs
                    if str(doc.get("store") or "").lower() == store.lower()
                ]
                per_store[store] = {
                    "empty_reason": "no_match" if store_docs else "no_catalog",
                    "empty_label": (
                        "sin match suficiente (prueba EAN o nombre más corto)"
                        if store_docs
                        else "sin producto en catálogo"
                    ),
                }
        matches[str(index)] = per_store
    if enqueue_refresh and refresh_keys:
        maybe_enqueue_matched_refresh(repo, refresh_keys)
    return matches


def refresh_quote_prices(repo: Any, quote: dict) -> dict[str, Any]:
    """Re-encola boost de scrape para SKUs ya matcheados en la lista/cotización."""
    keys: list[tuple[str, str]] = []
    if is_shopping_list(quote):
        for per_store in (quote.get("store_matches") or {}).values():
            if not isinstance(per_store, dict):
                continue
            for selected in per_store.values():
                if not isinstance(selected, dict):
                    continue
                store = str(selected.get("store") or "").strip()
                product_id = str(selected.get("product_id") or "").strip()
                if store and product_id:
                    keys.append((store, product_id))
    else:
        for selected in (quote.get("selections") or {}).values():
            if not isinstance(selected, dict):
                continue
            store = str(selected.get("store") or "").strip()
            product_id = str(selected.get("product_id") or "").strip()
            if store and product_id:
                keys.append((store, product_id))
    stats = maybe_enqueue_matched_refresh(repo, keys)
    return {
        **stats,
        "targets": len(set(keys)),
        "message": (
            (
                f"Prioridad de scrape subida en {stats.get('boosted', 0)} SKU(s)"
                + (
                    f" ({stats.get('following', 0)} en Siguiendo)"
                    if stats.get("following")
                    else ""
                )
                + ". Esperá unos minutos y regenerá la matriz o recargá la cotización."
            )
            if stats.get("boosted")
            else "No hay SKUs matcheados para actualizar, o no hay cola de prioridades."
        ),
        "price_max_age_hours": PRICE_MAX_AGE_HOURS,
    }


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


def _empty_cell(*, reason: str = "no_match", label: str | None = None) -> dict:
    labels = {
        "no_match": "sin match suficiente (prueba EAN o nombre más corto)",
        "no_catalog": "sin producto en catálogo",
        "stale_only": "precio fuera de ventana 48 h",
        "unknown": EMPTY_CELL_LABEL,
    }
    return {
        "matched": False,
        "label": label or labels.get(reason, EMPTY_CELL_LABEL),
        "empty_reason": reason,
        "price": None,
        "subtotal": None,
        "confidence": None,
        "product_id": None,
        "name": None,
        "url": None,
        "issues": [],
        "usable": False,
        "confirmed": False,
        "stale": reason == "stale_only",
        "observed_at": None,
        "price_age_hours": None,
        "match_reason": None,
    }


def _cell_from_candidate(candidate: dict | None) -> dict:
    if not candidate:
        return _empty_cell(reason="unknown")
    issues = list(candidate.get("issues") or [])
    stale = bool(candidate.get("stale")) or _is_stale_issue(issues)
    return {
        "matched": True,
        "label": None,
        "empty_reason": None,
        "store": candidate["store"],
        "product_id": candidate["product_id"],
        "name": candidate["name"],
        "price": candidate["price"],
        "confidence": candidate["confidence"],
        "match_method": candidate.get("match_method"),
        "match_reason": candidate.get("match_reason") or _match_reason(candidate),
        "observed_at": candidate.get("observed_at"),
        "price_age_hours": candidate.get("price_age_hours"),
        "stale": stale,
        "issues": issues,
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
            selected = per_store.get(store) or {}
            candidate = None
            confirmed = False
            if selected.get("store") and selected.get("product_id"):
                key = selected["store"], selected["product_id"]
                candidate = list_candidate_for(line, documents.get(key, {}), now=now)
                confirmed = bool(selected.get("confirmed"))
            if candidate:
                cell = _cell_from_candidate(candidate)
                cell["confirmed"] = confirmed
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
                cell = _empty_cell(
                    reason=str(selected.get("empty_reason") or "unknown"),
                    label=selected.get("empty_label"),
                )
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
    stale_cells = sum(
        1 for row in rows for store in stores if row["cells"][store].get("stale")
    )
    summary = {
        "mode": MODE_SHOPPING_LIST,
        "items": len(rows),
        "stores": stores,
        "store_group": quote.get("store_group") or "",
        "matched_cells": matched_cells,
        "confirmed_cells": confirmed_cells,
        "stale_cells": stale_cells,
        "total_cells": len(rows) * len(stores),
        "price_max_age_hours": PRICE_MAX_AGE_HOURS,
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
            f"Matriz lista × tiendas con precios del catálogo Mongo "
            f"(ventana {PRICE_MAX_AGE_HOURS} h). Totales sin despacho. "
            "Celdas vacías: sin producto en catálogo o sin match suficiente. "
            "Amarillo = precio fuera de ventana. Usá «Actualizar precios» y regenerá."
        ),
        "shipping_included": False,
        "shipping_note": "Sin despacho: totales solo productos.",
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
    header = [
        "Producto", "Cantidad", "Marca", "Unidad",
        "Mejor tienda", "Mejor precio unitario CLP", "Mejor total línea CLP",
        "Fecha precio mejor", "Stale mejor",
    ]
    for store in stores:
        header.extend([
            f"{store} CLP",
            f"{store} total línea",
            f"{store} confianza",
            f"{store} fecha precio",
            f"{store} stale",
            f"{store} motivo",
            f"{store} ficha",
        ])
    writer.writerow(header)
    for row in report.get("rows") or []:
        item = row.get("item") or {}
        qty = item.get("quantity", 1)
        best_store = row.get("best_store") or ""
        best_cell = (row.get("cells") or {}).get(best_store) or {}
        best_price = row.get("best_price")
        best_total = (best_price * qty) if isinstance(best_price, (int, float)) else ""
        values = [
            item.get("name", ""),
            qty,
            item.get("brand", ""),
            item.get("unit", "unidad"),
            best_store,
            best_price,
            best_total,
            best_cell.get("observed_at") or "",
            "sí" if best_cell.get("stale") else ("no" if best_cell.get("matched") else ""),
        ]
        for store in stores:
            cell = (row.get("cells") or {}).get(store) or {}
            if cell.get("matched"):
                price = cell.get("price")
                values.extend([
                    price,
                    (price * qty) if isinstance(price, (int, float)) else "",
                    f"{int(round((cell.get('confidence') or 0) * 100))}%" if cell.get("confidence") is not None else "",
                    cell.get("observed_at") or "",
                    "sí" if cell.get("stale") else "no",
                    cell.get("match_reason") or "",
                    cell.get("url") or "",
                ])
            else:
                values.extend([
                    cell.get("label") or EMPTY_CELL_LABEL,
                    "",
                    "",
                    "",
                    "",
                    cell.get("empty_reason") or "",
                    "",
                ])
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
    writer.writerow([])
    writer.writerow(["Nota", best.get("shipping_note") or "Sin despacho: totales solo productos."])
    writer.writerow(["Celdas stale", best.get("stale_cells") or 0])
    writer.writerow(["Ventana precio horas", best.get("price_max_age_hours") or PRICE_MAX_AGE_HOURS])
    return "\ufeff" + output.getvalue()
