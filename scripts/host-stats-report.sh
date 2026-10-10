#!/usr/bin/env bash
# Publica CPU/RAM/disco/temp del host a Mongo (app_settings cyber_day_host_stats:{ip}).
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

# Hechos del host (CPU/OS/kernel/modelo). Necesarios cuando el reporter corre
# en Docker y /etc/os-release o hostname del contenedor no reflejan el host.
host_facts_env() {
  unset HOST_STATS_FACTS_B64 HOST_STATS_FACTS || true
  local hostname cpu_model cpu_cores cpu_arch mem_kib mem_total disk_total
  local os_pretty kernel uptime machine_model json
  hostname="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"
  cpu_model="$(
    awk -F': ' '
      /^model name[ \t]*:/ && !m { m=$2; next }
      /^Hardware[ \t]*:/ && !h { h=$2; next }
      /^Processor[ \t]*:/ && !p && $2 !~ /^[0-9]+$/ { p=$2; next }
      END { if (m != "") print m; else if (h != "") print h; else if (p != "") print p }
    ' /proc/cpuinfo 2>/dev/null || true
  )"
  cpu_cores="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || true)"
  cpu_arch="$(uname -m 2>/dev/null || true)"
  mem_kib="$(awk '/^MemTotal:/ { print $2; exit }' /proc/meminfo 2>/dev/null || true)"
  mem_total=""
  if [[ -n "${mem_kib}" && "${mem_kib}" =~ ^[0-9]+$ ]]; then
    mem_total=$((mem_kib * 1024))
  fi
  disk_total="$(df -B1 --output=size / 2>/dev/null | awk 'NR==2 { print $1 }' || true)"
  os_pretty="$(
    awk -F= '
      $1 == "PRETTY_NAME" { gsub(/"/, "", $2); print $2; exit }
    ' /etc/os-release 2>/dev/null || true
  )"
  kernel="$(uname -r 2>/dev/null || true)"
  uptime="$(awk '{ printf "%.1f", $1 }' /proc/uptime 2>/dev/null || true)"
  machine_model=""
  if [[ -r /sys/devices/virtual/dmi/id/product_name ]]; then
    machine_model="$(tr -d '\0\n' </sys/devices/virtual/dmi/id/product_name 2>/dev/null || true)"
  elif [[ -r /sys/firmware/devicetree/base/model ]]; then
    machine_model="$(tr -d '\0\n' </sys/firmware/devicetree/base/model 2>/dev/null || true)"
  elif [[ -r /proc/device-tree/model ]]; then
    machine_model="$(tr -d '\0\n' </proc/device-tree/model 2>/dev/null || true)"
  fi
  case "${machine_model,,}" in
    ""|none|"to be filled by o.e.m."|"default string") machine_model="" ;;
  esac

  json="$(HOSTNAME_JSON="${hostname}" CPU_MODEL_JSON="${cpu_model}" \
    CPU_CORES_JSON="${cpu_cores}" CPU_ARCH_JSON="${cpu_arch}" \
    MEM_TOTAL_JSON="${mem_total}" DISK_TOTAL_JSON="${disk_total}" \
    OS_PRETTY_JSON="${os_pretty}" KERNEL_JSON="${kernel}" \
    UPTIME_JSON="${uptime}" MACHINE_MODEL_JSON="${machine_model}" \
    python3 - <<'PY' 2>/dev/null || true
import json, os

def num(key):
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return None
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return None

def text(key):
    raw = (os.environ.get(key) or "").strip()
    return raw or None

payload = {
    "hostname": text("HOSTNAME_JSON"),
    "cpu_model": text("CPU_MODEL_JSON"),
    "cpu_cores": num("CPU_CORES_JSON"),
    "cpu_arch": text("CPU_ARCH_JSON"),
    "mem_total_bytes": num("MEM_TOTAL_JSON"),
    "disk_total_bytes": num("DISK_TOTAL_JSON"),
    "os_pretty_name": text("OS_PRETTY_JSON"),
    "kernel": text("KERNEL_JSON"),
    "uptime_seconds": num("UPTIME_JSON"),
    "machine_model": text("MACHINE_MODEL_JSON"),
}
print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
PY
)"
  if [[ -z "${json}" ]]; then
    return 0
  fi
  if base64 -w0 </dev/null >/dev/null 2>&1; then
    HOST_STATS_FACTS_B64="$(printf '%s' "${json}" | base64 -w0)"
  else
    HOST_STATS_FACTS_B64="$(printf '%s' "${json}" | base64 | tr -d '\n')"
  fi
  export HOST_STATS_FACTS_B64
}

# Temperatura del host (sysfs thermal + hwmon). Necesaria cuando el reporter
# corre en Docker sin /sys del host montado (BMAX/soyo vía docker exec).
# Orange Pi suele exponer cpu-thermal; x86 a menudo solo hwmon (k10temp/coretemp).
host_temp_env() {
  unset HOST_STATS_TEMP_C HOST_STATS_TEMP_SOURCE || true
  local best_prio=999 best_c="" best_src="" zone type raw milli c prio
  local hw chip input_file label_file label src

  _host_temp_consider() {
    # $1=prio $2=celsius $3=source
    local p="$1" val="$2" src_name="$3"
    [[ -n "${val}" && "${val}" =~ ^-?[0-9]+$ ]] || return 0
    (( val < -20 || val > 150 )) && return 0
    if (( p < best_prio )); then
      best_prio="${p}"
      best_c="${val}"
      best_src="${src_name}"
    fi
  }

  _host_temp_from_milli() {
    # $1=raw millidegrees-or-c → stdout °C entero
    local milli="$1" c
    [[ -n "${milli}" && "${milli}" =~ ^-?[0-9]+$ ]] || return 1
    # Valores pequeños (<200) ya vienen en °C (igual que host_stats.py).
    if (( milli > -200 && milli < 200 )); then
      c="${milli}"
    elif (( milli < 0 )); then
      c=$(( -((-milli + 500) / 1000) ))
    else
      c=$(( (milli + 500) / 1000 ))
    fi
    printf '%s' "${c}"
  }

  for zone in /sys/class/thermal/thermal_zone*; do
    [[ -r "${zone}/temp" && -r "${zone}/type" ]] || continue
    type="$(tr -d '\n' <"${zone}/type" 2>/dev/null || true)"
    raw="$(tr -d '\n' <"${zone}/temp" 2>/dev/null || true)"
    c="$(_host_temp_from_milli "${raw}" 2>/dev/null || true)"
    [[ -n "${c}" ]] || continue
    case "${type,,}" in
      x86_pkg_temp) prio=0 ;;
      k10temp|coretemp) prio=1 ;;
      cpu-thermal|cpu_thermal) prio=3 ;;
      soc-thermal|soc_thermal) prio=4 ;;
      *cpu*|*pkg*|*soc*) prio=10 ;;
      *gpu*|*nvme*|*wifi*) prio=80 ;;
      *) prio=50 ;;
    esac
    _host_temp_consider "${prio}" "${c}" "${type:-thermal}"
  done

  # hwmon: típico en BMAX/soyo (AMD k10temp / Intel coretemp) cuando no hay
  # thermal_zone útil visible al wrapper.
  shopt -s nullglob
  for hw in /sys/class/hwmon/hwmon*; do
    [[ -d "${hw}" ]] || continue
    chip="$(tr -d '\n' <"${hw}/name" 2>/dev/null || true)"
    [[ -n "${chip}" ]] || chip="hwmon"
    for input_file in "${hw}"/temp*_input; do
      [[ -r "${input_file}" ]] || continue
      label_file="${input_file%_input}_label"
      label=""
      if [[ -r "${label_file}" ]]; then
        label="$(tr -d '\n' <"${label_file}" 2>/dev/null || true)"
      fi
      raw="$(tr -d '\n' <"${input_file}" 2>/dev/null || true)"
      c="$(_host_temp_from_milli "${raw}" 2>/dev/null || true)"
      [[ -n "${c}" ]] || continue
      src="${chip}"
      [[ -n "${label}" ]] && src="${chip}:${label}"
      case "${label,,}:${chip,,}" in
        package*|*:x86_pkg_temp|tctl:*|tdie:*) prio=0 ;;
        *:k10temp|*:coretemp) prio=1 ;;
        core*) prio=15 ;;
        *gpu*|*nvme*|*wifi*) prio=80 ;;
        *) prio=20 ;;
      esac
      case "${chip,,}" in
        *gpu*|*nvme*|*wifi*) prio=80 ;;
      esac
      _host_temp_consider "${prio}" "${c}" "${src}"
    done
  done
  shopt -u nullglob

  if [[ -n "${best_c}" ]]; then
    HOST_STATS_TEMP_C="${best_c}"
    HOST_STATS_TEMP_SOURCE="${best_src}"
    export HOST_STATS_TEMP_C HOST_STATS_TEMP_SOURCE
  fi
}

run_once() {
  docker_df_env
  host_temp_env
  host_facts_env
  # Preferir contenedor con red a Mongo (BMAX: precios-web). El .venv del host
  # suele tener MONGODB_URI=mongodb://mongo:27017 y falla fuera de Docker.
  if command -v docker >/dev/null 2>&1 && docker inspect precios-web >/dev/null 2>&1; then
    docker exec \
      -e HOST_STATS_HOST_IP="${HOST_STATS_HOST_IP}" \
      -e CYBER_DAY_HOST_IP="${CYBER_DAY_HOST_IP}" \
      -e HOST_STATS_SECONDS="${HOST_STATS_SECONDS:-15}" \
      -e HOST_STATS_DOCKER_DF_B64="${HOST_STATS_DOCKER_DF_B64:-}" \
      -e HOST_STATS_TEMP_C="${HOST_STATS_TEMP_C:-}" \
      -e HOST_STATS_TEMP_SOURCE="${HOST_STATS_TEMP_SOURCE:-}" \
      -e HOST_STATS_FACTS_B64="${HOST_STATS_FACTS_B64:-}" \
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
      -e HOST_STATS_TEMP_C="${HOST_STATS_TEMP_C:-}" \
      -e HOST_STATS_TEMP_SOURCE="${HOST_STATS_TEMP_SOURCE:-}" \
      -e HOST_STATS_FACTS_B64="${HOST_STATS_FACTS_B64:-}" \
      worker python -m retail.host_stats --once
    return
  fi
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') host-stats: falta precios-web, .venv o precios-worker" >&2
  exit 1
}

run_once
