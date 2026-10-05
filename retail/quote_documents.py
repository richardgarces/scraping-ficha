"""Convert Docling tables into reviewable purchasing references."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from retail.quotes import Evidence, MAX_ITEMS, QuoteInput, line_from_cells, mapped_columns


def tables_from_docling_json(document: dict) -> list[dict]:
    """Read exported tables without loading OCR or conversion models."""
    if document.get("schema_name") != "DoclingDocument":
        raise ValueError("El JSON no es un documento exportado por Docling.")
    tables = []
    for table in document.get("tables", []):
        data = table.get("data", {})
        rows, columns = data.get("num_rows", 0), data.get("num_cols", 0)
        if not isinstance(rows, int) or not isinstance(columns, int) or not 1 <= rows <= 1000 or not 1 <= columns <= 50:
            continue
        grid = [[""] * columns for _ in range(rows)]
        header_rows = set()
        for cell in data.get("table_cells", []):
            row, column = cell["start_row_offset_idx"], cell["start_col_offset_idx"]
            end_row, end_column = cell["end_row_offset_idx"], cell["end_col_offset_idx"]
            if not (0 <= row < end_row <= rows and 0 <= column < end_column <= columns):
                raise ValueError("La tabla Docling contiene posiciones inválidas.")
            for r in range(row, end_row):
                for c in range(column, end_column):
                    grid[r][c] = str(cell.get("text", ""))
                if cell.get("column_header"):
                    header_rows.add(r)
        header_end = max(header_rows) if header_rows else 0
        headers = [" ".join(dict.fromkeys(grid[r][column] for r in range(header_end + 1) if grid[r][column]))
                   for column in range(columns)]
        provenance = table.get("prov") or []
        tables.append({"headers": headers, "rows": grid[header_end + 1:],
                       "page": provenance[0].get("page_no") if provenance else None,
                       "first_data_row": header_end + 2})
    return tables


def quote_from_tables(tables: list[dict[str, Any]], *, title: str, source_name: str,
                      source_sha256: str, supplier: str = "", tax_included=None,
                      valid_until=None) -> tuple[QuoteInput, list[str]]:
    items = []
    warnings = []
    for index, table in enumerate(tables, start=1):
        headers = table["headers"]
        try:
            columns = mapped_columns(headers)
        except ValueError:
            warnings.append(f"Tabla {index}: encabezados no reconocidos; revisar manualmente.")
            continue
        for number, values in enumerate(table["rows"], start=table.get("first_data_row", 2)):
            if not any(str(value or "").strip() for value in values):
                continue
            if len(items) >= MAX_ITEMS:
                raise ValueError("El documento supera 100 productos; divídelo antes de importar.")
            if len(values) != len(headers):
                warnings.append(f"Tabla {index}, fila {number}: columnas inconsistentes.")
                continue
            try:
                items.append(line_from_cells(dict(zip(headers, values)), columns, Evidence(
                    source=source_name, row=number, page=table.get("page"), table=index,
                    text=" | ".join(str(value or "") for value in values)[:2000],
                )))
            except ValueError:
                warnings.append(f"Tabla {index}, fila {number}: campos inválidos; no se importó.")
    if not items:
        raise ValueError("No se encontraron filas válidas con columnas nombre/descripción y cantidades/precios reconocibles.")
    return QuoteInput(title=title, supplier=supplier, source_name=source_name,
                      source_sha256=source_sha256, source_kind="docling",
                      tax_included=tax_included, valid_until=valid_until, items=items,
                      extraction_warnings=warnings), warnings


def convert_document(path: Path, **kwargs) -> tuple[QuoteInput, dict]:
    if not path.is_file():
        raise ValueError("El documento no existe.")
    if path.stat().st_size > 20_000_000:
        raise ValueError("El documento supera 20 MB.")
    if path.suffix.lower() == ".json":
        document = json.loads(path.read_text())
        tables = tables_from_docling_json(document)
        status = "converted_json"
        page_count = len(document.get("pages", {}))
    elif path.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}:
        from docling.document_converter import DocumentConverter
        result = DocumentConverter().convert(path)
        status = str(result.status.value)
        if status not in {"success", "partial_success"}:
            raise ValueError(f"La conversión terminó con estado {status}.")
        document = result.document
        tables = []
        for table in document.tables:
            frame = table.export_to_dataframe(doc=document)
            rows = [["" if value is None else str(value) for value in row] for row in frame.itertuples(index=False, name=None)]
            tables.append({"headers": list(frame.columns), "rows": rows,
                           "page": table.prov[0].page_no if table.prov else None})
        page_count = len(document.pages)
    else:
        raise ValueError("Usa PDF, imagen o un JSON de Docling.")
    quote, warnings = quote_from_tables(tables, source_name=path.name,
                                       source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), **kwargs)
    return quote, {"status": status, "pages": page_count, "tables": len(tables),
                   "items": len(quote.items), "warnings": warnings, "review_required": True}
