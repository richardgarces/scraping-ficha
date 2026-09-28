#!/usr/bin/env python3
"""
Sitemap-based discovery: descarga sitemap.xml(s) y encola URLs en Redis schedule.

Variables de entorno:
  REDIS_URL (por defecto redis://redis:6379/0)
  SITEMAP_URLS (lista separada por comas de sitemaps a procesar)

El script añade cada URL a:
 - Redis hash `product:meta:{url}` con meta básico
 - Redis sorted set `schedule:urls` con score = next_run (unix ts)

Reglas de frecuencia (por defecto):
 - si el path o title contiene TV/televis => cada 4 horas
 - else => cada 48 horas
"""
import os
import sys
import time
import requests
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
SITEMAP_URLS = os.environ.get("SITEMAP_URLS", "").split(",") if os.environ.get("SITEMAP_URLS") else []


def default_frequency_seconds(url: str) -> int:
    p = urlparse(url)
    path = p.path.lower()
    if any(k in path for k in ("tv", "televis", "led", "oled", "smart-tv", "smarttv")):
        return 4 * 3600
    return 48 * 3600


def parse_sitemap_text(text: str):
    root = ET.fromstring(text)
    ns = {k: v for k, v in [node.split('}') for node in root.tag.split('}') if '}' in node]}
    # fallback: find all loc tags
    for loc in root.findall('.//{*}loc'):
        yield loc.text.strip()


def main():
    if not SITEMAP_URLS:
        print("Por favor exporta SITEMAP_URLS='https://tienda.cl/sitemap.xml,https://tienda2.cl/sitemap.xml'")
        sys.exit(1)

    r = redis.from_url(REDIS_URL)
    now = int(time.time())
    for sitemap in SITEMAP_URLS:
        try:
            resp = requests.get(sitemap, timeout=15)
            resp.raise_for_status()
            for url in parse_sitemap_text(resp.text):
                key = f"product:meta:{url}"
                # si no existe, añadir meta y schedule
                if not r.exists(key):
                    freq = default_frequency_seconds(url)
                    meta = {"url": url, "discovered_at": str(now), "frequency": str(freq)}
                    r.hset(key, mapping=meta)
                    r.zadd("schedule:urls", {url: now + freq})
            print(f"Procesado sitemap: {sitemap}")
        except Exception as e:
            print(f"Error procesando {sitemap}: {e}")


if __name__ == "__main__":
    main()
