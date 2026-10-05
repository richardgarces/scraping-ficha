#!/usr/bin/env python3
"""Offline bridge from scraping/Docling output to the retail purchasing pilot."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from retail.quote_documents import convert_document


def main():
    parser = argparse.ArgumentParser(description="Convertir una cotización PDF o JSON Docling para revisión en Retail Chile.")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--supplier", default="")
    parser.add_argument("--tax-included", action="store_true", help="Confirmación explícita: precios incluyen IVA")
    parser.add_argument("--valid-until", help="Vigencia de referencia, AAAA-MM-DD")
    args = parser.parse_args()
    try:
        quote, metadata = convert_document(args.input, title=args.title, supplier=args.supplier,
                                           tax_included=True if args.tax_included else None,
                                           valid_until=args.valid_until)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
            json.dump(quote.model_dump(mode="json"), handle, ensure_ascii=False, indent=2)
            temporary = handle.name
        os.replace(temporary, args.output)
        print(json.dumps({**metadata, "output": str(args.output)}, ensure_ascii=False))
    except ImportError:
        parser.exit(2, "Docling no está instalado en este entorno. Usa el entorno de scraping o instala el extra documents.\n")
    except (ValueError, OSError) as exc:
        parser.exit(2, f"No se creó la cotización: {exc}\n")


if __name__ == "__main__":
    main()
