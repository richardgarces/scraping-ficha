#!/usr/bin/env bash
# Helpers compartidos: platform-caddy, página de mantenimiento precios.
# shellcheck disable=SC2034

PLATFORM_CADDY="${PLATFORM_CADDY_DIR:-${HOME}/platform-kit/ubuntu/platform/caddy}"
PLATFORM_CADDY_PROJECT="${PLATFORM_CADDY_PROJECT:-platform-caddy}"
PRECOS_MAINT_FLAG="${PRECOS_MAINT_FLAG:-precios-maintenance.enabled}"
PRECOS_MAINT_HTML="${PRECOS_MAINT_HTML:-precios-maintenance.html}"

platform_caddy_info() { echo "==> $*"; }
platform_caddy_error() { echo "ERROR: $*" >&2; }

platform_caddy_as_priv_cp() {
  local src="$1" dst="$2"
  if [[ -w "$(dirname "$dst")" ]] && { [[ ! -e "$dst" ]] || [[ -w "$dst" ]]; }; then
    cp "$src" "$dst"
  elif command -v sudo >/dev/null 2>&1; then
    sudo cp "$src" "$dst"
  else
    platform_caddy_error "No se puede escribir $dst (usa sudo)"
    return 1
  fi
}

platform_caddy_read_dest() {
  local dest="$1" out="$2"
  if [[ -r "$dest" ]]; then
    cp "$dest" "$out"
  elif command -v sudo >/dev/null 2>&1 && sudo test -f "$dest" 2>/dev/null; then
    sudo cat "$dest" >"$out"
  else
    platform_caddy_error "falta ${dest}"
    return 1
  fi
}

# Copia maintenance.html y monta ./errors en platform-caddy si falta.
# root_dir: raíz del repo precios (contiene deploy/caddy/maintenance.html).
ensure_precios_error_pages() {
  local root_dir="${1:?root_dir}"
  local maint_src="${root_dir}/deploy/caddy/maintenance.html"
  local errors_dir="${PLATFORM_CADDY}/errors"
  local compose_file="${PLATFORM_CADDY}/docker-compose.yml"

  [[ -f "$maint_src" ]] || { platform_caddy_error "falta $maint_src"; return 1; }
  [[ -d "$PLATFORM_CADDY" ]] || { platform_caddy_error "falta $PLATFORM_CADDY (¿kit ubuntu?)"; return 1; }

  mkdir -p "$errors_dir"
  cp "$maint_src" "${errors_dir}/${PRECOS_MAINT_HTML}"
  chmod 644 "${errors_dir}/${PRECOS_MAINT_HTML}"
  platform_caddy_info "Página mantenimiento → ${errors_dir}/${PRECOS_MAINT_HTML}"

  [[ -f "$compose_file" ]] || { platform_caddy_error "falta ${compose_file}"; return 1; }

  local current patched
  current="$(mktemp)"
  patched="$(mktemp)"
  platform_caddy_read_dest "$compose_file" "$current"

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
    platform_caddy_error "No se pudo insertar volumen ./errors en docker-compose.yml"
    return 1
  fi

  platform_caddy_as_priv_cp "$patched" "$compose_file"
  rm -f "$current" "$patched"
  platform_caddy_info "Volumen ./errors:/srv/errors:ro añadido a platform-caddy compose"
}

precios_maintenance_flag_path() {
  echo "${PLATFORM_CADDY}/errors/${PRECOS_MAINT_FLAG}"
}

reload_platform_caddy() {
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx platform-caddy; then
    docker exec platform-caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile \
      || platform_caddy_error "Caddy no pudo recargarse"
    return 0
  fi
  platform_caddy_error "platform-caddy no está en ejecución"
  return 1
}
