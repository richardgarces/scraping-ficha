#!/usr/bin/env bash
# Menú producción — precios (en el servidor)
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
chmod +x "${ROOT_DIR}/scripts/"*.sh 2>/dev/null || true

ENV_FILE="${ROOT_DIR}/.env"
ENV_EXAMPLE="${ROOT_DIR}/.env.production.example"
COMPOSE_PROD="${ROOT_DIR}/docker-compose.prod.yml"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }
error() { echo "[✗] $*" >&2; }
pause() { read -r -p "Pulsa Enter..." _; }

ensure_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
      cp "$ENV_EXAMPLE" "$ENV_FILE"
      chmod 600 "$ENV_FILE"
      warn "Creado .env desde example — edita secretos (opción 2)"
    else
      error "Falta .env y .env.production.example"
      return 1
    fi
  else
    info ".env existe"
    chmod 600 "$ENV_FILE" 2>/dev/null || true
  fi
  if grep -q '^RETAIL_SECRET=cambia-esto' "$ENV_FILE" 2>/dev/null; then
    local secret
    secret="$(openssl rand -hex 32 2>/dev/null || python3 -c 'import secrets; print(secrets.token_hex(32))')"
    if [[ "$(uname)" == Darwin ]]; then
      sed -i '' "s/^RETAIL_SECRET=cambia-esto.*/RETAIL_SECRET=${secret}/" "$ENV_FILE"
    else
      sed -i "s/^RETAIL_SECRET=cambia-esto.*/RETAIL_SECRET=${secret}/" "$ENV_FILE"
    fi
    info "RETAIL_SECRET generado"
  fi
}

cmd_deploy() {
  EDGE="${EDGE:-platform}" bash "${ROOT_DIR}/scripts/deploy-prod.sh"
}

cmd_link() { bash "${ROOT_DIR}/scripts/link-platform-caddy.sh"; }

cmd_status() {
  docker ps -a --filter name=precios- \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' || true
  if docker exec precios-web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=3)" >/dev/null 2>&1; then
    info "precios-web /api/health OK"
  else
    warn "precios-web /api/health no responde"
  fi
  curl -sf --connect-timeout 3 -H 'Host: precios.meincart.com' http://127.0.0.1/api/health >/dev/null 2>&1 \
    && info "caddy → precios.meincart.com OK" || warn "caddy no responde para precios.meincart.com"
  if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q 'retail-ofertas-begin'; then
    info "cron host del batch instalado"
    crontab -l | sed -n '/retail-ofertas-begin/,/retail-ofertas-end/p' || true
  else
    warn "cron host del batch no está instalado (opción 8)"
  fi
}

cmd_cron() {
  bash "${ROOT_DIR}/scripts/install-host-cron.sh"
}

cmd_oneshot() {
  ensure_env
  echo "==> Revisa .env (RETAIL_SECRET, RETAIL_ADMIN_EMAIL, RETAIL_ADMIN_PASSWORD)…"
  cmd_link || warn "link caddy falló"
  EDGE=platform cmd_deploy
  cmd_status
  info "https://precios.meincart.com"
}

show_menu() {
  clear 2>/dev/null || true
  cat <<EOF
════════════════════════════════════════
 precios — producción (BMAX)
════════════════════════════════════════
  Dir: ${ROOT_DIR}
  Dom: precios.meincart.com

  1) Preparar .env
  2) Editar .env (nano)
  3) Enlazar platform-caddy
  4) Deploy EDGE=platform
  5) Estado / health
  6) Logs web
  7) Reiniciar web
  8) Instalar cron del batch (host)
 10) TODO EN UN PASO
  0) Salir
EOF
  read -r -p "Opción: " o
  case "$o" in
    1) ensure_env; pause ;;
    2) ensure_env; nano "$ENV_FILE" || vi "$ENV_FILE" ;;
    3) cmd_link; pause ;;
    4) EDGE=platform cmd_deploy; pause ;;
    5) cmd_status; pause ;;
    6) docker logs -f --tail=100 precios-web || true ;;
    7) docker restart precios-web || true; pause ;;
    8) cmd_cron; pause ;;
    10) cmd_oneshot; pause ;;
    0|q|Q) exit 0 ;;
    *) warn "inválida"; sleep 1 ;;
  esac
}

case "${1:-}" in
  1|env) ensure_env ;;
  3|link) cmd_link ;;
  4|deploy) EDGE=platform cmd_deploy ;;
  5|status) cmd_status ;;
  8|cron) cmd_cron ;;
  10|oneshot) cmd_oneshot ;;
  "") while true; do show_menu; done ;;
  *) error "usa --help o menú"; exit 1 ;;
esac
