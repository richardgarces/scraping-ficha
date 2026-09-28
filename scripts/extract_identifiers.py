#!/usr/bin/env python3
"""
Extracción de identificadores únicos (EAN, UPC, MPN, model) desde HTML y JS.

Uso:
  python3 extract_identifiers.py --html product_page.html
Devuelve JSON con claves encontradas.
"""
import argparse
import json
import re
from typing import Dict, Optional


EAN_RE = re.compile(r"\b(97[89]\d{10}|\d{13}|\d{8})\b")
UPC_RE = re.compile(r"\b(\d{12})\b")
MPN_RE = re.compile(r"\b(MPN[:\s]*[A-Z0-9\-]+)\b", re.I)
PRELOADED_RE = re.compile(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\});", re.DOTALL)


def extract_from_html(html: str) -> Dict[str, Optional[str]]:
  from bs4 import BeautifulSoup

  soup = BeautifulSoup(html, "html.parser")
  # Buscar meta tags comunes
  meta = {}
  for name in ["gtin13", "gtin", "product:retailer_part_no", "mpn"]:
    tag = soup.find("meta", attrs={"itemprop": name}) or soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
      meta[name] = tag["content"].strip()

  text = soup.get_text(separator=" ")
  # Buscar en tablas de especificaciones
  # Extraer patrones
  ean = None
  upc = None
  mpn = None

  m = EAN_RE.search(text)
  if m:
    ean = m.group(0)
  m = UPC_RE.search(text)
  if m:
    upc = m.group(0)
  m = MPN_RE.search(text)
  if m:
    mpn = m.group(0).split(":", 1)[-1].strip()

  # Buscar JSON preloaded
  preloaded = None
  js = "\n".join([s.string or "" for s in soup.find_all("script")])
  m = PRELOADED_RE.search(js)
  if m:
    try:
      preloaded = json.loads(m.group(1))
    except Exception:
      preloaded = None

  # Priorizar meta tags
  return {
    "ean": meta.get("gtin13") or ean,
    "upc": upc,
    "mpn": meta.get("mpn") or mpn,
    "preloaded": preloaded,
  }


def main():
  p = argparse.ArgumentParser()
  p.add_argument("--html", required=True)
  args = p.parse_args()

  with open(args.html, "r", encoding="utf-8") as f:
    html = f.read()
  out = extract_from_html(html)
  print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
