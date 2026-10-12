#!/usr/bin/env bash
# Deploy de producción en BMAX. Lo ejecuta el runner de GitHub Actions en el servidor.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Este deploy corre en el runner de BMAX, no en el Mac" >&2
  exit 1
fi

# BMAX usa docker-compose v1; cargar su cliente compatible sin alterar Python del sistema.
COMPOSE_COMPAT_VENV="${HOME}/.cache/docker-compose-compat"
if [[ -x "${COMPOSE_COMPAT_VENV}/bin/python" ]]; then
  COMPOSE_COMPAT_SITE="$("${COMPOSE_COMPAT_VENV}/bin/python" -c \
    'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  export PYTHONPATH="${COMPOSE_COMPAT_SITE}${PYTHONPATH:+:${PYTHONPATH}}"
fi

export SRC_DIR="${GITHUB_WORKSPACE:-$ROOT}"
export DEPLOY_DIR="${DEPLOY_DIR:-${HOME}/precios}"
bash "${ROOT}/scripts/sync-to-precios.sh"
cd "$DEPLOY_DIR"
EDGE=platform bash scripts/deploy-prod.sh
