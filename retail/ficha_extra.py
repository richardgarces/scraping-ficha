"""Características, descripción y productos relacionados de una ficha.

La ficha pinta el precio al toque. Esto se pide después: si Mongo ya guardó
specs o descripción, se usan; si no, se pide el detalle a la tienda que ya
sabe leer una ficha. Relacionados salen de productos ya guardados.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from retail.models import Product, Target
from retail.parsers import strip_html

SPEC_LIMIT = 12
RELATED_LIMIT = 12
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_STOP = {
    "con",
    "para",
    "the",
    "and",
    "pack",
    "set",
    "nuevo",
    "oferta",
    "unidad",
    "unidades",
    "color",
    "colores",
}


def fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.casefold().strip()


def name_tokens(value: Any) -> set[str]:
    return {token for token in _TOKEN_RE.findall(fold(value)) if token not in _STOP and not token.isdigit()}


def specifications_of(document: dict[str, Any] | None) -> dict[str, str]:
    """Dict guardado, string aplanado o lista de atributos."""
    if not document:
        return {}
    raw = document.get("specifications")
    if not raw:
        raw = document.get("attributes")
    return _spec_map(raw)


def description_of(document: dict[str, Any] | None) -> str:
    if not document:
        return ""
    text = strip_html(document.get("description") or document.get("longDescription") or "") or ""
    return text.strip()


def needs_store_detail(document: dict[str, Any] | None) -> bool:
    return bool(
        not specifications_of(document)
        or not description_of(document)
        or not (document or {}).get("image_url")
    )


def _spec_map(raw: Any) -> dict[str, str]:
    specs: dict[str, str] = {}
    if isinstance(raw, dict):
        direct_key = raw.get("name") or raw.get("label") or raw.get("id")
        if direct_key and "value" in raw:
            direct_value = _spec_value(raw.get("value"))
            unit = _spec_value(raw.get("unit"))
            if direct_value:
                return {str(direct_key): f"{direct_value} {unit}".strip()}
        for key, value in raw.items():
            nested = _json_spec_map(value)
            if nested and fold(key) in {"specs", "specifications", "attributes", "caracteristicas"}:
                specs.update(nested)
                continue
            text = _spec_value(value)
            if key and text:
                specs[str(key)] = text
        return specs
    if isinstance(raw, str):
        parsed = _json_spec_map(raw)
        if parsed:
            return parsed
        for part in raw.split("|"):
            if ":" not in part:
                continue
            key, value = part.split(":", 1)
            key, value = key.strip(), value.strip()
            if key and value:
                specs[key] = value
        return specs
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = item.get("name") or item.get("label") or item.get("id")
            value = _spec_value(item.get("value"))
            unit = _spec_value(item.get("unit"))
            if key and value:
                specs[str(key)] = f"{value} {unit}".strip()
    return specs


def _json_spec_map(value: Any) -> dict[str, str]:
    """Convierte JSON embebido; algunas tiendas guardan la lista bajo `Specs`."""
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text[0] not in "[{":
        return {}
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return _spec_map(parsed)


def _spec_value(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        parts = [_spec_value(item) for item in value]
        return ", ".join(part for part in parts if part)
    if isinstance(value, dict):
        nested = value.get("value") or value.get("label") or value.get("name")
        return _spec_value(nested)
    return strip_html(str(value)).strip()


def enrich_from_store(document: dict[str, Any]) -> dict[str, Any]:
    """Pide la ficha de la tienda solo si faltan specs o descripción."""
    if not needs_store_detail(document):
        return {}
    store = str(document.get("store") or "").strip()
    product_id = str(document.get("product_id") or "").strip()
    if not store or not product_id:
        return {}
    try:
        from retail.registry import get_client

        client = get_client(store, delay=0, timeout=8, retries=1)
    except Exception:
        return {}
    try:
        products = client.scrape(
            Target(kind="product", product_id=product_id, raw_url=document.get("url")),
            max_pages=1,
            max_items=1,
        )
    except Exception:
        return {}
    finally:
        try:
            client.close()
        except Exception:
            pass
    product = next((item for item in products or [] if _same_product(item, product_id)), None)
    if product is None:
        return {}
    fields: dict[str, Any] = {}
    # Include rating and reviews from scraped product if available
    if product.rating is not None and document.get("rating") is None:
        try:
            fields["rating"] = float(product.rating)
        except Exception:
            fields["rating"] = product.rating
    if product.reviews is not None and document.get("reviews") is None:
        try:
            fields["reviews"] = int(product.reviews)
        except Exception:
            fields["reviews"] = product.reviews
    if product.specifications and not specifications_of(document):
        fields["specifications"] = {str(key): str(value) for key, value in product.specifications.items() if value}
    if product.description and not description_of(document):
        fields["description"] = strip_html(product.description).strip()
    if product.category and not document.get("category"):
        fields["category"] = product.category
    if product.category_id and not document.get("category_id"):
        fields["category_id"] = product.category_id
    if product.image_url and not document.get("image_url"):
        fields["image_url"] = product.image_url
    if product.image_urls:
        known = [str(value) for value in (document.get("image_urls") or []) if value]
        merged = list(dict.fromkeys([*known, *product.image_urls]))
        if merged != known:
            fields["image_urls"] = merged
    return {key: value for key, value in fields.items() if value}


def _same_product(product: Product, product_id: str) -> bool:
    wanted = str(product_id)
    return wanted in {str(product.product_id or ""), str(product.sku_id or "")}


def search_text(document: dict[str, Any]) -> str:
    tokens = list(name_tokens(document.get("name")))[:6]
    brand = fold(document.get("brand"))
    if brand and brand not in tokens:
        tokens.insert(0, brand)
    return " ".join(tokens)


def related_score(seed: dict[str, Any], candidate: dict[str, Any]) -> int | None:
    """Misma categoría, marca o tokens del nombre. El producto de la ficha no entra."""
    if (seed.get("store"), str(seed.get("product_id") or "")) == (
        candidate.get("store"),
        str(candidate.get("product_id") or ""),
    ):
        return None
    seed_code = str(seed.get("compare_code") or "")
    if seed_code and seed_code == str(candidate.get("compare_code") or ""):
        return None
    overlap = len(name_tokens(seed.get("name")) & name_tokens(candidate.get("name")))
    same_brand = bool(fold(seed.get("brand"))) and fold(seed.get("brand")) == fold(candidate.get("brand"))
    same_group = _same_group(seed, candidate)
    if overlap < 1 and not (same_brand and same_group):
        return None
    if overlap < 2 and not same_group and not same_brand:
        return None
    return overlap * 3 + (4 if same_brand else 0) + (5 if same_group else 0)


def pick_related(seed: dict[str, Any], candidates: list[dict[str, Any]], *, limit: int = RELATED_LIMIT) -> list[dict[str, Any]]:
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in candidates:
        score = related_score(seed, item)
        if score is None:
            continue
        ranked.append((score, item))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].get("price") is None, pair[1].get("price") or 0))
    return [item for _, item in ranked[:limit]]


def _group_values(item: dict[str, Any]) -> set[str]:
    values = {
        fold(item.get("category_id")),
        fold(item.get("catalog_id")),
        fold(item.get("category")),
        fold(item.get("catalog_category")),
    }
    values.discard("")
    return values


def _same_group(seed: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return bool(_group_values(seed) & _group_values(candidate))
