from __future__ import annotations

import re
from pathlib import Path

from retail.registry import list_stores

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STORE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
PLATFORMS = ("custom", "vtex", "shopify", "magento")


def class_name_for(store_id: str) -> str:
    parts = [part for part in re.split(r"[^a-z0-9]+", store_id) if part]
    return "".join(part.capitalize() for part in parts) + "Store"


def normalize_store_id(store_id: str) -> str:
    key = store_id.strip().lower().replace("-", "_")
    if not STORE_ID_RE.match(key):
        raise ValueError("El id de tienda debe ser snake_case, por ejemplo mercadolibre")
    return key


def normalize_site(site: str) -> str:
    return site.replace("https://", "").replace("http://", "").strip("/")


def render_store_module(
    store_id: str,
    title: str,
    site: str,
    extra_category: bool = False,
    platform: str = "custom",
    brand: str | None = None,
) -> str:
    store_id = normalize_store_id(store_id)
    kind = platform.strip().lower()
    if kind not in PLATFORMS:
        raise ValueError(f"Plataforma inválida: {platform}. Usa {', '.join(PLATFORMS)}")
    template = (TEMPLATES_DIR / f"{kind}.py.tmpl").read_text(encoding="utf-8")
    default_brand = repr(brand) if brand else "None"
    return (
        template.replace("__STORE_ID__", store_id)
        .replace("__TITLE__", title)
        .replace("__SITE__", normalize_site(site))
        .replace("__CLASS_NAME__", class_name_for(store_id))
        .replace("__EXTRA_CATEGORY__", repr(extra_category))
        .replace("__DEFAULT_BRAND__", default_brand)
    )


def scaffold_store(
    store_id: str,
    title: str,
    site: str,
    extra_category: bool = False,
    platform: str = "custom",
    brand: str | None = None,
) -> Path:
    store_id = normalize_store_id(store_id)
    taken = {spec.id for spec in list_stores()}
    if store_id in taken:
        raise ValueError(f"Ya existe la tienda registrada: {store_id}")
    path = SOURCES_DIR / f"{store_id}.py"
    if path.exists():
        raise ValueError(f"Ya existe el archivo {path}")
    path.write_text(
        render_store_module(
            store_id,
            title,
            site,
            extra_category=extra_category,
            platform=platform,
            brand=brand,
        ),
        encoding="utf-8",
    )
    return path
