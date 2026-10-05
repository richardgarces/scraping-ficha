"""Matriz lista de compra × tiendas (catálogo Mongo, sin scrape síncrono)."""
from datetime import datetime, timezone

from retail.quotes import QuoteLine, parse_csv_quote
from retail.shopping_list import (
    EMPTY_CELL_LABEL,
    matrix_export_csv,
    shopping_matrix_report,
)

NOW = datetime(2026, 10, 5, 16, tzinfo=timezone.utc)


def _doc(store, product_id, name, price, **extra):
    return {
        "store": store,
        "product_id": product_id,
        "sku_id": product_id,
        "name": name,
        "brand": extra.pop("brand", ""),
        "condition": "new",
        "price": price,
        "price_all_payment": price,
        "stock": extra.pop("stock", 20),
        "currency": "CLP",
        "updated_at": NOW,
        **extra,
    }


def test_shopping_list_csv_allows_optional_price_and_quantity():
    lines = parse_csv_quote(
        "nombre;cantidad;marca\n"
        "Azúcar granulada 1 kg;2;Iansa\n"
        "Café molido 500 g;;Juan Valdez\n"
        "Papel higiénico 12 un;1;\n"
    )
    assert len(lines) == 3
    assert lines[0].unit_price is None
    assert lines[0].quantity == 2
    assert lines[1].quantity == 1  # default
    assert lines[2].name.startswith("Papel")


def test_shopping_list_csv_parses_combined_quantity_unit_comma():
    lines = parse_csv_quote("nombre,cantidad,marca\nazúcar,1 kg,lanza\n")
    assert lines[0].quantity == 1
    assert lines[0].unit == "kg"
    assert lines[0].brand == "lanza"


def test_matrix_three_items_three_stores_and_basket_total():
    quote = {
        "mode": "shopping_list",
        "store_group": "supermercados",
        "title": "Super",
        "tax_included": True,
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
            {"name": "Café molido 500 g", "quantity": 2, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
            {"name": "Papel higiénico 12 un", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
        ],
    }
    stores = ["lider", "unimarc", "tottus"]
    documents = {
        ("lider", "az"): _doc("lider", "az", "Azúcar granulada 1 kg", 1290),
        ("unimarc", "az"): _doc("unimarc", "az", "Azúcar granulada 1 kg", 1190),
        ("tottus", "az"): _doc("tottus", "az", "Azúcar granulada 1 kg", 1350),
        ("lider", "cf"): _doc("lider", "cf", "Café molido 500 g", 4500),
        ("unimarc", "cf"): _doc("unimarc", "cf", "Café molido 500 g", 4200),
        # tottus sin café
        ("lider", "ph"): _doc("lider", "ph", "Papel higiénico 12 un", 5990),
        ("unimarc", "ph"): _doc("unimarc", "ph", "Papel higiénico 12 un", 6200),
        ("tottus", "ph"): _doc("tottus", "ph", "Papel higiénico 12 un", 5800),
    }
    store_matches = {
        "0": {
            "lider": {"store": "lider", "product_id": "az", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "az", "confirmed": False},
            "tottus": {"store": "tottus", "product_id": "az", "confirmed": False},
        },
        "1": {
            "lider": {"store": "lider", "product_id": "cf", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "cf", "confirmed": False},
        },
        "2": {
            "lider": {"store": "lider", "product_id": "ph", "confirmed": False},
            "unimarc": {"store": "unimarc", "product_id": "ph", "confirmed": False},
            "tottus": {"store": "tottus", "product_id": "ph", "confirmed": False},
        },
    }
    report = shopping_matrix_report(quote, store_matches, documents, stores=stores, now=NOW)
    assert report["stores"] == stores
    assert len(report["rows"]) == 3
    assert report["rows"][0]["cells"]["unimarc"]["price"] == 1190
    assert report["rows"][1]["cells"]["tottus"]["matched"] is False
    assert report["rows"][1]["cells"]["tottus"]["label"] == EMPTY_CELL_LABEL
    # Café ×2 en unimarc = 8400; azúcar 1190; papel 6200 → 15790
    unimarc = next(row for row in report["summary"]["basket"] if row["store"] == "unimarc")
    assert unimarc["matched_items"] == 3
    assert unimarc["subtotal"] == 1190 + 8400 + 6200
    assert unimarc["complete"] is True
    # Tottus incompleta (falta café)
    tottus = next(row for row in report["summary"]["basket"] if row["store"] == "tottus")
    assert tottus["complete"] is False
    assert tottus["missing_items"] == 1
    assert "Café" in tottus["missing_names"][0]
    # Mejor canasta completa: unimarc 15790 vs lider 1290+9000+5990=16280
    assert report["summary"]["best_store"] == "unimarc"
    assert report["summary"]["best_store_subtotal"] == 15790
    assert report["summary"]["best_store_complete"] is True
    # Mejor precio por ítem
    assert report["rows"][0]["best_store"] == "unimarc"
    assert report["rows"][0]["best_price"] == 1190
    assert report["rows"][1]["best_store"] == "unimarc"
    assert report["rows"][2]["best_store"] == "tottus"
    assert report["rows"][2]["best_price"] == 5800

    csv_text = matrix_export_csv(report)
    assert "Azúcar granulada 1 kg" in csv_text
    assert "unimarc CLP" in csv_text
    assert EMPTY_CELL_LABEL in csv_text
    assert "Mejor tienda canasta" in csv_text
    assert "unimarc" in csv_text


def test_matrix_empty_when_no_identity_match():
    quote = {
        "mode": "shopping_list",
        "store_group": "supermercados",
        "tax_included": True,
        "items": [
            {"name": "Azúcar granulada 1 kg", "quantity": 1, "unit": "unidad", "brand": "", "gtin": "", "condition": "new"},
        ],
    }
    documents = {
        ("lider", "x"): _doc("lider", "x", "Detergente líquido 3 L", 4990),
    }
    store_matches = {"0": {"lider": {"store": "lider", "product_id": "x"}}}
    report = shopping_matrix_report(quote, store_matches, documents, stores=["lider"], now=NOW)
    assert report["rows"][0]["cells"]["lider"]["matched"] is False
    assert report["summary"]["matched_cells"] == 0


def test_quote_line_optional_unit_price_still_validates_name():
    line = QuoteLine(name="Café instantáneo 100 g")
    assert line.unit_price is None
    assert line.quantity == 1
