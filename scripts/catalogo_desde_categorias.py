#!/usr/bin/env python3
"""Convierte las categorías de Falabella en un catálogo para `retail batch`.

Las categorías son IDs de Falabella y no sirven en las otras 23 tiendas, así que
lo que se reutiliza es el **nombre**: pasa a ser la consulta que el batch busca
en todas las tiendas. El departamento raíz queda como `category`, que es lo que
alimenta el filtro por categoría del catálogo web.

    python scripts/catalogo_desde_categorias.py --solo-hojas
    retail batch --catalogo data/catalogo_categorias.json --pausa 2
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ENTRADA = Path("data/falabella_categorias.json")
SALIDA = Path("data/catalogo_categorias.json")
# Nombres demasiado genéricos para buscarlos como texto en otras tiendas.
DEMASIADO_VAGO = {"ofertas", "novedades", "outlet", "todo", "otros", "varios", "destacados"}


def _slug(value: str) -> str:
    limpio = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return limpio[:60] or "categoria"


def _departamento(item: dict) -> str:
    """El primer ancestro, o el propio nombre si es raíz."""
    padres = item.get("parents") or []
    crudo = padres[0]["name"] if padres else (item.get("label") or item["name"])
    # Las raíces vienen como "Cocina y Baño - Cocina"; basta el departamento.
    return crudo.split(" - ")[0].strip()


def _consulta(item: dict) -> str:
    """El nombre que publica la tienda, con tildes; el slug las pierde."""
    etiqueta = item.get("label")
    if etiqueta:
        return etiqueta.split(" - ")[-1].strip()
    return (item.get("name") or "").strip()


def construir(categorias: list[dict], solo_hojas: bool, profundidad_min: int) -> list[dict]:
    con_hijos = {item.get("parent_id") for item in categorias if item.get("parent_id")}
    elegidas = []
    for item in categorias:
        nombre = _consulta(item)
        if not nombre or nombre.lower() in DEMASIADO_VAGO:
            continue
        if solo_hojas and item["id"] in con_hijos:
            continue
        if item.get("depth") is not None and item["depth"] < profundidad_min:
            continue
        elegidas.append(
            {
                "id": f"cat-{_slug(nombre)}-{item['id'].lower()}",
                "query": nombre,
                "category": _departamento(item),
                "falabella_category_id": item["id"],
            }
        )
    return elegidas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-e", "--entrada", type=Path, default=ENTRADA)
    parser.add_argument("-o", "--salida", type=Path, default=SALIDA)
    parser.add_argument("--solo-hojas", action="store_true", help="Omitir categorías que tienen subcategorías")
    parser.add_argument("--profundidad-min", type=int, default=0, help="Descartar las más generales")
    parser.add_argument("--limite", type=int, default=0, help="Cortar a N categorías")
    args = parser.parse_args()

    from retail.registry import list_stores

    categorias = json.loads(args.entrada.read_text())["categories"]
    productos = construir(categorias, args.solo_hojas, args.profundidad_min)
    if args.limite:
        productos = productos[: args.limite]

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(
        json.dumps(
            {
                "title": "Categorías Falabella en todas las tiendas",
                "comment": f"Generado desde {args.entrada} por scripts/catalogo_desde_categorias.py",
                "default_stores": [spec.id for spec in list_stores()],
                "products": productos,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    departamentos = {item["category"] for item in productos}
    print(f"{len(productos)} categorías en {len(departamentos)} departamentos -> {args.salida}")
    print(f"tiempo estimado del batch: {len(productos) * 9.3 / 3600:.1f} h a 9,3 s por categoría")


if __name__ == "__main__":
    main()
