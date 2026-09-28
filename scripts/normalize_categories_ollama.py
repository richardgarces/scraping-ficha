#!/usr/bin/env python3
"""
Normalización de categorías vía Ollama (LLM local).

Uso básico:
  python3 normalize_categories_ollama.py --model llama2 --title "..." --breadcrumb "Home > Electrónica > TVs"

Recomendación: configurar `OLLAMA_MODEL` en el entorno o pasar `--model`.
El prompt fuerza salida JSON con campo `category` (cadena) y `category_id` (opcional).
"""
import argparse
import json
import os
import shlex
import subprocess
from typing import Dict, Optional


DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "llama2")


def call_ollama(model: str, prompt: str, timeout: int = 30) -> Optional[Dict]:
  """Llama a la CLI `ollama generate` y parsea JSON de salida.

  Nota: requiere que la CLI `ollama` esté instalada y accesible.
  """
  cmd = ["ollama", "generate", model, "--prompt", prompt, "--no-stream", "--json"]
  try:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = proc.stdout.strip()
    if not out:
      return None
    # Ollama puede emitir texto; buscamos el primer JSON en la salida
    try:
      j = json.loads(out)
      return j
    except Exception:
      # intentar extraer JSON entre la primera { y la última }
      start = out.find("{")
      end = out.rfind("}")
      if start != -1 and end != -1 and end > start:
        try:
          return json.loads(out[start : end + 1])
        except Exception:
          return None
      return None
  except FileNotFoundError:
    raise RuntimeError("CLI 'ollama' no encontrada. Instala Ollama y configura modelos locales.")


def build_prompt(title: str, description: str | None, breadcrumb: str | None, taxonomy_hint: str = "Google Merchant taxonomy") -> str:
  prompt = {
    "instruction": (
      "Clasifica el producto en una taxonomía maestra. Devuelve SOLO JSON con campos:"
      " category (cadena), category_id (opcional). No expliques texto adicional."
    ),
    "taxonomy": taxonomy_hint,
    "title": title,
    "description": description or "",
    "breadcrumb": breadcrumb or "",
    "output_format": {"category": "string", "category_id": "string|null"},
  }
  # Mandar el prompt como JSON-line para evitar ambigüedades
  return json.dumps(prompt, ensure_ascii=False)


def normalize(title: str, description: str | None = None, breadcrumb: str | None = None, model: str = DEFAULT_MODEL) -> Dict | None:
  prompt = build_prompt(title, description, breadcrumb)
  resp = call_ollama(model, prompt)
  return resp


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--model", default=DEFAULT_MODEL)
  parser.add_argument("--title", required=True)
  parser.add_argument("--description", default="")
  parser.add_argument("--breadcrumb", default="")
  args = parser.parse_args()

  out = normalize(args.title, args.description, args.breadcrumb, args.model)
  print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
  main()
