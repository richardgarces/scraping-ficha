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
    "items": [{"name": "Samsung Galaxy S25 256GB", "brand": "Samsung", "quantity": 2,
               "unit_price": 700000, "unit": "unidad", "condition": "new", "gtin": "",
               "evidence": {"source": "lista.csv", "row": 2, "text": "Samsung Galaxy S25 256GB | 2 | 700000"}}],
    "created_at": "2026-10-05T15:00:00+00:00", "selections": {}, "status": "draft",
}
candidate = {"store": "lider", "product_id": "sku", "name": "Samsung Galaxy S25 256GB",
             "price": 600000, "confidence": .95, "observed_at": "2026-10-05T15:00:00+00:00",
             "issues": [], "usable": True, "advice": {"reason": "Historial todavía insuficiente."}}
created = False


def detail():
    selected = bool(quote["selections"])
    return {"quote": quote, "report": {
        "rows": [{"item": quote["items"][0], "selected": candidate if selected else None,
                  "issues": [] if selected else ["Confirma una coincidencia válida del catálogo."]}],
        "summary": {"items": 1, "compared_items": int(selected), "confirmed_items": int(selected),
                    "reference_subtotal": 1400000 if selected else 0,
                    "market_subtotal": 1200000 if selected else 0, "potential_saving": 200000 if selected else 0,
                    "extraction_warnings": [], "source_review_pending": False,
                    "status": "compared" if selected else "draft", "status_label": "Comparada" if selected else "Borrador",
                    "note": "Comparación de productos sin despacho. La diferencia es una oportunidad, no un ahorro realizado."},
    }}


def handler(route):
    global created
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
        payload = {"user": {"id": "browser-pilot", "name": "Piloto", "role": "user", "status": "approved"}}
    elif path == "/api/quotes":
        payload = {"quotes": [quote] if created else []}
    elif path == "/api/quotes/import-csv":
        assert route.request.post_data_json["tax_included"] is True
        created = True
        payload = quote
    elif "/candidates/" in path:
        payload = {"candidates": [candidate]}
    elif path.endswith("/selection"):
        assert route.request.post_data_json["version"] == 1
        quote["selections"] = {"0": {"store": "lider", "product_id": "sku"}}
        quote["version"] = 2
        quote["status"] = "compared"
        payload = detail()
    elif path.endswith(quote["id"]):
        payload = detail()
    else:
        payload = {"ok": True}
    route.fulfill(body=json.dumps(payload), content_type="application/json")


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1080})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/*", handler)
    page.goto("https://retail.test/cotizaciones")
    page.locator("#quote-title").fill("Compra de equipos")
    page.locator("#quote-csv").fill("nombre;cantidad;precio_unitario;marca\nSamsung Galaxy S25 256GB;2;700000;Samsung")
    page.locator("#quote-tax").check()
    page.get_by_role("button", name="Importar y revisar").click()
    page.locator("#quote-detail").wait_for(state="visible")
    page.get_by_role("button", name="Buscar coincidencias").click()
    page.get_by_role("button", name="Confirmar coincidencia").click()
    page.wait_for_function("document.getElementById('quote-status').textContent.includes('Coincidencia confirmada')")
    assert "200.000" in page.locator("#quote-report").inner_text()
    assert page.locator("#quote-export").get_attribute("href").endswith("/export.csv")
    assert not errors, errors
    page.screenshot(path=os.environ.get("QUOTE_SCREENSHOT", "/tmp/purchasing-pilot.png"), full_page=True)
    print(json.dumps({"browser_flow": "passed", "page_errors": errors}))
    browser.close()
