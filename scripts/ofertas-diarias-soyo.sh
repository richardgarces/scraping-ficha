#!/usr/bin/env bash
# Cron en soyo (worker): retail batch/indice local (venv), datos en Mongo/Redis BMAX.
# Uso: ofertas-diarias-soyo.sh [grupo]
# Sin argumento: todos los grupos habilitados en serie.
# Requiere .env con MONGODB_URI / REDIS_URL apuntando a BMAX (VPN/LAN).
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs output

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

USE_DOCKER=0
if [[ -f "${ROOT}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT}/.venv/bin/activate"
elif [[ -x "${ROOT}/.venv/bin/retail" ]]; then
  export PATH="${ROOT}/.venv/bin:${PATH}"
elif command -v docker >/dev/null 2>&1 && docker image inspect precios-worker >/dev/null 2>&1; then
  USE_DOCKER=1
else
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') falta .venv o imagen precios-worker; venv: python3 -m venv .venv && .venv/bin/pip install -e .  |  docker: compose -f docker-compose.worker.soyo.yml build" >&2
  exit 1
fi

export MONGODB_URI="${MONGODB_URI:?MONGODB_URI requerido (Mongo BMAX)}"
export MONGODB_DB="${MONGODB_DB:-scraping}"
export REDIS_URL="${REDIS_URL:-}"
export PYTHONUNBUFFERED=1

# venv: retail/python locales. Docker: misma imagen del smoke (env desde .env del compose).
retail_run() {
  if [[ "$USE_DOCKER" == 1 ]]; then
    docker compose -f "${ROOT}/docker-compose.worker.soyo.yml" run --rm --no-deps -T worker retail "$@"
  else
    retail "$@"
  fi
}
py_run() {
  if [[ "$USE_DOCKER" == 1 ]]; then
    docker compose -f "${ROOT}/docker-compose.worker.soyo.yml" run --rm --no-deps -T worker python "$@"
  else
    python "$@"
  fi
}
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

read -r SOURCE PAUSE ENABLED PAUSED BUDGET < <(py_run -c '
from retail.batch.config import load_schedule
data = load_schedule()
print(
    data.get("source") or "both",
    data.get("pause") if data.get("pause") is not None else 3,
    int(bool(data.get("enabled"))),
    int(bool(data.get("paused"))),
    int(data.get("batch_budget_minutes") or 90),
)
')

if [[ "$ENABLED" != "1" ]]; then
  echo "$(stamp) programación desactivada; se omite el batch"
  exit 0
fi
if [[ "$PAUSED" == "1" ]]; then
  echo "$(stamp) corridas pausadas por el administrador; se omite el batch"
  exit 0
fi

# Máximo dos grupos pesados a la vez (mismo cupo que el wrapper BMAX).
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

# El índice es compartido: una sola renovación por día en este host.
INDEX_DAY="$(date '+%Y-%m-%d')"
INDEX_STAMP="logs/indice-${INDEX_DAY}.done"
exec 6>"logs/indice-diario.lock"
flock 6
if [[ ! -f "$INDEX_STAMP" ]]; then
  echo "$(stamp) renovando índice de productos y categorías de tiendas"
  if retail_run indice >> "$LOG" 2>&1; then
    touch "$INDEX_STAMP"
    find logs -maxdepth 1 -name 'indice-*.done' -mtime +7 -delete 2>/dev/null || true
  fi
fi
flock -u 6

# Tras SIGTERM/deploy (exit 75 = EX_TEMPFAIL) reintenta 1 vez por defecto.
# El cursor Mongo ya quedó; un proceso nuevo continúa sin «Continuar» manual.
BATCH_INTERRUPT_RETRIES="${BATCH_INTERRUPT_RETRIES:-1}"
BATCH_INTERRUPT_RETRY_DELAY="${BATCH_INTERRUPT_RETRY_DELAY:-20}"
INTERRUPT_EXIT_CODE=75

run_group_once() {
  local g="$1"
  local budget="$BUDGET"
  local -a env_prefix=()
  local rc=0
  if [[ "$g" == "retail" ]]; then
    budget="${RETAIL_FULL_BATCH_BUDGET_MINUTES:-0}"
    env_prefix=(env ADAPTIVE_SCRAPING=0)
  fi
  if [[ "$USE_DOCKER" == 1 && "$g" == "retail" ]]; then
    docker compose -f "${ROOT}/docker-compose.worker.soyo.yml" run --rm --no-deps -T \
      -e ADAPTIVE_SCRAPING=0 worker retail batch \
      --grupo "$g" \
      --source "$SOURCE" \
      --pausa "$PAUSE" \
      --presupuesto-minutos "$budget" >> "$LOG" 2>&1 || rc=$?
  else
    "${env_prefix[@]}" retail_run batch \
      --grupo "$g" \
      --source "$SOURCE" \
      --pausa "$PAUSE" \
      --presupuesto-minutos "$budget" >> "$LOG" 2>&1 || rc=$?
  fi
  return "$rc"
}

run_group() {
  local g="$1"
  local budget="$BUDGET"
  local mode="adaptativo"
  local attempt=0
  local max_attempts=$((BATCH_INTERRUPT_RETRIES + 1))
  local rc=0
  local delay=0
  if [[ "$g" == "retail" ]]; then
    budget="${RETAIL_FULL_BATCH_BUDGET_MINUTES:-0}"
    mode="completo"
  fi
  echo "$(stamp) inicio batch grupo=${g} source=${SOURCE} pausa=${PAUSE} presupuesto=${budget}m modo=${mode}"
  while (( attempt < max_attempts )); do
    attempt=$((attempt + 1))
    rc=0
    run_group_once "$g" || rc=$?
    if [[ "$rc" -eq 0 ]]; then
      echo "$(stamp) fin batch grupo=${g}"
      return 0
    fi
    if [[ "$rc" -eq "$INTERRUPT_EXIT_CODE" ]] && (( attempt < max_attempts )); then
      delay=$((BATCH_INTERRUPT_RETRY_DELAY * attempt))
      echo "$(stamp) grupo=${g} interrumpido (rc=${rc}); reintento automático ${attempt}/${BATCH_INTERRUPT_RETRIES} en ${delay}s" | tee -a "$LOG" >&2
      sleep "$delay"
      continue
    fi
    echo "$(stamp) ERROR batch grupo=${g} rc=${rc}" >&2
    return "$rc"
  done
  echo "$(stamp) ERROR batch grupo=${g} rc=${rc} (sin más reintentos)" >&2
  return "$rc"
}

if [[ -n "$GRUPO" ]]; then
  run_group "$GRUPO"
  exit $?
fi

mapfile -t GROUPS < <(py_run -c '
from retail.batch.config import load_schedule
from retail.store_categories import enabled_group_ids
print("\n".join(enabled_group_ids(load_schedule())))
')
if [[ ${#GROUPS[@]} -eq 0 ]]; then
  echo "$(stamp) inicio batch (sin grupos) source=${SOURCE} pausa=${PAUSE}"
  if retail_run batch --source "$SOURCE" --pausa "$PAUSE" >> "$LOG" 2>&1; then
    echo "$(stamp) fin batch"
    exit 0
  fi
  echo "$(stamp) ERROR batch (sin grupos)" >&2
  exit 1
fi

FAILED=0
for g in "${GROUPS[@]}"; do
  if ! run_group "$g"; then
    FAILED=1
  fi
done
if [[ "$FAILED" -ne 0 ]]; then
  echo "$(stamp) batch diario terminó con uno o más grupos en error" >&2
  exit 1
fi
echo "$(stamp) batch diario completado"
