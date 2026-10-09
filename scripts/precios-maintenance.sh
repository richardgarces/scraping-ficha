#!/usr/bin/env bash
# Activa/desactiva mantenimiento precios.meincart.com en platform-caddy (503 + HTML).
# Uso: ./scripts/precios-maintenance.sh on|off|status
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-compose.sh"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-platform-caddy.sh"

usage() {
  echo "Uso: $0 on|off|status" >&2
  exit 1
}

cmd="${1:-}"
[[ -n "$cmd" ]] || usage

FLAG="$(precios_maintenance_flag_path)"

case "$cmd" in
  on)
    ensure_precios_error_pages "$ROOT_DIR"
    if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx platform-caddy; then
      if ! docker exec platform-caddy grep -Fq 'precios-maintenance.enabled' /etc/caddy/Caddyfile 2>/dev/null; then
        platform_caddy_error "Caddyfile sin @maint — ejecuta ./scripts/link-platform-caddy.sh una vez"
      fi
    fi
    touch "$FLAG"
    chmod 644 "$FLAG"
    reload_platform_caddy || true
    platform_caddy_info "Mantenimiento precios: ON (${FLAG})"
    ;;
  off)
    rm -f "$FLAG"
    reload_platform_caddy || true
    platform_caddy_info "Mantenimiento precios: OFF"
    ;;
  status)
    if [[ -f "$FLAG" ]]; then
      echo "on"
    else
      echo "off"
    fi
    ;;
  *)
    usage
    ;;
esac
