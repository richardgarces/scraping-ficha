#!/usr/bin/env bash
# Atajo: empujar precios al BMAX
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
chmod +x "$ROOT/scripts/remote/"*.sh "$ROOT/scripts/"*.sh 2>/dev/null || true
exec bash "${ROOT}/scripts/remote/00-pack-and-push-app.sh" "$@"
