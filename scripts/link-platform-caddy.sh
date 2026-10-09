#!/usr/bin/env bash
# Fusiona el sitio precios.meincart.com en el Caddyfile de platform-caddy.
# Nunca pisa el archivo entero (rent.meincart.com y el resto se conservan).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-compose.sh"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/lib-platform-caddy.sh"

SRC="${ROOT_DIR}/deploy/caddy/Caddyfile.platform-edge"
DEST="${PLATFORM_CADDY}/Caddyfile"
PROJECT_NAME="${PLATFORM_CADDY_PROJECT}"
BEGIN="# --- BEGIN precios.meincart.com ---"
END="# --- END precios.meincart.com ---"

info() { platform_caddy_info "$@"; }
error() { platform_caddy_error "$@"; }

[[ -f "$SRC" ]] || { error "falta $SRC"; exit 1; }
[[ -d "$PLATFORM_CADDY" ]] || { error "falta $PLATFORM_CADDY (¿kit ubuntu?)"; exit 1; }

COMPOSE_BIN="$(detect_compose)" || { error "sin docker compose"; exit 1; }

ensure_error_pages() {
  ensure_precios_error_pages "$ROOT_DIR"
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

platform_caddy_read_dest "$DEST" "$CURRENT"
upsert_site_block "$CURRENT" "$SRC" "$MERGED"

STAMP="$(date +%Y%m%d_%H%M%S)"
platform_caddy_as_priv_cp "$CURRENT" "${DEST}.bak-precios-${STAMP}"
platform_caddy_as_priv_cp "$MERGED" "$DEST"
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
