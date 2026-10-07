#!/usr/bin/env bash
# Fusiona el sitio precios.meincart.com en el Caddyfile de platform-caddy.
# Nunca pisa el archivo entero (rent.meincart.com y el resto se conservan).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-compose.sh"

PLATFORM_CADDY="${PLATFORM_CADDY_DIR:-${HOME}/platform-kit/ubuntu/platform/caddy}"
SRC="${ROOT_DIR}/deploy/caddy/Caddyfile.platform-edge"
DEST="${PLATFORM_CADDY}/Caddyfile"
PROJECT_NAME="platform-caddy"
BEGIN="# --- BEGIN precios.meincart.com ---"
END="# --- END precios.meincart.com ---"

info() { echo "==> $*"; }
error() { echo "ERROR: $*" >&2; }

[[ -f "$SRC" ]] || { error "falta $SRC"; exit 1; }
[[ -d "$PLATFORM_CADDY" ]] || { error "falta $PLATFORM_CADDY (¿kit ubuntu?)"; exit 1; }

COMPOSE_BIN="$(detect_compose)" || { error "sin docker compose"; exit 1; }

MAINT_SRC="${ROOT_DIR}/deploy/caddy/maintenance.html"
ERRORS_DIR="${PLATFORM_CADDY}/errors"
COMPOSE_FILE="${PLATFORM_CADDY}/docker-compose.yml"

# Copia la página de downtime y asegura el volumen ./errors → /srv/errors en
# platform-caddy (idempotente). Sin esto, handle_errors no puede servir el HTML.
ensure_error_pages() {
  [[ -f "$MAINT_SRC" ]] || { error "falta $MAINT_SRC"; return 1; }
  mkdir -p "$ERRORS_DIR"
  cp "$MAINT_SRC" "${ERRORS_DIR}/precios-maintenance.html"
  chmod 644 "${ERRORS_DIR}/precios-maintenance.html"
  info "Página mantenimiento → ${ERRORS_DIR}/precios-maintenance.html"

  [[ -f "$COMPOSE_FILE" ]] || { error "falta ${COMPOSE_FILE}"; return 1; }

  local current patched
  current="$(mktemp)"
  patched="$(mktemp)"
  read_dest "$COMPOSE_FILE" "$current"

  if grep -Fq './errors:/srv/errors' "$current"; then
    rm -f "$current" "$patched"
    return 0
  fi

  awk '
    /Caddyfile:\/etc\/caddy\/Caddyfile/ {
      print
      print "      - ./errors:/srv/errors:ro"
      next
    }
    { print }
  ' "$current" >"$patched"

  if ! grep -Fq './errors:/srv/errors' "$patched"; then
    rm -f "$current" "$patched"
    error "No se pudo insertar volumen ./errors en docker-compose.yml"
    return 1
  fi

  as_priv_cp "$patched" "$COMPOSE_FILE"
  rm -f "$current" "$patched"
  info "Volumen ./errors:/srv/errors:ro añadido a platform-caddy compose"
}

as_priv_cp() {
  local src="$1" dst="$2"
  if [[ -w "$(dirname "$dst")" ]] && { [[ ! -e "$dst" ]] || [[ -w "$dst" ]]; }; then
    cp "$src" "$dst"
  elif command -v sudo >/dev/null 2>&1; then
    sudo cp "$src" "$dst"
  else
    error "No se puede escribir $dst (usa sudo)"
    return 1
  fi
}

read_dest() {
  local dest="$1" out="$2"
  if [[ -r "$dest" ]]; then
    cp "$dest" "$out"
  elif command -v sudo >/dev/null 2>&1 && sudo test -f "$dest" 2>/dev/null; then
    sudo cat "$dest" >"$out"
  else
    error "falta ${dest}"
    return 1
  fi
}

write_canonical_block() {
  local snippet="$1"
  local out="$2"
  {
    echo "$BEGIN"
    if grep -Fq "$BEGIN" "$snippet"; then
      awk -v begin="$BEGIN" -v end="$END" '
        $0 == begin { inside=1; next }
        $0 == end { inside=0; next }
        inside { print }
      ' "$snippet"
    else
      cat "$snippet"
    fi
    echo "$END"
  } >"$out"
}

upsert_site_block() {
  local current="$1"
  local snippet="$2"
  local out="$3"
  local block
  block="$(mktemp)"
  write_canonical_block "$snippet" "$block"

  if grep -Fq "$BEGIN" "$current"; then
    awk -v begin="$BEGIN" -v end="$END" -v blockfile="$block" '
      BEGIN {
        while ((getline line < blockfile) > 0) {
          block = block line ORS
        }
        close(blockfile)
      }
      $0 == begin {
        printf "%s", block
        skip=1
        next
      }
      skip && $0 == end { skip=0; next }
      skip { next }
      { print }
    ' "$current" >"$out"
  else
    cat "$current" >"$out"
    printf '\n' >>"$out"
    cat "$block" >>"$out"
    printf '\n' >>"$out"
  fi
  rm -f "$block"
}

ensure_error_pages

CURRENT="$(mktemp)"
MERGED="$(mktemp)"
trap 'rm -f "$CURRENT" "$MERGED"' EXIT

read_dest "$DEST" "$CURRENT"
upsert_site_block "$CURRENT" "$SRC" "$MERGED"

STAMP="$(date +%Y%m%d_%H%M%S)"
as_priv_cp "$CURRENT" "${DEST}.bak-precios-${STAMP}"
as_priv_cp "$MERGED" "$DEST"
info "Sitio precios.meincart.com fusionado → ${DEST}"
info "Backup: ${DEST}.bak-precios-${STAMP}"

ENV_FILE="${PLATFORM_CADDY}/.env"
TMP="$(mktemp)"
chmod 600 "$TMP"
if [[ -r "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "$TMP"
elif sudo test -f "$ENV_FILE" 2>/dev/null; then
  sudo cat "$ENV_FILE" >"$TMP"
else
  error "falta ${ENV_FILE} (ACME_EMAIL real; SITE_ADDRESS puede seguir siendo rent.meincart.com)"
  rm -f "$TMP"
  exit 1
fi

if ! docker network inspect platform-net >/dev/null 2>&1; then
  info "Creando red platform-net"
  docker network create platform-net
fi

(
  cd "$PLATFORM_CADDY"
  case "$COMPOSE_BIN" in
    docker-compose|*/docker-compose)
      $COMPOSE_BIN -p "$PROJECT_NAME" --env-file "$TMP" -f docker-compose.yml down || true
      docker rm -f platform-caddy 2>/dev/null || true
      $COMPOSE_BIN -p "$PROJECT_NAME" --env-file "$TMP" -f docker-compose.yml up -d
      ;;
    *)
      $COMPOSE_BIN -p "$PROJECT_NAME" --env-file "$TMP" -f docker-compose.yml up -d --force-recreate
      ;;
  esac
)
rm -f "$TMP"
info "platform-caddy recargado (rent + precios)"
echo "    Health: curl -sf -H 'Host: precios.meincart.com' http://127.0.0.1/api/health"
