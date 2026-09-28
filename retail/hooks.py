"""Sistema ligero de hooks que se ejecutan sobre productos justo antes de guardar.

Activación: export.py ejecutará `apply_hooks(products)` si `RUN_HOOKS=1` en el
entorno. Los hooks usan los scripts en `scripts/` para normalizar categorías,
extraer identificadores y buscar matches en Qdrant.

Los hooks deben ser rápidos o tolerantes a timeout para no bloquear el scraper.
"""
from __future__ import annotations

import os
import json
import subprocess
from typing import List

from retail.models import Product


def _run_script(cmd: list[str], timeout: int = 5) -> dict | None:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = proc.stdout.strip()
        if not out:
            return None
        try:
            return json.loads(out)
        except Exception:
            return None
    except Exception:
        return None


def hook_extract_identifiers(product: Product) -> Product:
    # Extrae EAN/UPC/MPN desde `description` o `specifications` rápida con script
    text = product.description or ""
    specs = " | ".join(f"{k}: {v}" for k, v in (product.specifications or {}).items())
    payload = text + "\n" + specs
    # Llamar al extractor pasando contenido via stdin es más seguro; usar archivo temporal sería ideal
    # Aquí simplificamos: si el script existiera como CLI que acepta --html, no lo llamamos. Intentamos usar regex local.
    import re

    ean_re = re.compile(r"\b(97[89]\d{10}|\d{13}|\d{8})\b")
    m = ean_re.search(payload)
    if m:
        product.specifications.setdefault("ean", m.group(0))
    return product


def hook_normalize_category(product: Product) -> Product:
    # Si no hay category_id y Ollama está disponible, llamar al script
    if product.category_id:
        return product
    if os.environ.get("DISABLE_CATEGORY_HOOK"):
        return product
    cmd = ["python3", os.path.join(os.getcwd(), "scraping/scripts/normalize_categories_ollama.py"), "--title", product.name or "", "--description", product.description or "", "--breadcrumb", product.category or ""]
    resp = _run_script(cmd, timeout=6)
    if resp and isinstance(resp, dict):
        cat = resp.get("category")
        cid = resp.get("category_id")
        if cat:
            product.category = cat
        if cid:
            product.category_id = cid
    return product


def hook_entity_resolution(product: Product) -> Product:
    # Intentar resolver contra Qdrant si URL disponible y service configurado
    if os.environ.get("QDRANT_URL") is None:
        return product
    if product.product_id and product.product_id.startswith("MPM"):
        # heurística: si ya tiene MPN/EAN quizá no hace falta
        pass
    cmd = ["python3", os.path.join(os.getcwd(), "scraping/scripts/entity_resolution_qdrant.py"), "--find", json.dumps({"id": product.product_id, "title": product.name, "brand": product.brand or ""}), "--collection", os.environ.get("QDRANT_COLLECTION", "products"), "--qdrant", os.environ.get("QDRANT_URL")] 
    resp = _run_script(cmd, timeout=6)
    if resp:
        # Si hay match fuerte, anotar global id en specifications
        try:
            if isinstance(resp, list) and len(resp) > 0:
                top = resp[0]
                product.specifications.setdefault("resolved_global_id", str(top.get("id")))
        except Exception:
            pass
    return product


HOOKS = [hook_extract_identifiers, hook_normalize_category, hook_entity_resolution]


def apply_hooks(products: List[Product]) -> List[Product]:
    """Aplica hooks a la lista de productos si RUN_HOOKS=1.

    Los hooks deben ser idempotentes y tolerantes a fallos; errores son ignorados.
    """
    if os.environ.get("RUN_HOOKS") != "1":
        return products
    out = []
    for p in products:
        prod = p
        for h in HOOKS:
            try:
                prod = h(prod) or prod
            except Exception:
                # no romper la ingestión por un hook
                continue
        out.append(prod)
    return out
