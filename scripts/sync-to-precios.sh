#!/usr/bin/env bash
# Copia un checkout al árbol de producción conservando secretos y la programación remota.
# SRC_DIR: origen (checkout). DEPLOY_DIR: destino, por defecto ~/precios.
set -euo pipefail

SRC_DIR="${SRC_DIR:-${GITHUB_WORKSPACE:-}}"
DEPLOY_DIR="${DEPLOY_DIR:-${HOME}/precios}"

if [[ -z "$SRC_DIR" || ! -d "$SRC_DIR" ]]; then
  echo "Falta SRC_DIR con el checkout a desplegar" >&2
  exit 1
fi
if [[ "$SRC_DIR" == "$DEPLOY_DIR" ]]; then
  echo "SRC_DIR y DEPLOY_DIR no pueden ser el mismo directorio" >&2
  exit 1
fi

mkdir -p "$DEPLOY_DIR/retail/batch"
rsync -a --delete \
  --exclude '.git' --exclude '.venv/' --exclude '.build/' \
  --exclude '.env' --exclude '.env.*' --exclude '.mongo_creds' \
  --exclude '.push-defaults' --exclude 'backups/' --exclude 'storage/' \
  --exclude 'logs/' --exclude 'output/' \
  --exclude '/retail/batch/programacion.json' \
  --exclude '/retail/batch/reglas_ofertas.json' \
  "$SRC_DIR/" "$DEPLOY_DIR/"
rsync -a --ignore-existing \
  "$SRC_DIR/retail/batch/programacion.json" \
  "$SRC_DIR/retail/batch/reglas_ofertas.json" \
  "$DEPLOY_DIR/retail/batch/"
chmod +x "$DEPLOY_DIR/"*.sh "$DEPLOY_DIR/scripts/"*.sh "$DEPLOY_DIR/scripts/remote/"*.sh 2>/dev/null || true
echo "Sincronizado en $DEPLOY_DIR"
