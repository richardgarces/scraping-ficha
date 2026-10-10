#!/usr/bin/env bash
# Publica CPU/RAM/disco del host a Mongo (app_settings cyber_day_host_stats:{ip}).
# BMAX: docker exec precios-web (o venv). soyo: venv o imagen worker.
# Uso: HOST_STATS_HOST_IP=192.168.1.198 bash scripts/host-stats-report.sh
set -euo pipefail
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT}/.env"
  set +a
fi

# Inferir IP conocida si no viene en el entorno.
if [[ -z "${HOST_STATS_HOST_IP:-}" && -z "${CYBER_DAY_HOST_IP:-}" ]]; then
  case "$(hostname -s 2>/dev/null || hostname || true)" in
    soyo*|precios-worker-soyo*) export HOST_STATS_HOST_IP=192.168.1.197 ;;
    bmax*|precios*) export HOST_STATS_HOST_IP=192.168.1.198 ;;
  esac
fi
export HOST_STATS_HOST_IP="${HOST_STATS_HOST_IP:-${CYBER_DAY_HOST_IP:-}}"
export CYBER_DAY_HOST_IP="${CYBER_DAY_HOST_IP:-${HOST_STATS_HOST_IP:-}}"
export PYTHONUNBUFFERED=1

# Docker df del host (el reporter suele correr dentro de un contenedor sin socket).
# Base64 evita romper `docker exec -e` con saltos de línea del JSON.
docker_df_env() {
  unset HOST_STATS_DOCKER_DF_B64 || true
  if ! command -v docker >/dev/null 2>&1; then
    return 0
  fi
  local raw
  raw="$(docker system df --format '{{json .}}' 2>/dev/null || true)"
  if [[ -z "${raw}" ]]; then
    return 0
  fi
  if base64 -w0 </dev/null >/dev/null 2>&1; then
    HOST_STATS_DOCKER_DF_B64="$(printf '%s' "${raw}" | base64 -w0)"
  else
    HOST_STATS_DOCKER_DF_B64="$(printf '%s' "${raw}" | base64 | tr -d '\n')"
  fi
  export HOST_STATS_DOCKER_DF_B64
}

run_once() {
  docker_df_env
  # Preferir contenedor con red a Mongo (BMAX: precios-web). El .venv del host
  # suele tener MONGODB_URI=mongodb://mongo:27017 y falla fuera de Docker.
  if command -v docker >/dev/null 2>&1 && docker inspect precios-web >/dev/null 2>&1; then
    docker exec \
      -e HOST_STATS_HOST_IP="${HOST_STATS_HOST_IP}" \
      -e CYBER_DAY_HOST_IP="${CYBER_DAY_HOST_IP}" \
      -e HOST_STATS_SECONDS="${HOST_STATS_SECONDS:-15}" \
      -e HOST_STATS_DOCKER_DF_B64="${HOST_STATS_DOCKER_DF_B64:-}" \
      precios-web python -m retail.host_stats --once
    return
  fi
  if [[ -f "${ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/.venv/bin/activate"
    python -m retail.host_stats --once
    return
  fi
  if command -v docker >/dev/null 2>&1 && docker image inspect precios-worker >/dev/null 2>&1; then
    docker compose -f "${ROOT}/docker-compose.worker.soyo.yml" run --rm --no-deps -T \
      -e HOST_STATS_HOST_IP="${HOST_STATS_HOST_IP}" \
      -e CYBER_DAY_HOST_IP="${CYBER_DAY_HOST_IP}" \
      -e HOST_STATS_DOCKER_DF_B64="${HOST_STATS_DOCKER_DF_B64:-}" \
      worker python -m retail.host_stats --once
    return
  fi
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') host-stats: falta precios-web, .venv o precios-worker" >&2
  exit 1
}

run_once
