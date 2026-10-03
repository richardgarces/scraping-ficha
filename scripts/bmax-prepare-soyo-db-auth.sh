#!/usr/bin/env bash
# Prepara auth en precios-mongo / precios-redis ANTES de publicar puertos VPN.
# NO abre puertos. Idempotente a medias: falla si faltan variables.
#
# Uso (en BMAX, con contenedores arriba):
#   export PRECIOS_MONGO_USER=precios_soyo
#   export PRECIOS_MONGO_PASSWORD='…'
#   export PRECIOS_REDIS_PASSWORD='…'
#   bash scripts/bmax-prepare-soyo-db-auth.sh
#
# Después hay que actualizar .env de precios-web (MONGODB_URI / REDIS_URL con
# credenciales) y recrear web+redis con el command requirepass — ver SOYO_WORKER.md.
# Hasta entonces, NO actives docker-compose.prod.soyo-access.yml.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MONGO_USER="${PRECIOS_MONGO_USER:?PRECIOS_MONGO_USER requerido}"
MONGO_PASS="${PRECIOS_MONGO_PASSWORD:?PRECIOS_MONGO_PASSWORD requerido}"
REDIS_PASS="${PRECIOS_REDIS_PASSWORD:?PRECIOS_REDIS_PASSWORD requerido}"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }

if ! docker inspect -f '{{.State.Running}}' precios-mongo 2>/dev/null | grep -qx true; then
  echo "[✗] precios-mongo no está corriendo" >&2
  exit 1
fi
if ! docker inspect -f '{{.State.Running}}' precios-redis 2>/dev/null | grep -qx true; then
  echo "[✗] precios-redis no está corriendo" >&2
  exit 1
fi

info "Creando/actualizando usuario Mongo '${MONGO_USER}' (admin + readWrite scraping)"
docker exec precios-mongo mongosh --quiet --eval "
const user = '${MONGO_USER}';
const pass = '${MONGO_PASS}';
const admin = db.getSiblingDB('admin');
const existing = admin.getUser(user);
if (existing) {
  admin.updateUser(user, {
    pwd: pass,
    roles: [
      { role: 'readWrite', db: 'scraping' },
      { role: 'readWrite', db: 'admin' },
    ],
  });
  print('updated');
} else {
  admin.createUser({
    user: user,
    pwd: pass,
    roles: [
      { role: 'readWrite', db: 'scraping' },
      { role: 'readWrite', db: 'admin' },
    ],
  });
  print('created');
}
"

warn "Mongo: el usuario existe, pero auth NO está forzada hasta arrancar mongod con --auth"
warn "       o MONGO_INITDB_ROOT_* en un volumen nuevo. Ver docs/bmax/SOYO_WORKER.md §3.1"
warn "Redis: apply requirepass en runtime (no persiste en conf del compose aún):"

docker exec precios-redis redis-cli CONFIG SET requirepass "${REDIS_PASS}" >/dev/null
docker exec precios-redis redis-cli -a "${REDIS_PASS}" PING

info "Redis requirepass activo en el proceso actual"
warn "Actualiza REDIS_URL del web a redis://:${REDIS_PASS}@precios-redis:6379/0 y recrea precios-web"
warn "Para persistir Redis auth, añade al service redis en un override:"
warn "  command: redis-server --save 60 1 --requirepass \"\${PRECIOS_REDIS_PASSWORD}\""
warn "NO publiques soyo-access hasta VPN + auth + firewall."
