#!/usr/bin/env bash
# Cron por grupo: 0 6 * * * /ruta/scraping/scripts/ofertas-diarias.sh tecnologia
# Sin argumento: recorre todos los grupos de programacion.json / Mongo (secuencial).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
source .venv/bin/activate
export MONGODB_URI="${MONGODB_URI:-mongodb://localhost:27017}"
export MONGODB_DB="${MONGODB_DB:-scraping}"
mkdir -p output logs

GRUPO="${1:-}"

read -r SOURCE PAUSE ENABLED PAUSED < <(python -c "
from retail.batch.config import load_schedule
data = load_schedule()
print(data.get('source') or 'both', data.get('pause') if data.get('pause') is not None else 3, int(bool(data.get('enabled'))), int(bool(data.get('paused'))))
")

# Un disparo nuevo no debe iniciar durante una pausa. Los procesos que ya
# estaban activos esperan cooperativamente y continúan al presionar Reanudar.
if [[ "$ENABLED" != "1" || "$PAUSED" == "1" ]]; then
  exit 0
fi

LOG="logs/ofertas-diarias.log"
if [[ -n "$GRUPO" ]]; then
  LOG="logs/ofertas-diarias-${GRUPO}.log"
fi

retail indice >> "$LOG" 2>&1 || true

if [[ -n "$GRUPO" ]]; then
  exec retail batch --grupo "$GRUPO" --source "$SOURCE" --pausa "$PAUSE" >> "$LOG" 2>&1
fi

# Opcional: todos los grupos en serie (útil a mano; el cron usa un script por grupo).
mapfile -t GROUPS < <(python -c "
from retail.batch.config import load_schedule
from retail.store_categories import enabled_group_ids
print('\n'.join(enabled_group_ids(load_schedule())))
")
if [[ ${#GROUPS[@]} -eq 0 ]]; then
  exec retail batch --source "$SOURCE" --pausa "$PAUSE" >> "$LOG" 2>&1
fi
for g in "${GROUPS[@]}"; do
  echo "=== grupo ${g} ===" >> "$LOG"
  retail batch --grupo "$g" --source "$SOURCE" --pausa "$PAUSE" >> "$LOG" 2>&1 || true
done
