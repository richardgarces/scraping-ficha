#!/usr/bin/env bash
# Deploy producción — precios (EDGE=platform|builtin|auto)
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-compose.sh"

EDGE="${EDGE:-platform}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
PLATFORM_OVERRIDE="${PLATFORM_OVERRIDE:-docker-compose.prod.platform.yml}"
SOYO_ACCESS_OVERRIDE="${SOYO_ACCESS_OVERRIDE:-docker-compose.prod.soyo-access.yml}"

COMPOSE_BIN="$(detect_compose)" || { echo "ERROR: falta docker compose"; exit 1; }

# Cargar BMAX_VPN_IP / HOST_BATCH_CRON desde .env si existen (sin source completo).
if [[ -f "${ROOT_DIR}/.env" ]]; then
  _vip="$(grep -E '^BMAX_VPN_IP=' "${ROOT_DIR}/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -z "${BMAX_VPN_IP:-}" && -n "${_vip}" ]] && BMAX_VPN_IP="${_vip}"
  _hb="$(grep -E '^HOST_BATCH_CRON=' "${ROOT_DIR}/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -z "${HOST_BATCH_CRON:-}" && -n "${_hb}" ]] && HOST_BATCH_CRON="${_hb}"
  unset _vip _hb
fi
export BMAX_VPN_IP="${BMAX_VPN_IP:-}"
export HOST_BATCH_CRON="${HOST_BATCH_CRON:-1}"

use_platform=false
case "$EDGE" in
  platform|1|yes|true) use_platform=true ;;
  builtin|app) use_platform=false ;;
  auto)
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qx platform-caddy && use_platform=true
    ;;
  *) echo "EDGE inválido: $EDGE"; exit 1 ;;
esac

# Spec con | para word-split seguro ("docker compose" = 2 palabras)
SPEC="${COMPOSE_BIN}|-f|${COMPOSE_FILE}"
if [[ "$use_platform" == true ]]; then
  [[ -f "$PLATFORM_OVERRIDE" ]] || { echo "ERROR: falta $PLATFORM_OVERRIDE"; exit 1; }
  docker network inspect platform-net >/dev/null 2>&1 || docker network create platform-net
  SPEC="${SPEC}|-f|${PLATFORM_OVERRIDE}"
  echo "==> EDGE=platform  compose=${COMPOSE_BIN}"
else
  echo "==> EDGE=builtin  compose=${COMPOSE_BIN}"
fi

# Override soyo-access: solo si el archivo existe Y BMAX_VPN_IP está definido
# (evita publicar Mongo/Redis por error en un deploy normal).
if [[ -f "${ROOT_DIR}/${SOYO_ACCESS_OVERRIDE}" ]]; then
  if [[ -n "${BMAX_VPN_IP}" ]]; then
    export BMAX_VPN_IP
    SPEC="${SPEC}|-f|${SOYO_ACCESS_OVERRIDE}"
    echo "==> soyo-access: bind Mongo/Redis en ${BMAX_VPN_IP} (puertos host 27018/6380 por defecto)"
  else
    echo "[!] ${SOYO_ACCESS_OVERRIDE} presente pero BMAX_VPN_IP vacío — override OMITIDO (seguro)"
  fi
fi

mkdir -p "${ROOT_DIR}/logs" "${ROOT_DIR}/output"

IFS='|' read -r -a build_cmd <<<"${SPEC}"
"${build_cmd[@]}" build
compose_up_safe "$SPEC" precios-web precios-mongo precios-qdrant precios-redis

# Caddy conserva durante un tiempo la IP resuelta del contenedor anterior.
# Recargarlo después de recrear `precios-web` evita servir la release vieja.
if [[ "$use_platform" == true ]] && docker ps --format '{{.Names}}' | grep -qx platform-caddy; then
  docker exec platform-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile \
    || echo "[!] Caddy no pudo recargarse; revisar platform-caddy"
fi

echo "==> Cron diario del batch (host, no el contenedor)"
if bash "${ROOT_DIR}/scripts/install-host-cron.sh"; then
  echo "==> Cron host OK"
else
  echo "[!] No se pudo instalar crontab en el host (¿falta el paquete cron?)"
fi

echo "==> Deploy OK — contenedores:"
docker ps --filter name=precios- --format 'table {{.Names}}\t{{.Status}}'
