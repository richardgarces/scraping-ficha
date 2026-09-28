"""Transformador PoC: convierte products.json a formato OpenCompare JSON minimal.
"""
import json
from typing import List, Dict


def product_to_opencompare(p: Dict) -> Dict:
    # Minimal mapping: name, brand, store, id, features
    features = []
    specs = p.get("specifications") or {}
    for k, v in specs.items():
        features.append({"feature_name": k, "feature_value": str(v)})

    oc = {
        "id": f"{p.get('store')}-{p.get('product_id')}",
        "title": p.get("name"),
        "brand": p.get("brand"),
        "store": p.get("store"),
        "price": p.get("price"),
        "rating": p.get("rating"),
        "reviews": p.get("reviews"),
        "features": features,
    }
    return oc


def transform_products(products: List[Dict]) -> Dict:
    items = [product_to_opencompare(p) for p in products]
    return {"version": "opencompare-poC-1", "items": items}


def main(infile: str, outfile: str):
    with open(infile, "r", encoding="utf-8") as f:
        products = json.load(f)
    oc = transform_products(products)
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(oc, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: opencompare_transform.py products.json out.json")
        raise SystemExit(1)
    main(sys.argv[1], sys.argv[2])
