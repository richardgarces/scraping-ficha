#!/usr/bin/env bash
# Ops Cyber Day en Orange Pi: workers pineados + opcional secuencial del resto.
#
#   ./cyber-pi.sh start --parallel 3     # 3 pines (default)
#   ./cyber-pi.sh start --parallel 2     # 2 pines + 1 secuencial (resto)
#   ./cyber-pi.sh start                  # usa CYBER_DAY_MAX_PARALLEL o 3
#   ./cyber-pi.sh stop|restart|status|logs
#
set -euo pipefail
cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.worker.pi.yml)
PINNED3=(cyber-junio2026 cyber-oct2026 cyber-cambio-ultimo-jes)
PINNED2=(cyber-junio2026 cyber-oct2026)
SEQ_SERVICE=cyber-sequential
ALL_SERVICES=("${PINNED3[@]}" "$SEQ_SERVICE")
LEGACY_CONTAINER=precios-cyber-worker-pi
STATE_FILE=.cyber-pi-parallel

usage() {
  cat <<'EOF'
Usage:
  ./cyber-pi.sh start [--parallel 2|3] [servicio]
  ./cyber-pi.sh stop|restart|status|logs [servicio|all]
  ./cyber-pi.sh start --parallel 2   # 2 pines + secuencial (resto)
  ./cyber-pi.sh start --parallel 3   # 3 pines (default)

Env: CYBER_DAY_MAX_PARALLEL=2|3 (default 3 si no se pasa --parallel)
EOF
  exit 1
}

read_parallel() {
  local from_env="${CYBER_DAY_MAX_PARALLEL:-}"
  local from_file=""
  [[ -f "$STATE_FILE" ]] && from_file=$(tr -d '[:space:]' <"$STATE_FILE" || true)
  echo "${from_env:-${from_file:-3}}"
}

services_for_parallel() {
  local n="$1"
  case "$n" in
    2) echo "${PINNED2[*]} $SEQ_SERVICE" ;;
    3) echo "${PINNED3[*]}" ;;
    *)
      echo "parallel debe ser 2 o 3 (got: $n)" >&2
      exit 1
      ;;
  esac
}

resolve_one() {
  local sel="$1"
  case "$sel" in
    all|"") echo "" ;;
    1|junio|cyber-junio2026|cyber_junio2026) echo "cyber-junio2026" ;;
    2|oct|cyber-oct2026|cyber_oct2026) echo "cyber-oct2026" ;;
    3|cambio|cyber-cambio-ultimo-jes|cyber_cambio_ultimo_jes) echo "cyber-cambio-ultimo-jes" ;;
    seq|sequential|cyber-sequential) echo "cyber-sequential" ;;
    *)
      echo "Servicio desconocido: $sel" >&2
      usage
      ;;
  esac
}

stop_legacy_unpinned() {
  if docker ps -a --format '{{.Names}}' | grep -qx "$LEGACY_CONTAINER"; then
    echo "Parando worker legacy sin pin ($LEGACY_CONTAINER)…"
    docker stop "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
    docker update --restart=no "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
    docker rm -f "$LEGACY_CONTAINER" >/dev/null 2>&1 || true
  fi
  if docker ps -a --format '{{.Names}}' | grep -qx "precios-cyber-worker-soyo"; then
    docker stop precios-cyber-worker-soyo >/dev/null 2>&1 || true
    docker update --restart=no precios-cyber-worker-soyo >/dev/null 2>&1 || true
  fi
}

stop_not_in() {
  # Para los servicios del compose que no están en la lista deseada → stop.
  local want=("$@")
  local s
  for s in "${ALL_SERVICES[@]}"; do
    local keep=0
    local w
    for w in "${want[@]}"; do
      [[ "$s" == "$w" ]] && keep=1 && break
    done
    if [[ $keep -eq 0 ]]; then
      if [[ -n "$("${COMPOSE[@]}" ps -q "$s" 2>/dev/null || true)" ]]; then
        echo "Parando $s (fuera de parallel actual)…"
        "${COMPOSE[@]}" stop "$s" >/dev/null 2>&1 || true
      fi
    fi
  done
}

cmd=""
parallel=""
sel="all"
args=("$@")
i=0
while [[ $i -lt ${#args[@]} ]]; do
  a="${args[$i]}"
  case "$a" in
    start|stop|restart|status|logs)
      cmd="$a"
      ;;
    --parallel|-p)
      i=$((i + 1))
      parallel="${args[$i]:-}"
      ;;
    --parallel=*|-p=*)
      parallel="${a#*=}"
      ;;
    -h|--help)
      usage
      ;;
    *)
      if [[ -z "$cmd" ]]; then
        echo "Comando desconocido: $a" >&2
        usage
      fi
      sel="$a"
      ;;
  esac
  i=$((i + 1))
done

[[ -n "$cmd" ]] || usage

if [[ -z "$parallel" ]]; then
  parallel="$(read_parallel)"
fi
case "$parallel" in
  2|3) ;;
  *)
    echo "parallel inválido: $parallel" >&2
    exit 1
    ;;
esac

want=($(services_for_parallel "$parallel"))
one="$(resolve_one "$sel")"
if [[ -n "$one" ]]; then
  targets=("$one")
else
  targets=("${want[@]}")
fi

case "$cmd" in
  start)
    stop_legacy_unpinned
    echo "$parallel" >"$STATE_FILE"
    echo "Cyber Pi parallel=$parallel → ${targets[*]}"
    # Si arrancamos el set completo del modo, apagar el otro modo.
    if [[ -z "$one" ]]; then
      stop_not_in "${want[@]}"
    fi
    "${COMPOSE[@]}" up -d --no-deps "${targets[@]}"
    ;;
  stop)
    if [[ -z "$one" ]]; then
      "${COMPOSE[@]}" stop "${ALL_SERVICES[@]}" 2>/dev/null || true
    else
      "${COMPOSE[@]}" stop "${targets[@]}"
    fi
    ;;
  restart)
    stop_legacy_unpinned
    echo "$parallel" >"$STATE_FILE"
    if [[ -z "$one" ]]; then
      stop_not_in "${want[@]}"
      "${COMPOSE[@]}" up -d --no-deps "${want[@]}"
      "${COMPOSE[@]}" restart "${want[@]}"
    else
      "${COMPOSE[@]}" up -d --no-deps "${targets[@]}"
      "${COMPOSE[@]}" restart "${targets[@]}"
    fi
    ;;
  status)
    echo "parallel=$(read_parallel) (CYBER_DAY_MAX_PARALLEL=${CYBER_DAY_MAX_PARALLEL:-} state=$(cat "$STATE_FILE" 2>/dev/null || echo -))"
    docker ps -a --filter name=precios-cyber-worker-pi --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'
    for s in "${ALL_SERVICES[@]}"; do
      c=$("${COMPOSE[@]}" ps -q "$s" 2>/dev/null || true)
      if [[ -n "$c" ]]; then
        docker inspect --format "$s Health={{.State.Health.Status}} MemLimit={{.HostConfig.Memory}}" "$c" 2>/dev/null || true
      fi
    done
    names=$(docker ps --filter name=precios-cyber-worker-pi --format '{{.Names}}' | tr '\n' ' ')
    if [[ -n "${names// }" ]]; then
      # shellcheck disable=SC2086
      docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' $names 2>/dev/null || true
    fi
    uptime
    free -h | head -2
    ;;
  logs)
    if [[ -z "$one" ]]; then
      running_svcs=()
      for s in "${want[@]}"; do
        [[ -n "$("${COMPOSE[@]}" ps -q "$s" 2>/dev/null || true)" ]] && running_svcs+=("$s")
      done
      if [[ ${#running_svcs[@]} -eq 0 ]]; then
        echo "Ningún worker arriba (parallel=$parallel)"
        exit 1
      fi
      "${COMPOSE[@]}" logs -f --tail 80 "${running_svcs[@]}"
    else
      "${COMPOSE[@]}" logs -f --tail 100 "${targets[@]}"
    fi
    ;;
  *)
    usage
    ;;
esac
