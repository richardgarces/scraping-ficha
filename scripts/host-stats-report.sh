#!/usr/bin/env bash
# Publica CPU/RAM/disco/temp/potencia del host a Mongo (app_settings cyber_day_host_stats:{ip}).
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

# Potencia del host (W). RAPL energy_uj suele ser root-only; el wrapper:
# 1) lee energy_uj si es legible, 2) si no, docker nsenter al mount del host,
# 3) fallback hwmon power*_input (µW). Estado en logs/ para delta entre crons.
host_power_env() {
  unset HOST_STATS_POWER_W HOST_STATS_POWER_SOURCE || true
  local state_file="${ROOT}/logs/host-stats-power.state"
  local zone energy max_range zone_name src now prev_e prev_t dt delta watts e2 prio
  local hw chip input_file label_file label raw_uw
  local best_prio=999 best_w="" best_src=""

  _host_power_consider() {
    # $1=prio $2=watts (float/int) $3=source
    local p="$1" val="$2" src_name="$3"
    [[ -n "${val}" ]] || return 0
    # Aceptar enteros o decimales simples.
    [[ "${val}" =~ ^[0-9]+([.][0-9]+)?$ ]] || return 0
    # Rango sano ~0.05–500 W (comparar como enteros truncados).
    local as_int="${val%%.*}"
    (( as_int > 500 )) && return 0
    if (( p < best_prio )); then
      best_prio="${p}"
      best_w="${val}"
      best_src="${src_name}"
    fi
  }

  _host_rapl_energy_uj() {
    # $1=zone dir → stdout energy_uj o vacío
    local z="$1" e=""
    if [[ -r "${z}/energy_uj" ]]; then
      e="$(tr -d '\n' <"${z}/energy_uj" 2>/dev/null || true)"
      printf '%s' "${e}"
      return 0
    fi
    # energy_uj root-only: leer vía nsenter en el namespace del host (docker group).
    if command -v docker >/dev/null 2>&1; then
      e="$(
        docker run --rm --privileged --pid=host alpine:latest \
          nsenter -t 1 -m -- cat "${z}/energy_uj" 2>/dev/null || true
      )"
      e="$(printf '%s' "${e}" | tr -d '\n')"
      printf '%s' "${e}"
      return 0
    fi
    return 1
  }

  _host_rapl_max_range() {
    local z="$1" m=""
    if [[ -r "${z}/max_energy_range_uj" ]]; then
      m="$(tr -d '\n' <"${z}/max_energy_range_uj" 2>/dev/null || true)"
      printf '%s' "${m}"
      return 0
    fi
    if command -v docker >/dev/null 2>&1; then
      m="$(
        docker run --rm --privileged --pid=host alpine:latest \
          nsenter -t 1 -m -- cat "${z}/max_energy_range_uj" 2>/dev/null || true
      )"
      printf '%s' "$(printf '%s' "${m}" | tr -d '\n')"
      return 0
    fi
    return 1
  }

  now="$(date +%s)"
  # Preferir package-0 (intel-rapl:0); ignorar mmio duplicado.
  shopt -s nullglob
  for zone in /sys/class/powercap/intel-rapl:0 /sys/class/powercap/intel-rapl:*; do
    [[ -d "${zone}" ]] || continue
    [[ "${zone}" == *mmio* ]] && continue
    zone_name="$(tr -d '\n' <"${zone}/name" 2>/dev/null || true)"
    [[ -n "${zone_name}" ]] || zone_name="$(basename "${zone}")"
    # Solo dominio package (o el :0 raíz) para el anillo principal.
    case "${zone_name,,}" in
      package*|psys|platform) ;;
      *)
        # Permitir intel-rapl:0 aunque el name falle.
        [[ "$(basename "${zone}")" == "intel-rapl:0" ]] || continue
        ;;
    esac
    energy="$(_host_rapl_energy_uj "${zone}" || true)"
    [[ -n "${energy}" && "${energy}" =~ ^[0-9]+$ ]] || continue
    src="rapl:${zone_name}"
    max_range="$(_host_rapl_max_range "${zone}" || true)"
    prev_e="" prev_t=""
    if [[ -r "${state_file}" ]]; then
      # Formato: source energy_uj epoch
      while read -r s e t _; do
        [[ "${s}" == "${src}" ]] || continue
        prev_e="${e}"
        prev_t="${t}"
        break
      done <"${state_file}"
    fi
    # Persistir muestra actual (aunque aún no haya watts).
    {
      echo "${src} ${energy} ${now}"
      if [[ -r "${state_file}" ]]; then
        while read -r s e t _; do
          [[ "${s}" == "${src}" ]] && continue
          [[ -n "${s}" ]] && echo "${s} ${e} ${t}"
        done <"${state_file}"
      fi
    } >"${state_file}.tmp" 2>/dev/null || true
    mv -f "${state_file}.tmp" "${state_file}" 2>/dev/null || true

    if [[ -n "${prev_e}" && -n "${prev_t}" && "${prev_e}" =~ ^[0-9]+$ && "${prev_t}" =~ ^[0-9]+$ ]]; then
      dt=$(( now - prev_t ))
      if (( dt >= 5 && dt <= 7200 )); then
        if (( energy >= prev_e )); then
          delta=$(( energy - prev_e ))
        elif [[ -n "${max_range}" && "${max_range}" =~ ^[0-9]+$ ]] && (( max_range > 0 )); then
          delta=$(( max_range - prev_e + energy ))
        else
          delta=-1
        fi
        if (( delta >= 0 )); then
          # watts = (µJ delta / 1e6) / dt  → awk con C locale (evitar coma decimal).
          watts="$(LC_ALL=C awk -v d="${delta}" -v t="${dt}" 'BEGIN{ printf "%.2f", (d/1000000.0)/t }' 2>/dev/null || true)"
          _host_power_consider 0 "${watts}" "${src}"
        fi
      fi
    elif [[ -z "${prev_e}" ]]; then
      # Primera corrida: muestreo corto para no esperar al próximo cron.
      sleep 0.8
      e2="$(_host_rapl_energy_uj "${zone}" || true)"
      if [[ -n "${e2}" && "${e2}" =~ ^[0-9]+$ ]]; then
        watts="$(LC_ALL=C awk -v a="${energy}" -v b="${e2}" 'BEGIN{ printf "%.2f", (b-a)/1000000.0/0.8 }' 2>/dev/null || true)"
        _host_power_consider 0 "${watts}" "${src}"
        {
          echo "${src} ${e2} $(date +%s)"
        } >"${state_file}" 2>/dev/null || true
      fi
    fi
    # Con package-0 basta.
    break
  done

  # Fallback: hwmon power*_input (microwatts), p.ej. amdgpu PPT en BMAX.
  if [[ -z "${best_w}" ]]; then
    for hw in /sys/class/hwmon/hwmon*; do
      [[ -d "${hw}" ]] || continue
      chip="$(tr -d '\n' <"${hw}/name" 2>/dev/null || true)"
      [[ -n "${chip}" ]] || chip="hwmon"
      for input_file in "${hw}"/power*_input; do
        [[ -r "${input_file}" ]] || continue
        label_file="${input_file%_input}_label"
        label=""
        if [[ -r "${label_file}" ]]; then
          label="$(tr -d '\n' <"${label_file}" 2>/dev/null || true)"
        fi
        raw_uw="$(tr -d '\n' <"${input_file}" 2>/dev/null || true)"
        [[ -n "${raw_uw}" && "${raw_uw}" =~ ^[0-9]+$ ]] || continue
        watts="$(LC_ALL=C awk -v u="${raw_uw}" 'BEGIN{ printf "%.2f", u/1000000.0 }' 2>/dev/null || true)"
        src="${chip}"
        [[ -n "${label}" ]] && src="${chip}:${label}"
        case "${label,,}:${chip,,}" in
          ppt:*|package*:*|*:amdgpu) prio=1 ;;
          *) prio=20 ;;
        esac
        case "${chip,,}" in
          *nvme*|*wifi*) prio=80 ;;
        esac
        _host_power_consider "${prio}" "${watts}" "${src}"
      done
    done
  fi
  shopt -u nullglob

  if [[ -n "${best_w}" ]]; then
    HOST_STATS_POWER_W="${best_w}"
    HOST_STATS_POWER_SOURCE="${best_src}"
    export HOST_STATS_POWER_W HOST_STATS_POWER_SOURCE
  fi
}

run_once() {
  docker_df_env
  host_temp_env
  host_power_env
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
      -e HOST_STATS_POWER_W="${HOST_STATS_POWER_W:-}" \
      -e HOST_STATS_POWER_SOURCE="${HOST_STATS_POWER_SOURCE:-}" \
      -e HOST_STATS_FACTS_B64="${HOST_STATS_FACTS_B64:-}" \
      precios-web python -m retail.host_stats --once
    return
  fi
  if [[ -f "${ROOT}/.venv/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT}/.venv/bin/activate"
    # Si el wrapper ya midió potencia, exportarla; si no, Python puede leer sysfs.
    export HOST_STATS_POWER_W="${HOST_STATS_POWER_W:-}"
    export HOST_STATS_POWER_SOURCE="${HOST_STATS_POWER_SOURCE:-}"
    export HOST_STATS_RAPL_STATE_FILE="${ROOT}/logs/host-stats-rapl-py.state"
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
      -e HOST_STATS_POWER_W="${HOST_STATS_POWER_W:-}" \
      -e HOST_STATS_POWER_SOURCE="${HOST_STATS_POWER_SOURCE:-}" \
      -e HOST_STATS_FACTS_B64="${HOST_STATS_FACTS_B64:-}" \
      worker python -m retail.host_stats --once
    return
  fi
  echo "$(date '+%Y-%m-%dT%H:%M:%S%z') host-stats: falta precios-web, .venv o precios-worker" >&2
  exit 1
}

run_once
