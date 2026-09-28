#!/usr/bin/env python3
"""Runner que invoca los parsers Python existentes para procesar una URL.

Entrada: JSON por stdin: {"url": "https://...", "meta": {...}}
Salida: JSON por stdout con al menos {"url": ..., "status": "ok"/"error", "meta_updates": {...}}

El runner usa la CLI interna `retail` para detectar la tienda apropiada y ejecutar
el subcomando `url` que ya existe en `retail/cli.py`. Captura la salida JSON y
devuelve meta simplificada que el worker Go usará para actualizar Redis.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any


def detect_store_and_run(url: str) -> dict[str, Any]:
    # Intent: invocar 'python -m retail <store> url <url> -o -' no es trivial porque
    # la CLI espera un store_id. En su defecto intentamos iterar tiendas y usar
    # get_client() directamente via Python subprocess que llama a retail.cli.unified_main
    # pero para simplicidad invocamos 'retail' CLI globalmente y pedimos JSON a archivo.
    # Aquí implementamos fallback: usar 'retail' con cada store hasta que no falle.

    # Si el paquete está instalado en editable mode, el entrypoint es 'retail'.
    stores_cmd = [sys.executable, "-m", "retail", "tiendas"]
    try:
        out = subprocess.check_output(stores_cmd, stderr=subprocess.DEVNULL, text=True, timeout=10)
    except Exception:
        return {"url": url, "status": "error", "error": "no_cli"}

    # parsear salida de tiendas para obtener ids
    stores = []
    for line in out.splitlines():
        parts = line.split()
        if parts:
            stores.append(parts[0])

    tmp_out = "/tmp/worker_product.json"
    for store in stores:
        cmd = [sys.executable, "-m", "retail", store, "url", url, "-o", tmp_out]
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=30)
            # leer archivo generado
            with open(tmp_out, "r", encoding="utf-8") as fh:
                data = fh.read()
            try:
                obj = json.loads(data)
            except Exception:
                obj = {"raw": data}
            # simplificar meta
            meta_updates = {
                "last_scraped_at": str(int(__import__("time").time())),
                "last_status": "200",
                "store": store,
            }
            return {"url": url, "status": "ok", "meta_updates": meta_updates, "product": obj}
        except subprocess.CalledProcessError:
            continue
        except Exception:
            continue

    return {"url": url, "status": "error", "error": "no_store_match"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        url = payload.get("url")
        if not url:
            print(json.dumps({"status": "error", "error": "missing_url"}))
            return 1
        result = detect_store_and_run(url)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
