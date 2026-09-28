#!/usr/bin/env python3
"""Stub runner que lee JSON desde stdin y imprime un objeto mínimo.
Usado para pruebas locales del worker Go.
"""
import sys, json, os
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
# mostrar proxies recibidos
proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
print(json.dumps({
    "meta_updates": {"last_scraped_at": str(int(__import__('time').time()))},
    "product": {"name": "stub-product", "brand": "stub", "catalog_category": "test", "store": "stub-store"},
    "proxy_used": proxy,
}))
