# Cambios y pasos de despliegue en bmax

Resumen breve de los cambios realizados el 2026-09-20 para desplegar y habilitar nuevas funcionalidades:

- Añadido `deploy_bmax.sh` (script interactivo) en la raíz del repositorio `scraping`.
- En `docling`: añadido CSS global para mostrar `checkbox` como toggle en la documentación y actualizado `mkdocs.yml` para incluir `docs/stylesheets/toggle-checkbox.css`.
- En `scraping`:
  - Persistencia de `rating` y `reviews` desde la consulta a la tienda si faltaban (`retail/ficha_extra.py`).
  - Nueva UI de comparación de productos en `retail/web/static/producto.js` (modal, búsqueda y tabla comparativa).
  - Estilos para el modal de comparación en `retail/web/static/styles.css`.
  - `deploy` / `docker-compose.yml` modificaciones:
    - Eliminadas temporalmente publicaciones de puerto para `mongo` y `redis` (para evitar conflictos).
    - Opcional: mapeo alternativo `27018:27017` y `6380:6379` si se necesita acceso desde host.

Pasos clave ejecutados (comandos usados):

Local (desde el workspace):
```bash
# Commit y push de cambios
git add -A
git commit -m "feat/deploy: cambios para bmax + comparison UI + docs" || true
git push bmax main
```

Remoto (servidor `bmax`):
```bash
# Checkout work-tree (ejecutado por el script o manualmente)
ssh -p 2222 richard@192.168.1.198 \
  "git --work-tree=/home/richard/precios --git-dir=/home/richard/precios fetch --all && git --work-tree=/home/richard/precios --git-dir=/home/richard/precios checkout -f main"

# Reiniciar servicios docker-compose (ejecutado desde /home/richard/precios)
cd /home/richard/precios
docker-compose -f docker-compose.yml down --remove-orphans || true
docker-compose -f docker-compose.yml up -d --remove-orphans
```

Notas y recomendaciones:

- Conflictos de puertos: el host `bmax` ejecuta servicios de plataforma que ocupaban `127.0.0.1:27017` y `127.0.0.1:6379`. Para evitar ese bloqueo se optó por mapear `mongo` a `27018` y `redis` a `6380` en `docker-compose.yml`. Si otros servicios esperan los puertos estándar, actualiza sus variables de entorno (`MONGODB_URI`, `REDIS_URL`) o usa una red compartida de Docker sin exponer puertos.
- Archivos a revisar/ajustar si cambia la configuración de puertos:
  - `scraping/.env` y `scraping/.env.production.example`
  - `scraping/Dockerfile`, `scraping/worker/*` y cualquier script que use `localhost:6379` o `localhost:27017`.
- Docling: para publicar la documentación, ejecutar `mkdocs build`/`mkdocs serve` desde `docling` si es necesario.
- Si deseas volver a publicar puertos estándar en el host, detén los servicios que los usan o cambia su configuración (con cuidado si están en producción).

Dónde buscar los cambios hechos (rutas principales):

- `scraping/deploy_bmax.sh`
- `scraping/docker-compose.yml`
- `scraping/retail/web/static/producto.js`
- `scraping/retail/web/static/styles.css`
- `scraping/retail/ficha_extra.py`
- `docling/docs/stylesheets/toggle-checkbox.css`
- `docling/mkdocs.yml`

Si quieres, puedo:

- 1) Actualizar automáticamente referencias en el repo que apunten a `localhost:6379`/`27017` (reemplazo a `6380`/`27018`) — ya identifiqué las ocurrencias.
- 2) Añadir una sección al README con instrucciones de despliegue simplificadas.
- 3) Crear un pequeño script `check_ports.sh` en `scripts/` para validar puertos libres en `bmax` antes del deploy.

Fin del registro.