#!/usr/bin/env bash
# Cron en el HOST BMAX: entra a precios-web y corre el batch por grupo.
# Uso: ofertas-diarias-bmax.sh [grupo]
# Sin argumento: todos los grupos habilitados en serie.
# No uses crontab dentro del contenedor: no hay binario crontab.
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

GRUPO="${1:-}"
LOCK="logs/ofertas-diarias.lock"
LOG="logs/ofertas-diarias.log"
if [[ -n "$GRUPO" ]]; then
  LOCK="logs/ofertas-diarias-${GRUPO}.lock"
  LOG="logs/ofertas-diarias-${GRUPO}.log"
fi

stamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(stamp) ya hay un batch en curso; se omite"
  exit 0
fi

if ! docker inspect -f '{{.State.Running}}' precios-web 2>/dev/null | grep -qx true; then
  echo "$(stamp) precios-web no está corriendo; se omite el batch" >&2
  exit 1
fi

read -r SOURCE PAUSE ENABLED PAUSED BUDGET < <(docker exec precios-web python -c '
from retail.batch.config import load_schedule
data = load_schedule()
print(data.get("source") or "both", data.get("pause") if data.get("pause") is not None else 3, int(bool(data.get("enabled"))), int(bool(data.get("paused"))), int(data.get("batch_budget_minutes") or 90))
')

if [[ "$ENABLED" != "1" ]]; then
  echo "$(stamp) programación desactivada; se omite el batch"
  exit 0
fi
if [[ "$PAUSED" == "1" ]]; then
  echo "$(stamp) corridas pausadas por el administrador; se omite el batch"
  exit 0
fi

# Máximo dos grupos pesados a la vez. Los demás esperan su turno sin cargar
# Python, Mongo ni las tiendas. Esto evita que 19 crons compitan entre sí.
if [[ -n "$GRUPO" ]]; then
  exec 8>"logs/ofertas-slot-1.lock"
  exec 7>"logs/ofertas-slot-2.lock"
  QUEUE_DEADLINE=$((SECONDS + ${BATCH_QUEUE_WAIT_MINUTES:-1080} * 60))
  while true; do
    if flock -n 8; then
      SLOT=1
      break
    fi
    if flock -n 7; then
      SLOT=2
      break
    fi
    if (( SECONDS >= QUEUE_DEADLINE )); then
      echo "$(stamp) grupo=${GRUPO} agotó la espera por un cupo; se reintentará en la próxima corrida"
      exit 0
    fi
    sleep 30
  done
  echo "$(stamp) grupo=${GRUPO} obtuvo cupo=${SLOT}"
fi

# El índice es compartido: se renueva una sola vez por día, no una vez por grupo.
INDEX_DAY="$(date '+%Y-%m-%d')"
INDEX_STAMP="logs/indice-${INDEX_DAY}.done"
exec 6>"logs/indice-diario.lock"
flock 6
if [[ ! -f "$INDEX_STAMP" ]]; then
  echo "$(stamp) renovando índice de productos y categorías de tiendas"
  if docker exec -e PYTHONUNBUFFERED=1 precios-web retail indice >> "$LOG" 2>&1; then
    touch "$INDEX_STAMP"
    find logs -maxdepth 1 -name 'indice-*.done' -mtime +7 -delete 2>/dev/null || true
  fi
fi
flock -u 6

run_group() {
  local g="$1"
  local budget="$BUDGET"
  local mode="adaptativo"
  local -a docker_env=(-e PYTHONUNBUFFERED=1)
  if [[ "$g" == "retail" ]]; then
    # Retail siempre recorre el catálogo completo. Presupuesto 0 significa sin
    # corte por tiempo; el lock evita que el cron siguiente duplique la corrida.
    budget="${RETAIL_FULL_BATCH_BUDGET_MINUTES:-0}"
    mode="completo"
    docker_env+=(-e ADAPTIVE_SCRAPING=0)
  fi
  echo "$(stamp) inicio batch grupo=${g} source=${SOURCE} pausa=${PAUSE} presupuesto=${budget}m modo=${mode}"
  docker exec \
    "${docker_env[@]}" \
    precios-web \
    retail batch --grupo "$g" --source "$SOURCE" --pausa "$PAUSE" --presupuesto-minutos "$budget" >> "$LOG" 2>&1
  echo "$(stamp) fin batch grupo=${g}"
}

if [[ -n "$GRUPO" ]]; then
  run_group "$GRUPO"
  exit 0
fi

mapfile -t GROUPS < <(docker exec -i precios-web python - <<'PY'
from retail.batch.config import load_schedule
from retail.store_categories import enabled_group_ids
print("\n".join(enabled_group_ids(load_schedule())))
PY
)
if [[ ${#GROUPS[@]} -eq 0 ]]; then
  echo "$(stamp) inicio batch (sin grupos) source=${SOURCE} pausa=${PAUSE}"
  docker exec \
    -e PYTHONUNBUFFERED=1 \
    precios-web \
    retail batch --source "$SOURCE" --pausa "$PAUSE" >> "$LOG" 2>&1
  echo "$(stamp) fin batch"
  exit 0
fi

for g in "${GROUPS[@]}"; do
  run_group "$g" || true
done
