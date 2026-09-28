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

COMPOSE_BIN="$(detect_compose)" || { echo "ERROR: falta docker compose"; exit 1; }

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
