from datetime import datetime, timedelta, timezone

import pytest

from retail.quotes import QuoteInput, QuoteLine, candidate_for, comparison_report, parse_csv_quote, resolve_quote_status
from retail.quote_documents import quote_from_tables

NOW = datetime(2026, 10, 5, 15, tzinfo=timezone.utc)


def document(**changes):
    return {"store": "lider", "product_id": "s25", "sku_id": "s25", "name": "Samsung Galaxy S25 256GB",
            "brand": "Samsung", "condition": "new", "price": 600000, "price_all_payment": 600000,
            "stock": 4, "updated_at": NOW, **changes}


def quote(**changes):
    return QuoteInput(title="Equipos", tax_included=True,
                      items=[QuoteLine(name="Samsung Galaxy S25 256GB", brand="Samsung", quantity=2, unit_price=700000)],
                      **changes).model_dump(mode="json")


def test_csv_chilean_prices_and_original_evidence():
    lines = parse_csv_quote("\ufeffnombre;cantidad;precio_unitario;marca\nSamsung Galaxy S25 256GB;2;$700.000;Samsung\n", "proveedor.csv")
    assert lines[0].unit_price == 700000
    assert lines[0].quantity == 2
    assert lines[0].evidence.row == 2
    assert "$700.000" in lines[0].evidence.text


def test_csv_rejects_ambiguous_prices_and_invalid_quantities():
    for value in ("10,50", "-10", "NaN", "100.5"):
        with pytest.raises(ValueError):
            parse_csv_quote(f"nombre;cantidad;precio_unitario\nSamsung Galaxy S25;1;{value}")
    with pytest.raises(ValueError):
        parse_csv_quote("nombre;cantidad\nSamsung Galaxy S25;0")


def test_reference_requires_review_and_does_not_assume_shipping():
    unreviewed = comparison_report(quote(), {}, {}, NOW)
    assert unreviewed["summary"]["compared_items"] == 0
    assert unreviewed["summary"]["status"] == "draft"
    selected = {"0": {"store": "lider", "product_id": "s25"}}
    report = comparison_report(quote(), selected, {("lider", "s25"): document()}, NOW)
    assert report["summary"]["potential_saving"] == 200000
    assert report["summary"]["complete"] is True
    assert report["summary"]["status"] == "compared"
    assert report["summary"]["shipping_included"] is False
    assert report["summary"]["realized_saving"] is None
    exported = {**quote(), "selections": selected, "exported_at": NOW.isoformat()}
    assert resolve_quote_status(exported, report) == "exported"


@pytest.mark.parametrize("changes", [
    {"name": "Samsung Galaxy S25 512GB"},
    {"condition": "refurbished"},
    {"name": "Samsung Galaxy S25 Ultra 256GB"},
])
def test_other_variants_cannot_be_confirmed(changes):
    assert candidate_for(QuoteLine.model_validate(quote()["items"][0]), document(**changes), NOW) is None


@pytest.mark.parametrize("changes", [
    {"updated_at": NOW - timedelta(days=3)}, {"updated_at": None},
    {"stock": 0}, {"stock": 1}, {"currency": "USD"},
])
def test_unusable_prices_do_not_enter_savings(changes):
    result = comparison_report(quote(), {"0": {"store": "lider", "product_id": "s25"}},
                               {("lider", "s25"): document(**changes)}, NOW)
    assert result["summary"]["compared_items"] == 0
    assert result["rows"][0]["potential_saving"] is None


def test_unknown_tax_expired_quote_and_unit_conversion_are_pending():
    selection = {"0": {"store": "lider", "product_id": "s25"}}
    for change in ({"tax_included": None}, {"valid_until": "2026-10-04"}):
        data = {**quote(), **change}
        assert comparison_report(data, selection, {("lider", "s25"): document()}, NOW)["summary"]["compared_items"] == 0
    data = quote()
    data["items"][0]["unit"] = "kg"
    # Sin masa en el nombre del catálogo: pendiente.
    assert comparison_report(data, selection, {("lider", "s25"): document()}, NOW)["summary"]["compared_items"] == 0


def test_kg_litro_metro_convert_when_catalog_declares_measure():
    selection = {"0": {"store": "lider", "product_id": "paint"}}
    data = quote()
    data["items"][0] = {
        **data["items"][0],
        "name": "Pintura látex blanca 4 L",
        "brand": "",
        "unit": "litro",
        "quantity": 2,
        "unit_price": 5000,
    }
    catalog = document(
        product_id="paint",
        name="Pintura látex blanca 4 L",
        brand="",
        price=16000,
        price_all_payment=16000,
        stock=10,
    )
    report = comparison_report(data, selection, {("lider", "paint"): catalog}, NOW)
    assert report["summary"]["compared_items"] == 1
    # 16000 / 4 L = 4000 CLP/L → 2 L × 4000 = 8000 vs 2 × 5000 = 10000
    assert report["rows"][0]["market_subtotal"] == 8000
    assert report["rows"][0]["potential_saving"] == 2000

    data["items"][0]["unit"] = "kg"
    data["items"][0]["name"] = "Arroz grado 1 2 kg"
    catalog_kg = document(
        product_id="paint",
        name="Arroz grado 1 2 kg",
        brand="",
        price=3000,
        price_all_payment=3000,
        stock=10,
    )
    report_kg = comparison_report(data, selection, {("lider", "paint"): catalog_kg}, NOW)
    assert report_kg["rows"][0]["selected"]["price"] == 1500  # 3000/2kg

    data["items"][0]["unit"] = "metro"
    data["items"][0]["name"] = "Cable UTP 100 m"
    catalog_m = document(
        product_id="paint",
        name="Cable UTP 100 m",
        brand="",
        price=50000,
        price_all_payment=50000,
        stock=10,
    )
    report_m = comparison_report(data, selection, {("lider", "paint"): catalog_m}, NOW)
    assert report_m["rows"][0]["selected"]["price"] == 500  # 50000/100m


def test_docling_tables_keep_provenance_and_report_skipped_rows():
    result, warnings = quote_from_tables([
        {"headers": ["Descripción", "Cantidad", "Precio unitario"], "page": 3,
         "rows": [["Samsung Galaxy S25 256GB", "2", "$700.000"], ["Total", "", "1,5"]]},
    ], title="Cotización", source_name="proveedor.pdf", source_sha256="a" * 64)
    assert len(result.items) == 1
    assert result.items[0].evidence.page == 3
    assert result.items[0].evidence.table == 1
    assert result.items[0].evidence.row == 2
    assert warnings


def test_gtin_checksum_is_validated():
    QuoteLine(name="Producto", gtin="4006381333931")
    with pytest.raises(ValueError):
        QuoteLine(name="Producto", gtin="4006381333932")


def test_duplicate_rows_require_combined_stock():
    data = quote()
    data["items"].append(dict(data["items"][0]))
    selected = {str(i): {"store": "lider", "product_id": "s25"} for i in range(2)}
    report = comparison_report(data, selected, {("lider", "s25"): document(stock=3)}, NOW)
    assert report["summary"]["compared_items"] == 0


def test_docling_json_conversion_without_loading_ocr(tmp_path):
    import json
    from retail.quote_documents import convert_document

    values = [["Descripción", "Cantidad", "Precio unitario"], ["Samsung Galaxy S25 256GB", "2", "700000"]]
    cells = [{"start_row_offset_idx": r, "end_row_offset_idx": r + 1,
              "start_col_offset_idx": c, "end_col_offset_idx": c + 1,
              "text": value, "column_header": r == 0} for r, row in enumerate(values) for c, value in enumerate(row)]
    document = {"schema_name": "DoclingDocument", "pages": {"1": {}},
                "tables": [{"data": {"num_rows": 2, "num_cols": 3, "table_cells": cells}, "prov": [{"page_no": 1}]}]}
    path = tmp_path / "quote.json"
    path.write_text(json.dumps(document))
    converted, metadata = convert_document(path, title="Compra")
    assert metadata["status"] == "converted_json"
    assert metadata["pages"] == 1
    assert converted.items[0].unit_price == 700000
    assert converted.items[0].evidence.page == 1
    assert len(converted.source_sha256) == 64
