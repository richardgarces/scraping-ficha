"""Reviewed purchasing quotes; source prices remain separate from retail history."""
from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from retail.compare import identity_match_confidence
from retail.models import Product
from retail.pricing import buy_or_wait, parse_moment
from retail.quote_units import unit_price_for_quote
from zoneinfo import ZoneInfo

MAX_ITEMS = 100
MAX_SOURCE_BYTES = 512_000
QUOTE_STATUSES = ("draft", "review", "compared", "exported")
STATUS_LABELS = {
    "draft": "Borrador",
    "review": "Revisión",
    "compared": "Comparada",
    "exported": "Exportada",
}


def column_key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).lower()
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)))


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(default="", max_length=200)
    row: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)
    table: int | None = Field(default=None, ge=1)
    text: str = Field(default="", max_length=2000)


class QuoteLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=300)
    quantity: int = Field(default=1, ge=1, le=10_000, strict=True)
    unit_price: int | None = Field(default=None, ge=1, le=1_000_000_000, strict=True)
    unit: Literal["unidad", "pack", "kg", "litro", "metro"] = "unidad"
    brand: str = Field(default="", max_length=100)
    gtin: str = Field(default="", max_length=14)
    condition: Literal["new", "refurbished", "open_box", "display", "used", "unknown"] = "new"
    evidence: Evidence | None = None

    @field_validator("name", "brand", mode="before")
    @classmethod
    def trim_text(cls, value):
        return str(value or "").strip()

    @field_validator("gtin")
    @classmethod
    def valid_gtin(cls, value):
        if not value:
            return value
        if not value.isdigit() or len(value) not in (8, 12, 13, 14):
            raise ValueError("EAN/GTIN debe contener 8, 12, 13 o 14 dígitos.")
        digits = list(map(int, value))
        checksum = sum(digit * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(digits[:-1])))
        if (10 - checksum % 10) % 10 != digits[-1]:
            raise ValueError("El dígito verificador EAN/GTIN no es válido.")
        return value


class QuoteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=150)
    supplier: str = Field(default="", max_length=150)
    source_name: str = Field(default="", max_length=200)
    source_sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")
    source_kind: Literal["manual", "csv", "docling"] = "manual"
    mode: Literal["quote", "shopping_list"] = "quote"
    store_group: str = Field(default="", max_length=80)
    store_ids: list[str] = Field(default_factory=list, max_length=50)
    currency: Literal["CLP"] = "CLP"
    tax_included: bool | None = None
    valid_until: date | None = None
    extraction_warnings: list[str] = Field(default_factory=list, max_length=100)
    source_reviewed: bool = False
    items: list[QuoteLine] = Field(min_length=1, max_length=MAX_ITEMS)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Ingresa un nombre para la cotización.")
        return value.strip()

    @field_validator("store_group", mode="before")
    @classmethod
    def trim_store_group(cls, value):
        return str(value or "").strip().lower()

    @field_validator("store_ids", mode="before")
    @classmethod
    def clean_store_ids(cls, value):
        if not value:
            return []
        return [str(item).strip().lower() for item in value if str(item).strip()]

ALIASES = {
    "name": {"name", "nombre", "producto", "descripcion", "detalle"},
    "quantity": {"quantity", "cantidad", "cant"},
    "unit_price": {"unitprice", "preciounitario", "precio", "valorunitario"},
    "brand": {"brand", "marca"},
    "gtin": {"gtin", "ean", "codigobarras"},
    "unit": {"unit", "unidad"},
}


def mapped_columns(headers: list[Any]) -> dict[str, Any]:
    result = {}
    for field, aliases in ALIASES.items():
        found = [header for header in headers if column_key(header) in aliases]
        if len(found) > 1:
            raise ValueError(f"Más de una columna corresponde a {field}.")
        if found:
            result[field] = found[0]
    if "name" not in result:
        raise ValueError("Falta la columna nombre o descripción.")
    return result


def integer_cell(value: Any, *, money: bool = False) -> int:
    text = str(value).strip()
    if money:
        text = re.sub(r"^(?:CLP\s*|\$\s*)", "", text, flags=re.I)
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
            text = text.replace(".", "")
    if not re.fullmatch(r"\d+", text):
        raise ValueError("Usa enteros; precios CLP como 10990 o $10.990.")
    return int(text)


def line_from_cells(cells: dict, columns: dict, evidence: Evidence) -> QuoteLine:
    values = {field: str(cells.get(header, "") or "").strip() for field, header in columns.items()}
    for field in ("quantity", "unit_price"):
        if values.get(field):
            values[field] = integer_cell(values[field], money=field == "unit_price")
        else:
            values.pop(field, None)
    if not values.get("unit"):
        values.pop("unit", None)
    return QuoteLine(**values, evidence=evidence)


def parse_csv_quote(text: str, source: str = "lista.csv") -> list[QuoteLine]:
    if len(text.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise ValueError("El archivo supera 512 KB.")
    clean = text.lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(clean[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(clean), dialect=dialect)
    columns = mapped_columns(reader.fieldnames or [])
    lines = []
    for number, cells in enumerate(reader, start=2):
        if not any(str(value or "").strip() for value in cells.values()):
            continue
        if len(lines) >= MAX_ITEMS:
            raise ValueError("La lista admite como máximo 100 productos.")
        if None in cells:
            raise ValueError(f"Fila {number}: hay columnas adicionales sin encabezado.")
        try:
            lines.append(line_from_cells(cells, columns, Evidence(
                source=source, row=number, text=" | ".join(str(v or "") for v in cells.values())[:2000],
            )))
        except ValueError as exc:
            raise ValueError(f"Fila {number}: {exc}") from exc
    if not lines:
        raise ValueError("La lista no contiene productos.")
    return lines


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def product_from_document(doc: dict) -> Product:
    fields = Product.__dataclass_fields__
    values = {key: value for key, value in doc.items() if key in fields}
    values.setdefault("product_id", str(doc.get("product_id") or ""))
    values.setdefault("sku_id", str(doc.get("sku_id") or doc.get("product_id") or ""))
    values.setdefault("name", str(doc.get("name") or ""))
    return Product(**values)


def candidate_for(line: QuoteLine, doc: dict, now: datetime | None = None) -> dict | None:
    now = now or datetime.now(timezone.utc)
    desired = Product(product_id="quote", sku_id="quote", name=line.name, brand=line.brand,
                      condition=line.condition, specifications={"ean": line.gtin} if line.gtin else {})
    try:
        product = product_from_document(doc)
        confidence, method = identity_match_confidence(desired, product)
    except (TypeError, ValueError, OverflowError):
        return None
    if confidence < 0.8 or not product.store or not product.product_id:
        return None
    price = product.price_all_payment or product.price
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return None
    observed = parse_moment(doc.get("updated_at") or doc.get("scraped_at"))
    if observed and observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    fresh = bool(observed and now - timedelta(hours=48) <= observed <= now + timedelta(minutes=10))
    availability = column_key(product.availability)
    unavailable = product.stock == 0 or availability in {"agotado", "sinstock", "outofstock", "unavailable", "nodisponible"}
    verified_stock = isinstance(product.stock, int) and not isinstance(product.stock, bool) and product.stock >= line.quantity
    available = verified_stock or (line.quantity == 1 and availability in {"disponible", "available", "instock", "enstock"})
    unit_ok, unit_price, unit_issues = unit_price_for_quote(line.unit, int(price), product)
    issues = list(unit_issues)
    if not fresh:
        issues.append("Precio sin fecha reciente (máximo 48 horas).")
    if unavailable:
        issues.append("Producto sin stock.")
    elif not available:
        issues.append("Cantidad disponible por confirmar.")
    if product.currency != "CLP":
        issues.append("La moneda del catálogo no es CLP.")
    comparable_price = unit_price if unit_ok and unit_price else int(price)
    return {
        "store": product.store, "product_id": product.product_id, "name": product.name,
        "price": comparable_price, "currency": product.currency, "confidence": round(confidence, 3),
        "match_method": method, "observed_at": observed.isoformat() if observed else None,
        "shipping_cost": product.shipping_cost, "shipping_region": product.shipping_region,
        "stock": product.stock, "issues": issues, "usable": not issues and product.currency == "CLP",
        "advice": buy_or_wait(doc.get("price_history"), int(price), now=now),
        "unit": line.unit,
        "unit_compatible": unit_ok,
        "catalog_pack_price": int(price),
    }


def resolve_quote_status(quote: dict, report: dict | None = None) -> str:
    """Map a quote to the pilot lifecycle without inventing completed savings."""
    summary = (report or {}).get("summary") or {}
    selections = quote.get("selections") or {}
    if quote.get("exported_at") and summary.get("complete"):
        return "exported"
    if summary.get("complete"):
        return "compared"
    if selections or quote.get("updated_at") or quote.get("source_reviewed"):
        return "review"
    return "draft"


def comparison_report(quote: dict, selections: dict[str, dict], documents: dict[tuple[str, str], dict], now=None) -> dict:
    now = now or datetime.now(timezone.utc)
    expired = bool(quote.get("valid_until") and date.fromisoformat(str(quote["valid_until"])) < now.astimezone(ZoneInfo("America/Santiago")).date())
    rows = []
    quantities: dict[tuple[str, str], int] = {}
    for index, raw in enumerate(quote["items"]):
        selected = selections.get(str(index))
        if selected:
            key = selected["store"], selected["product_id"]
            quantities[key] = quantities.get(key, 0) + raw["quantity"]
    for index, raw in enumerate(quote["items"]):
        line = QuoteLine.model_validate(raw)
        selected = selections.get(str(index))
        candidate = candidate_for(line, documents.get((selected["store"], selected["product_id"]), {}), now) if selected else None
        issues = list((candidate or {}).get("issues", []))
        if not candidate:
            issues.append("Confirma una coincidencia válida del catálogo.")
        elif selected:
            total_quantity = quantities[(selected["store"], selected["product_id"])]
            stock = candidate["stock"]
            if total_quantity > line.quantity and (not isinstance(stock, int) or isinstance(stock, bool) or stock < total_quantity):
                issues.append("Confirma el stock para la cantidad total de este producto en la lista.")
        if line.unit_price is None:
            issues.append("Falta el precio unitario de referencia.")
        if quote.get("tax_included") is not True:
            issues.append("Confirma que el precio de referencia incluye IVA.")
        if expired:
            issues.append("La cotización de referencia está vencida.")
        comparable = bool(candidate and candidate["usable"] and not issues)
        reference = line.unit_price * line.quantity if line.unit_price else None
        market = candidate["price"] * line.quantity if candidate else None
        rows.append({"index": index, "item": raw, "selected": candidate, "issues": issues,
                     "comparable": comparable, "reference_subtotal": reference, "market_subtotal": market,
                     "potential_saving": reference - market if comparable else None})
    compared = [row for row in rows if row["comparable"]]
    saving = sum(row["potential_saving"] for row in compared)
    warnings = list(quote.get("extraction_warnings") or [])
    confirmed = sum(1 for row in rows if row.get("selected"))
    summary = {
        "items": len(rows), "compared_items": len(compared), "pending_items": len(rows) - len(compared),
        "confirmed_items": confirmed,
        "reference_subtotal": sum(row["reference_subtotal"] for row in compared),
        "market_subtotal": sum(row["market_subtotal"] for row in compared),
        "potential_saving": saving, "complete": len(compared) == len(rows) and (not warnings or quote.get("source_reviewed") is True),
        "source_review_pending": bool(warnings and quote.get("source_reviewed") is not True),
        "extraction_warnings": warnings,
        "shipping_included": False, "realized_saving": None,
        "note": "Comparación de productos sin despacho. La diferencia es una oportunidad, no un ahorro realizado.",
    }
    report = {"rows": rows, "summary": summary, "generated_at": now.isoformat()}
    status_source = {**quote, "selections": selections}
    summary["status"] = resolve_quote_status(status_source, report)
    summary["status_label"] = STATUS_LABELS[summary["status"]]
    return report
