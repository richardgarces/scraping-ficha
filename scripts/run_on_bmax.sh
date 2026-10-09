#!/usr/bin/env bash
# Script para ejecutarse en host BMAX (local allí). Crea venv, genera forecasts y los importa a Mongo local.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

echo "ROOT_DIR=$ROOT_DIR"
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi
if ! "$VENV_DIR/bin/python3" -c 'import numpy, pymongo' >/dev/null 2>&1; then
  "$VENV_DIR/bin/python3" -m pip install -U pip setuptools wheel
  "$VENV_DIR/bin/python3" -m pip install numpy pymongo
fi

mkdir -p "$ROOT_DIR/output"

# La tarea de cron no hereda la configuración del contenedor web.
# Exportar la configuración del host antes de resolver MongoDB.
if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

# Resuelve Mongo antes de generar: el modo real lee el historial y escribe los
# pronósticos directamente en la colección `forecasts`.
MONGODB_CREDS_FILE="${MONGODB_CREDS_FILE:-$ROOT_DIR/.mongo_creds}"
if [ -z "${MONGODB_URI:-}" ] && [ -f "$MONGODB_CREDS_FILE" ]; then
  # shellcheck disable=SC1090
  source "$MONGODB_CREDS_FILE"
fi

# En BMAX las credenciales vigentes se inyectan al contenedor web. Si la
# configuración del host no autentica, reutilizar esa URI sin imprimirla.
if command -v docker >/dev/null 2>&1 && docker inspect precios-web >/dev/null 2>&1; then
  if ! "$VENV_DIR/bin/python3" -c 'import os, sys; from urllib.parse import urlsplit; sys.exit(0 if urlsplit(os.environ.get("MONGODB_URI", "")).username else 1)'; then
    WEB_MONGODB_URI="$(docker exec precios-web python -c 'import os; print(os.environ.get("MONGODB_URI", ""))')"
    if [ -n "$WEB_MONGODB_URI" ]; then
      MONGODB_URI="$WEB_MONGODB_URI"
      MONGODB_DB="${MONGODB_DB:-$(docker exec precios-web python -c 'import os; print(os.environ.get("MONGODB_DB", "scraping"))')}"
    fi
    unset WEB_MONGODB_URI
  fi
fi

MONGODB_URI="${MONGODB_URI:-mongodb://localhost:27017}"
MONGODB_CONTAINER="${MONGODB_CONTAINER:-precios-mongo}"
if command -v docker >/dev/null 2>&1 && docker inspect "$MONGODB_CONTAINER" >/dev/null 2>&1; then
  MONGODB_HOST="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$MONGODB_CONTAINER")"
  if [ -n "$MONGODB_HOST" ]; then
    export MONGODB_URI MONGODB_HOST
    MONGODB_URI="$($VENV_DIR/bin/python3 -c '
import os
from urllib.parse import urlsplit, urlunsplit

uri = os.environ["MONGODB_URI"]
host = os.environ["MONGODB_HOST"]
parts = urlsplit(uri)
userinfo = parts.netloc.rsplit("@", 1)[0] + "@" if "@" in parts.netloc else ""
port = f":{parts.port}" if parts.port else ""
print(urlunsplit((parts.scheme, f"{userinfo}{host}{port}", parts.path, parts.query, parts.fragment)))
')"
  fi
fi
MONGODB_DB="${MONGODB_DB:-scraping}"
export MONGODB_URI MONGODB_DB

FORECAST_SAMPLE="${FORECAST_SAMPLE:-50}"
FORECAST_HORIZON="${FORECAST_HORIZON:-7}"
FORECAST_MIN_HISTORY_DAYS="${FORECAST_MIN_HISTORY_DAYS:-30}"
FORECAST_ARGS=(--sample "$FORECAST_SAMPLE" --horizon "$FORECAST_HORIZON" --min-history-days "$FORECAST_MIN_HISTORY_DAYS")
if [ "${FORECAST_SIMULATE:-0}" = "1" ]; then
  FORECAST_ARGS+=(--simulate)
fi

if [ "${FORECAST_SIMULATE:-0}" != "1" ]; then
  echo "Validating TimesFM against the last-price baseline…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/validate_timesfm.py" || true
fi

# El modo real escribe directo en Mongo. Solo la simulación produce un JSON.
# Incluye prioridad + enriquecimiento Cyber (oct/junio 2026) salvo FORECAST_INCLUDE_CYBER=0.
MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
  "$VENV_DIR/bin/python3" "$ROOT_DIR/timesfm_poc/forecast_from_mongo.py" "${FORECAST_ARGS[@]}"

if [ "${FORECAST_SIMULATE:-0}" != "1" ]; then
  echo "Ensuring experimental forecasts for Cyber oct/junio 2026 products…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" - <<'PY'
from retail.mongo import ProductRepository
from retail.cyber_forecast import ensure_cyber_list_forecasts
import os

repo = ProductRepository(os.environ["MONGODB_URI"], database=os.environ.get("MONGODB_DB", "scraping"))
try:
    stats = ensure_cyber_list_forecasts(repo, use_timesfm=True, prefer_cyber_event=True)
    print(
        "cyber forecasts:",
        f"lists={stats.get('list_ids')}",
        f"candidates={stats.get('candidates')}",
        f"written={stats.get('written')}",
        f"written_cyber_event={stats.get('written_cyber_event')}",
        f"fresh={stats.get('fresh')}",
        f"blocked={stats.get('blocked')}",
        f"missing_with_many_changes={stats.get('missing_forecast_with_many_changes')}",
    )
finally:
    repo.close()
PY
  echo "Building adaptive scraping priorities and seasonal patterns…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/build_scrape_priorities.py"
  echo "Backfilling missing product thumbnails…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/backfill_thumbnails.py"
  echo "Evaluating experimental forecast outcomes (cumplimiento diario)…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/evaluate_forecast_outcomes.py"
  echo "Evaluating predictive notifications (validation gate applies)…"
  PYTHONPATH="$ROOT_DIR" MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" \
    "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/send_predictive_alerts.py"
  echo "Done. Forecasts reales guardados directamente en Mongo (si hubo productos elegibles)."
  exit 0
fi

# pick the most recent forecasts_simulated_*.json in output/
OUTFILE="$(ls -1t "$ROOT_DIR/output/forecasts_simulated_"*.json 2>/dev/null | head -n1 || true)"
if [ -z "$OUTFILE" ]; then
  echo "ERROR: no generated forecasts file found in $ROOT_DIR/output" >&2
  exit 2
fi

echo "Generated: $OUTFILE"

MONGODB_TARGET="$($VENV_DIR/bin/python3 -c 'import os; from urllib.parse import urlsplit; p=urlsplit(os.environ["MONGODB_URI"]); print(f"{p.hostname}:{p.port or 27017}{p.path}")')"
echo "Importing to Mongo at ${MONGODB_TARGET} DB=${MONGODB_DB}"
MONGODB_URI="$MONGODB_URI" MONGODB_DB="$MONGODB_DB" "$VENV_DIR/bin/python3" "$ROOT_DIR/scripts/import_forecasts.py" "$OUTFILE"

echo "Done. Run the API on BMAX (systemd/docker) or curl the forecasts endpoint to verify."
