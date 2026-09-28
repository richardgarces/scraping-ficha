#!/usr/bin/env python3
"""Genera el listado de categorías de falabella.cl.

La lista sale del sitemap oficial, que es la fuente completa y autorizada. No
existe un endpoint con el árbol entero, así que la jerarquía es opcional: con
--jerarquia se consulta el breadcrumb de cada categoría, una petición por cada
una. Se puede cortar y retomar, porque reutiliza lo que ya esté en el JSON.

    python scripts/falabella_categorias.py
    python scripts/falabella_categorias.py --jerarquia --pausa 0.7
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INDEX = "https://www.falabella.com/static/site/sitemaps/categories/categories_cl_FA_COM-index.xml"
SALIDA = Path("data/falabella_categorias.json")
LOC_RE = re.compile(r"<loc>([^<]+)</loc>")
CATEGORY_RE = re.compile(r"/falabella-cl/category/([^/]+)/([^/?#]+)")


def _fetch(url: str) -> str:
    import httpx

    from retail.http import DEFAULT_HEADERS

    with httpx.Client(timeout=60.0, follow_redirects=True, headers=DEFAULT_HEADERS) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _nombre(slug: str) -> str:
    return slug.replace("-", " ").strip()


def descargar_categorias() -> list[dict[str, str]]:
    """Todas las categorías publicadas en el sitemap, sin repetir."""
    sitemaps = LOC_RE.findall(_fetch(INDEX)) or [INDEX]
    encontradas: dict[str, dict[str, str]] = {}
    for sitemap in sitemaps:
        for url in LOC_RE.findall(_fetch(sitemap)):
            match = CATEGORY_RE.search(url)
            if not match:
                continue
            category_id, slug = match.group(1), match.group(2)
            encontradas.setdefault(
                category_id,
                {"id": category_id, "name": _nombre(slug), "slug": slug, "url": url},
            )
    return sorted(encontradas.values(), key=lambda item: item["id"])


def agregar_jerarquia(categorias: list[dict], pausa: float, guardar) -> None:
    """Completa padres y ruta con el breadcrumb que devuelve el listado."""
    import time

    from retail.sources.falabella.client import FalabellaClient

    pendientes = [item for item in categorias if "path" not in item]
    print(f"jerarquía: {len(pendientes)} pendientes de {len(categorias)}")
    with FalabellaClient(delay=pausa) as client:
        for hechas, item in enumerate(pendientes, start=1):
            try:
                data = client.category(item["id"], item["slug"])
                # El breadcrumb viene de la hoja hacia arriba.
                cadena = list(reversed(data.get("breadcrumb") or []))
                ancestros = [
                    {"id": nodo.get("id"), "name": nodo.get("label")}
                    for nodo in cadena
                    if nodo.get("id") and nodo.get("id") != item["id"]
                ]
                # La etiqueta de la tienda trae el departamento en las raíces
                # ("Cocina y Baño - Cocina"), así que se guarda aparte del nombre.
                if cadena and cadena[-1].get("label"):
                    item["label"] = cadena[-1]["label"]
                item["parents"] = ancestros
                item["parent_id"] = ancestros[-1]["id"] if ancestros else None
                item["depth"] = len(ancestros)
                item["path"] = " / ".join([p["name"] for p in ancestros] + [item.get("label") or item["name"]])
            except Exception as exc:  # una categoría caída no bota la corrida
                item["error"] = str(exc)[:120]
            if hechas % 25 == 0:
                guardar()
                print(f"  {hechas}/{len(pendientes)} · {item.get('path') or item['id']}")
            time.sleep(pausa)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-o", "--salida", type=Path, default=SALIDA)
    parser.add_argument("--jerarquia", action="store_true", help="Consultar el breadcrumb de cada categoría")
    parser.add_argument("--pausa", type=float, default=0.7, help="Segundos entre peticiones")
    parser.add_argument("--mongo", action="store_true", help="Cargar el resultado en la colección categories")
    args = parser.parse_args()

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    previas = {}
    if args.salida.exists():
        previas = {item["id"]: item for item in json.loads(args.salida.read_text())["categories"]}

    categorias = descargar_categorias()
    print(f"sitemap: {len(categorias)} categorías")
    for item in categorias:
        anterior = previas.get(item["id"])
        if anterior and "path" in anterior:
            item.update({k: v for k, v in anterior.items() if k not in {"url", "slug"}})

    def guardar() -> None:
        payload = {
            "source": INDEX,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(categorias),
            "categories": categorias,
        }
        args.salida.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")

    guardar()
    if args.jerarquia:
        agregar_jerarquia(categorias, args.pausa, guardar)
        guardar()
    print(f"escrito {args.salida} ({len(categorias)} categorías)")

    if args.mongo:
        from retail.search import connect_repo

        repo = connect_repo()
        if repo is None:
            print("Mongo no está disponible, quedó solo el JSON")
            return
        try:
            saved = repo.save_categories("falabella", categorias)
            print(f"mongo: +{saved['upserted']} nuevas, ~{saved['modified']} actualizadas")
        finally:
            repo.close()


if __name__ == "__main__":
    main()
