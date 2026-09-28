#!/usr/bin/env python3
"""
Indexado y búsqueda de similitud de productos usando embeddings y Qdrant.

Funciones clave:
 - `index_products(qdrant_url, collection_name, products)` : indexa productos
 - `find_similar(qdrant_url, collection_name, product, threshold=0.95)` : busca matches

`products` es una lista de dicts con al menos `id`, `title`, `brand` y opcional `attrs`.
"""
from typing import List, Dict, Any
import os
import hashlib


def _text_for_embedding(p: Dict[str, Any]) -> str:
  parts = [p.get("title", ""), p.get("brand", "")]
  attrs = p.get("attrs") or []
  if isinstance(attrs, dict):
    parts.append(" ".join(f"{k}:{v}" for k, v in attrs.items()))
  elif isinstance(attrs, list):
    parts.append(" ".join(attrs))
  return " ".join([s for s in parts if s])


def _make_point_id(s: str) -> int:
  # Qdrant prefers integer ids; generamos hash consistente
  h = hashlib.sha1(s.encode("utf-8")).hexdigest()
  return int(h[:15], 16)


def index_products(qdrant_url: str, collection_name: str, products: List[Dict[str, Any]], embedding_model: str = "all-MiniLM-L6-v2") -> None:
  """Calcula embeddings (sentence-transformers) y sube a Qdrant.

  Requiere: `pip install qdrant-client sentence-transformers torch`.
  """
  from qdrant_client import QdrantClient
  from qdrant_client.http import models as qm
  from sentence_transformers import SentenceTransformer

  client = QdrantClient(url=qdrant_url)
  model = SentenceTransformer(embedding_model)

  vectors = []
  payloads = []
  ids = []
  for p in products:
    text = _text_for_embedding(p)
    vec = model.encode(text)
    pid = _make_point_id(str(p.get("id")))
    ids.append(pid)
    vectors.append(vec.tolist())
    payloads.append({"brand": p.get("brand"), "source_id": p.get("id"), **(p.get("meta", {}))})

  # Crear colección si no existe
  try:
    client.get_collection(collection_name)
  except Exception:
    client.recreate_collection(collection_name, vectors_config=qm.VectorParams(size=len(vectors[0]), distance=qm.Distance.COSINE))

  client.upsert(collection_name=collection_name, points=[qm.PointStruct(id=i, vector=v, payload=pl) for i, v, pl in zip(ids, vectors, payloads)])


def find_similar(qdrant_url: str, collection_name: str, product: Dict[str, Any], top_k: int = 10, threshold: float = 0.95, embedding_model: str = "all-MiniLM-L6-v2") -> List[Dict[str, Any]]:
  from qdrant_client import QdrantClient
  from sentence_transformers import SentenceTransformer

  client = QdrantClient(url=qdrant_url)
  model = SentenceTransformer(embedding_model)

  text = _text_for_embedding(product)
  emb = model.encode(text).tolist()

  hits = client.search(collection_name=collection_name, query_vector=emb, limit=top_k)
  results = []
  for h in hits:
    score = 1.0 - h.score if hasattr(h, "score") else None
    payload = h.payload or {}
    # Si hay brand y coincide, preferir
    same_brand = False
    if payload.get("brand") and product.get("brand"):
      same_brand = payload.get("brand").strip().lower() == product.get("brand").strip().lower()
    results.append({"id": h.id, "score": score, "payload": payload, "same_brand": same_brand})

  # Filtrar por threshold (si la métrica es coseno, convertimos si es necesario)
  filtered = [r for r in results if (r["score"] is None or r["score"] >= threshold)]

  # Si no hay filtrados por threshold, devolver top-K
  return filtered if filtered else results


if __name__ == "__main__":
  import argparse
  import json

  p = argparse.ArgumentParser()
  p.add_argument("--qdrant", default=os.environ.get("QDRANT_URL", "http://localhost:6333"))
  p.add_argument("--collection", default="products")
  p.add_argument("--file", help="JSONL con productos para indexar (id,title,brand,attrs)")
  p.add_argument("--find", help="JSON con producto para buscar similitudes")
  args = p.parse_args()

  if args.file:
    with open(args.file, "r", encoding="utf-8") as f:
      prods = [json.loads(l) for l in f]
    index_products(args.qdrant, args.collection, prods)
    print("Indexación finalizada.")
  elif args.find:
    prod = json.loads(args.find)
    hits = find_similar(args.qdrant, args.collection, prod)
    print(json.dumps(hits, ensure_ascii=False, indent=2))
  else:
    print("Usa --file para indexar o --find para buscar.")
