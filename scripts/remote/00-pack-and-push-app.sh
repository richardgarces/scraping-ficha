#!/usr/bin/env bash
# Empaqueta la app, SCP al BMAX, descomprime. Preserva .env remoto.
# Atajo: ./push-to-server.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

REMOTE_USER="${REMOTE_USER:-richard}"
REMOTE_IP="${REMOTE_IP:-192.168.1.198}"
REMOTE_DIR="${REMOTE_DIR:-~/precios}"
SSH_PORT="${SSH_PORT:-2222}"
SSH_IDENTITY="${SSH_IDENTITY:-}"
APP_SLUG="precios"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }
error() { echo "[✗] $*" >&2; }

if [[ -f "${ROOT_DIR}/.push-defaults" ]]; then
  # shellcheck disable=SC1091
  set -a; source "${ROOT_DIR}/.push-defaults"; set +a
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) REMOTE_USER="${2:-}"; shift 2 ;;
    --ip|--hostname) REMOTE_IP="${2:-}"; shift 2 ;;
    --dir) REMOTE_DIR="${2:-}"; shift 2 ;;
    --port) SSH_PORT="${2:-}"; shift 2 ;;
    --identity|-i) SSH_IDENTITY="${2:-}"; shift 2 ;;
    user@*) REMOTE_USER="${1%%@*}"; REMOTE_IP="${1#*@}"; shift ;;
    *) shift ;;
  esac
done

read -r -p "Usuario SSH [${REMOTE_USER}]: " u; REMOTE_USER="${u:-$REMOTE_USER}"
read -r -p "IP [${REMOTE_IP}]: " ip; REMOTE_IP="${ip:-$REMOTE_IP}"
read -r -p "Dir remoto [${REMOTE_DIR}]: " d; REMOTE_DIR="${d:-$REMOTE_DIR}"
read -r -p "Puerto SSH [${SSH_PORT}]: " p; SSH_PORT="${p:-$SSH_PORT}"

HOST="${REMOTE_USER}@${REMOTE_IP}"
SSH_OPTS=(-p "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
SCP_OPTS=(-P "$SSH_PORT" -o StrictHostKeyChecking=accept-new)
[[ -n "$SSH_IDENTITY" ]] && SSH_OPTS+=(-i "$SSH_IDENTITY") && SCP_OPTS+=(-i "$SSH_IDENTITY")

BUILD_DIR="${ROOT_DIR}/.build"
mkdir -p "$BUILD_DIR"
STAMP="$(date +%Y%m%d_%H%M%S)"
ZIP="${BUILD_DIR}/${APP_SLUG}_${STAMP}.zip"
REMOTE_ZIP="/tmp/${APP_SLUG}_${STAMP}.zip"

info "Empaquetando ${APP_SLUG}…"
# Excluye secretos, deps y basura; incluye código y scripts de deploy
(
  cd "$ROOT_DIR"
  zip -r "$ZIP" . \
    -x "./.git" \
    -x "./.git/*" \
    -x "./.build/*" \
    -x "./.venv/*" \
    -x "./.pytest_cache/*" \
    -x "./output/*" \
    -x "./logs/*" \
    -x "./storage/*" \
    -x "./node_modules/*" \
    -x "./**/node_modules/*" \
    -x "./.env" \
    -x "./.env.*" \
    -x "./.mongo_creds" \
    -x "./backups/*" \
    -x "./ubuntu/*" \
    -x "./.push-defaults" \
    -x "./.DS_Store" \
    -x "**/.DS_Store" \
    -x "**/__pycache__/*" \
    -x "**/*.pyc" \
    >/dev/null
  # Forzar includes útiles aunque .env.* excluya examples
  zip -u "$ZIP" .env.production.example .push-defaults.example 2>/dev/null || true
)

info "SCP → ${HOST}:${REMOTE_ZIP}"
scp "${SCP_OPTS[@]}" "$ZIP" "${HOST}:${REMOTE_ZIP}"

info "Descomprimir en remoto (preserva .env)"
# shellcheck disable=SC2029
ssh "${SSH_OPTS[@]}" "$HOST" bash -s <<REMOTE
set -euo pipefail
REMOTE_DIR="${REMOTE_DIR/#\~/\$HOME}"
mkdir -p "\$REMOTE_DIR"
STAGE_DIR="\$(mktemp -d /tmp/${APP_SLUG}.unpack.XXXXXX)"
trap 'rm -rf "\$STAGE_DIR"' EXIT
if [[ -f "\$REMOTE_DIR/.env" ]]; then
  cp -a "\$REMOTE_DIR/.env" "/tmp/${APP_SLUG}.env.preserve"
fi
unzip -qo "${REMOTE_ZIP}" -d "\$STAGE_DIR"
# Sincronizar dentro de los directorios existentes preserva sus inodes. Esto
# evita que el bind mount retail/batch de un contenedor activo quede apuntando
# a un directorio eliminado y aparezca vacío hasta el siguiente deploy.
rsync -a --delete \
  --exclude '.git' --exclude '.venv/' --exclude '.build/' \
  --exclude '.env' --exclude '.env.*' --exclude '.mongo_creds' \
  --exclude '.push-defaults' --exclude 'backups/' --exclude 'storage/' \
  --exclude 'logs/' --exclude 'output/' \
  --exclude '/retail/batch/programacion.json' \
  --exclude '/retail/batch/reglas_ofertas.json' \
  "\$STAGE_DIR/" "\$REMOTE_DIR/"
# Instalar los valores iniciales solo cuando aún no hay configuración remota.
rsync -a --ignore-existing \
  "\$STAGE_DIR/retail/batch/programacion.json" \
  "\$STAGE_DIR/retail/batch/reglas_ofertas.json" \
  "\$REMOTE_DIR/retail/batch/"
if [[ -f "/tmp/${APP_SLUG}.env.preserve" ]]; then
  mv "/tmp/${APP_SLUG}.env.preserve" "\$REMOTE_DIR/.env"
  chmod 600 "\$REMOTE_DIR/.env"
fi
chmod +x "\$REMOTE_DIR/"*.sh "\$REMOTE_DIR/scripts/"*.sh "\$REMOTE_DIR/scripts/remote/"*.sh 2>/dev/null || true
rm -f "${REMOTE_ZIP}"
rm -rf "\$STAGE_DIR"
trap - EXIT
echo "OK en \$REMOTE_DIR"
echo "Siguiente: cd \$REMOTE_DIR && ./prod-menu.sh"
REMOTE

info "Listo. SSH: ssh -p ${SSH_PORT} ${HOST}"
