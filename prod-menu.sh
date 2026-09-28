#!/usr/bin/env bash
# Menú producción en el SERVIDOR — precios
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${ROOT}/scripts/prod-menu.sh" "$@"
