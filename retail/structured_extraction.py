"""Extractor comercial opcional con Ollama para datos que la API no publica.

Los parsers deterministas tienen prioridad. El modelo solo completa campos
vacíos y nunca reemplaza precios o stock ya entregados por la tienda.
"""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from retail.commercial import normalize_condition, normalize_variants
from retail.models import Product


def enabled() -> bool:
    return os.environ.get("COMMERCIAL_LLM_ENABLED", "0").strip().lower() in {"1", "true", "yes"}


def _prompt(product: Product) -> str:
    source = {
        "nombre": product.name,
        "marca": product.brand,
        "descripcion": product.description,
        "caracteristicas": product.specifications,
        "precios_conocidos": {
            "normal": product.price_normal,
            "todo_medio": product.price_all_payment,
            "tarjeta": product.price_card,
        },
        "disponibilidad": product.availability,
    }
    return (
        "Extrae datos comerciales del producto. Devuelve únicamente JSON válido. "
        "Clasifica grado A/B o detalles estéticos como refurbished; devolución de cliente o caja abierta como open_box. "
        "No deduzcas valores ausentes: usa null. Estructura: "
        '{"condition":"new|refurbished|open_box|display|used|unknown",'
        '"payment_card_name":null,"installment_count":null,"installment_total":null,'
        '"financial_cae":null,"payment_conditions":null,'
        '"shipping_cost":null,"shipping_free_threshold":null,'
        '"shipping_region":null,"pickup_available":null,"low_stock":false,'
        '"only_extreme_sizes":false,"variants":[{"id":"","sku":"","name":"",'
        '"stock":null,"available":null}]}. Datos: '
        + json.dumps(source, ensure_ascii=False)[:12000]
    )


def extract(product: Product) -> dict:
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("COMMERCIAL_LLM_MODEL", "llama3.2:3b")
    body = json.dumps({
        "model": model,
        "prompt": _prompt(product),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }).encode("utf-8")
    request = Request(f"{base}/api/generate", data=body, headers={"Content-Type": "application/json"})
    timeout = max(2, min(30, int(os.environ.get("COMMERCIAL_LLM_TIMEOUT", "8"))))
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = payload.get("response") if isinstance(payload, dict) else None
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    return parsed if isinstance(parsed, dict) else {}


def apply(product: Product, data: dict) -> Product:
    condition = normalize_condition(data.get("condition"))
    if product.condition == "unknown" and condition != "unknown":
        product.condition = condition
        product.condition_source = "llm"
        product.condition_confidence = 0.75
    for field in ("payment_card_name", "payment_conditions", "shipping_region"):
        value = data.get(field)
        if getattr(product, field) is None and isinstance(value, str) and value.strip():
            setattr(product, field, value.strip()[:300])
    for field in ("installment_count", "installment_total", "shipping_cost", "shipping_free_threshold"):
        value = data.get(field)
        if getattr(product, field) is not None or isinstance(value, bool) or value in (None, ""):
            continue
        try:
            parsed = max(0, int(float(value)))
        except (TypeError, ValueError):
            continue
        setattr(product, field, parsed)
    if product.financial_cae is None and not isinstance(data.get("financial_cae"), bool):
        try:
            cae = float(str(data.get("financial_cae")).replace(",", "."))
            if 0 <= cae <= 1000:
                product.financial_cae = cae
        except (TypeError, ValueError):
            pass
    if product.pickup_available is None and isinstance(data.get("pickup_available"), bool):
        product.pickup_available = data["pickup_available"]
    if product.shipping_source is None and any(data.get(key) is not None for key in ("shipping_cost", "shipping_free_threshold")):
        product.shipping_source = "llm"
    if not product.variants:
        product.variants = normalize_variants(data.get("variants"))
    product.low_stock = bool(product.low_stock or data.get("low_stock") is True)
    product.only_extreme_sizes = bool(product.only_extreme_sizes or data.get("only_extreme_sizes") is True)
    return product


def enrich_products(products: list[Product]) -> list[Product]:
    if not enabled():
        return products
    maximum = max(0, min(50, int(os.environ.get("COMMERCIAL_LLM_MAX_PER_BATCH", "10"))))
    for product in products[:maximum]:
        try:
            apply(product, extract(product))
        except Exception:
            continue
    return products
