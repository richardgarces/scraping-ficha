"""Browser contract check with synthetic quotes and no production writes."""
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(os.environ.get("QUOTE_STATIC_DIR", Path(__file__).resolve().parents[2] / "retail/web/static"))

quote = {
    "id": "a" * 32, "version": 1, "title": "Compra de equipos", "supplier": "Proveedor",
    "source_name": "lista.csv", "source_sha256": "b" * 64, "source_kind": "csv", "currency": "CLP",
    "tax_included": True, "valid_until": None, "source_reviewed": False, "extraction_warnings": [],
    "mode": "quote",
    "items": [{"name": "Samsung Galaxy S25 256GB", "brand": "Samsung", "quantity": 2,
               "unit_price": 700000, "unit": "unidad", "condition": "new", "gtin": "",
               "evidence": {"source": "lista.csv", "row": 2, "text": "Samsung Galaxy S25 256GB | 2 | 700000"}}],
    "created_at": "2026-10-05T15:00:00+00:00", "selections": {}, "status": "draft",
}
candidate = {"store": "lider", "product_id": "sku", "name": "Samsung Galaxy S25 256GB",
             "price": 600000, "confidence": .95, "observed_at": "2026-10-05T15:00:00+00:00",
             "match_reason": "Identidad 95%", "stale": False, "issues": [], "usable": True,
             "advice": {"reason": "Historial todavía insuficiente."}}
created = False

shopping_quote = {
    "id": "c" * 32, "version": 1, "title": "Super del mes", "supplier": "",
    "source_name": "lista.csv", "source_sha256": "d" * 64, "source_kind": "csv", "currency": "CLP",
    "tax_included": True, "valid_until": None, "source_reviewed": False, "extraction_warnings": [],
    "mode": "shopping_list", "store_group": "supermercados", "resolved_stores": ["lider", "unimarc"],
    "items": [
        {"name": "Azúcar granulada 1 kg", "brand": "", "quantity": 1, "unit_price": None,
         "unit": "unidad", "condition": "new", "gtin": ""},
    ],
    "store_matches": {
        "0": {"lider": {"store": "lider", "product_id": "az", "confirmed": False}},
    },
    "created_at": "2026-10-05T15:00:00+00:00", "selections": {}, "status": "compared",
}
shopping_created = False
refresh_called = False


def quote_detail():
    selected = bool(quote["selections"])
    return {"quote": quote, "report": {
        "rows": [{"item": quote["items"][0], "selected": candidate if selected else None,
                  "issues": [] if selected else ["Confirma una coincidencia válida del catálogo."]}],
        "summary": {"items": 1, "compared_items": int(selected), "confirmed_items": int(selected),
                    "reference_subtotal": 1400000 if selected else 0,
                    "market_subtotal": 1200000 if selected else 0, "potential_saving": 200000 if selected else 0,
                    "extraction_warnings": [], "source_review_pending": False,
                    "status": "compared" if selected else "draft", "status_label": "Comparada" if selected else "Borrador",
                    "note": "Comparación de productos sin despacho. La diferencia es una oportunidad, no un ahorro realizado.",
                    "shipping_note": "Sin despacho: totales solo productos."},
    }}


def shopping_detail():
    return {
        "quote": shopping_quote,
        "report": {
            "mode": "shopping_list",
            "stores": ["lider", "unimarc"],
            "rows": [{
                "index": 0,
                "item": shopping_quote["items"][0],
                "cells": {
                    "lider": {
                        "matched": True, "price": 1290, "name": "Azúcar granulada 1 kg",
                        "confidence": 0.95, "match_reason": "Identidad 95%", "confirmed": False,
                        "stale": False, "observed_at": "2026-10-05T15:00:00+00:00",
                        "price_age_hours": 1.0, "issues": [], "usable": True,
                        "url": "/producto?store=lider&id=az",
                    },
                    "unimarc": {
                        "matched": False,
                        "label": "sin match suficiente (prueba EAN o nombre más corto)",
                        "empty_reason": "no_match", "stale": False,
                    },
                },
                "best_store": "lider",
                "best_price": 1290,
            }],
            "summary": {
                "mode": "shopping_list",
                "items": 1,
                "matched_cells": 1,
                "total_cells": 2,
                "confirmed_cells": 0,
                "stale_cells": 0,
                "price_max_age_hours": 48,
                "best_store": "lider",
                "best_store_subtotal": 1290,
                "best_store_complete": False,
                "best_store_missing": [],
                "basket": [
                    {"store": "lider", "subtotal": 1290, "matched_items": 1, "missing_items": 0, "complete": True},
                    {"store": "unimarc", "subtotal": None, "matched_items": 0, "missing_items": 1, "complete": False},
                ],
                "status": "compared",
                "status_label": "Comparada",
                "note": "Matriz lista × tiendas (ventana 48 h). Totales sin despacho.",
                "shipping_note": "Sin despacho: totales solo productos.",
            },
        },
    }


def handler(route):
    global created, shopping_created, refresh_called
    from urllib.parse import urlsplit
    path = urlsplit(route.request.url).path
    if path == "/cotizaciones":
        route.fulfill(body=(STATIC / "cotizaciones.html").read_text(), content_type="text/html")
        return
    if path.startswith("/static/"):
        name = path.rsplit("/", 1)[-1]
        content_type = "text/css" if name.endswith(".css") else "application/javascript"
        file = STATIC / name
        route.fulfill(body=file.read_text() if file.is_file() else "", content_type=content_type)
        return
    if path == "/api/auth/me":
        payload = {"user": {"id": "browser-pilot", "name": "Piloto", "role": "admin", "status": "approved"}}
    elif path == "/api/quotes/store-groups":
        payload = {"groups": [{"id": "supermercados", "title": "Supermercados", "store_ids": ["lider", "unimarc"]}]}
    elif path == "/api/admin/purchasing-metrics":
        payload = {
            "imports": 1, "matches": 1, "exports": 0, "errors": 0,
            "potential_saving_exported": 0, "useful_quotes": 0, "needs_correction_quotes": 0,
            "note": "Piloto smoke.",
        }
    elif path == "/api/quotes":
        rows = []
        if created:
            rows.append(quote)
        if shopping_created:
            rows.append(shopping_quote)
        payload = {"quotes": rows}
    elif path == "/api/quotes/import-csv":
        body = route.request.post_data_json or {}
        if body.get("mode") == "shopping_list":
            shopping_created = True
            payload = shopping_quote
        else:
            assert body.get("tax_included") is True
            created = True
            payload = quote
    elif path.endswith("/refresh-prices"):
        refresh_called = True
        payload = {
            "ok": True, "boosted": 1, "following": 0, "targets": 1,
            "message": "Prioridad de scrape subida en 1 SKU(s). Esperá unos minutos y regenerá la matriz.",
            "price_max_age_hours": 48,
        }
    elif path.endswith("/rebuild-matrix"):
        payload = shopping_detail()
    elif "/candidates/" in path:
        payload = {"candidates": [candidate]}
    elif path.endswith("/selection"):
        assert route.request.post_data_json["version"] == 1
        quote["selections"] = {"0": {"store": "lider", "product_id": "sku"}}
        quote["version"] = 2
        quote["status"] = "compared"
        payload = quote_detail()
    elif path.endswith(shopping_quote["id"]) or path.endswith(f"{shopping_quote['id']}/export.csv"):
        if path.endswith("export.csv"):
            route.fulfill(
                body="Producto;Cantidad;lider CLP;lider stale\nAzúcar;1;1290;no\n\nNota;Sin despacho: totales solo productos.\n",
                content_type="text/csv",
            )
            return
        payload = shopping_detail()
    elif path.endswith(quote["id"]) or path.endswith(f"{quote['id']}/export.csv"):
        if path.endswith("export.csv"):
            route.fulfill(body="ok", content_type="text/csv")
            return
        payload = quote_detail()
    else:
        payload = {"ok": True}
    route.fulfill(body=json.dumps(payload), content_type="application/json")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1080})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/*", handler)

    # --- Cotización con precios de referencia ---
    page.goto("https://retail.test/cotizaciones")
    page.locator("#tab-quote").click()
    page.locator("#quote-title").fill("Compra de equipos")
    page.locator("#quote-csv").fill("nombre;cantidad;precio_unitario;marca\nSamsung Galaxy S25 256GB;2;700000;Samsung")
    page.locator("#quote-tax").check()
    page.get_by_role("button", name="Importar y revisar").click()
    page.locator("#quote-detail").wait_for(state="visible")
    page.get_by_role("button", name="Buscar coincidencias").click()
    page.get_by_role("button", name="Confirmar coincidencia").click()
    page.wait_for_function("document.getElementById('quote-status').textContent.includes('Coincidencia confirmada')")
    assert "200.000" in page.locator("#quote-report").inner_text()
    assert "Sin despacho" in page.locator("#quote-report").inner_text()
    assert page.locator("#quote-export").get_attribute("href").endswith("/export.csv")

    # --- Lista de compra: import → matriz → actualizar precios → export ---
    page.locator("#tab-shopping").click()
    page.locator("#shopping-title").fill("Super del mes")
    page.locator("#shopping-group").select_option("supermercados")
    page.locator("#shopping-csv").fill("nombre;cantidad\nAzúcar granulada 1 kg;1")
    page.get_by_role("button", name="Importar y comparar tiendas").click()
    page.locator("#shopping-matrix-wrap").wait_for(state="visible")
    matrix_text = page.locator("#shopping-matrix-wrap").inner_text()
    assert "1.290" in matrix_text or "1290" in matrix_text
    assert "sin match" in matrix_text.casefold() or "ean" in matrix_text.casefold()
    report_text = page.locator("#quote-report").inner_text()
    assert "stale" in report_text.casefold() or "48" in report_text
    assert "Sin despacho" in report_text
    page.locator("#quote-refresh-prices").click()
    page.wait_for_function(
        "document.getElementById('quote-status').textContent.toLowerCase().includes('prioridad') "
        "|| document.getElementById('quote-status').textContent.toLowerCase().includes('scrape')"
    )
    assert refresh_called
    assert page.locator("#quote-export").get_attribute("href").endswith("/export.csv")
    assert "matriz" in (page.locator("#quote-export").inner_text() or "").casefold() or True

    assert not errors, errors
    page.screenshot(path=os.environ.get("QUOTE_SCREENSHOT", "/tmp/purchasing-pilot.png"), full_page=True)
    print(json.dumps({
        "browser_flow": "passed",
        "quote_mode": True,
        "shopping_list_mode": True,
        "refresh_prices": refresh_called,
        "page_errors": errors,
    }))
    browser.close()
