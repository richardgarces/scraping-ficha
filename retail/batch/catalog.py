from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PACKAGE_DIR = Path(__file__).resolve().parent


def default_catalog_path() -> Path:
    return PACKAGE_DIR / "catalogo_electronicos.json"


def default_rules_path() -> Path:
    return PACKAGE_DIR / "reglas_ofertas.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    data = load_json(path or default_catalog_path())
    products = data.get("products") or []
    if not products:
        raise ValueError("El catálogo no tiene productos.")
    data["products"] = [
        {**item, "enabled": bool(item.get("enabled", True))}
        for item in products
    ]
    return data


def active_products(catalog: dict) -> list[dict]:
    return [item for item in (catalog.get("products") or []) if item.get("enabled", True)]


_ORIGIN_ID = re.compile(r"^prod-([a-z0-9_]+)-", re.I)


def catalog_origin_store(item: dict[str, Any]) -> str | None:
    """Tienda de origen de una consulta importada desde un producto guardado."""
    explicit = str(item.get("origin_store") or item.get("store") or "").strip().lower()
    if explicit:
        return explicit
    match = _ORIGIN_ID.match(str(item.get("id") or "").strip())
    return match.group(1).lower() if match else None
