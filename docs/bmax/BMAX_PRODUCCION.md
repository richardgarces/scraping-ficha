# Precios → BMAX (precios.meincart.com)

El comparador corre como un solo contenedor FastAPI (`precios-web:8080`) detrás de **platform-caddy**, igual que MyRent Go (`rent.meincart.com`). Mongo, Qdrant y Redis van en el compose de la app (no se publican al host).

Skill: `bmax-platform-deploy`.

## Dominio

| Host | Upstream |
|------|----------|
| `precios.meincart.com` | `precios-web:8080` (UI + `/api`) |

Health: `https://precios.meincart.com/api/health`

DNS: el mismo Cloudflare Tunnel que `rent.meincart.com` (Proxied). Añade el Public Hostname `precios.meincart.com` → `http://platform-caddy:80` si aún no está.

## Qué hay en el repo

| Archivo | Rol |
|---------|-----|
| `push-to-server.sh` | Mac: zip + SCP + unzip; **conserva** el `.env` remoto |
| `prod-menu.sh` | En BMAX: env, caddy, deploy, logs, cron host, oneshot |
| `docker-compose.prod.yml` | `web` + mongo + qdrant + redis, **sin** puertos al host |
| `docker-compose.prod.platform.yml` | Une `precios-web` a `platform-net` |
| `deploy/caddy/Caddyfile.platform-edge` | Bloque `precios.meincart.com`, flag `@maint` y `handle_errors` 502/503/504 |
| `deploy/caddy/maintenance.html` | Página «Estamos actualizando la página» (marca Precios) |
| `scripts/link-platform-caddy.sh` | **Fusiona** ese bloque; copia el HTML a `platform-caddy/errors/`; no pisa `rent.meincart.com` |
| `scripts/precios-maintenance.sh` | `on` / `off` / `status` — flag `precios-maintenance.enabled` + reload Caddy |

### Mantenimiento en deploy

`scripts/deploy-prod.sh` (EDGE=platform) hace:

1. **Antes** del build/`up`: `./scripts/precios-maintenance.sh on` → Caddy responde **503** con el HTML estático (sin tocar `precios-web` todavía).
2. Tras `up` + health (`/api/health` en el contenedor y vía Caddy).
3. **Éxito**: `precios-maintenance.sh off` → routing normal.
4. **Fallo**: deja el mantenimiento **ON** (mensaje claro; no 502 genérico de Cloudflare si el borde está bien).

Respaldo si el contenedor cae sin aviso: `handle_errors` sirve la misma página en 502/503/504.

**Una vez** tras actualizar el repo (bloque `@maint` nuevo): `./prod-menu.sh` → opción **3** (`link-platform-caddy`) para fusionar el Caddyfile y montar `./errors:/srv/errors` en platform-caddy.

Manual:

```bash
./scripts/precios-maintenance.sh on   # antes de cambios manuales
./scripts/precios-maintenance.sh off
```

## Mac → servidor

```bash
cd /Users/Richard/desarrollo/python/scraping
./push-to-server.sh
```

Defaults: `richard@192.168.1.198`, SSH `2222`, dir `~/precios`.

El zip **no** lleva `.venv`, `.env`, `.git` ni `output/`.

## En BMAX

```bash
ssh -p 2222 richard@192.168.1.198
cd ~/precios && ./prod-menu.sh
# 1 → 2 (RETAIL_SECRET / admin) → 3 → 4
# o 10 (oneshot)
# 8 instala el cron diario del batch en el HOST (no dentro del contenedor)
```

`link-platform-caddy` hace backup del Caddyfile de plataforma y **añade** el sitio; el bloque de rent queda.

## Cron diario del batch

`precios-web` es una imagen slim: **no tiene `crontab`**. El horario se guarda en `retail/batch/programacion.json` (bind mount del JSON en compose; el resto de `retail/batch` va en la imagen). El job lo dispara el **cron del usuario `richard`** en el host, **una línea por grupo** de tiendas:

```
# retail-ofertas-begin
CRON_TZ=America/Santiago
0 6 * * * /home/richard/precios/scripts/ofertas-diarias-bmax.sh retail >> .../logs/ofertas-diarias-retail.log
45 6 * * * /home/richard/precios/scripts/ofertas-diarias-bmax.sh farmacias >> ...
…
# retail-ofertas-end
```

El wrapper hace `docker exec precios-web retail batch --grupo <grupo> ...`. Cada deploy y `prod-menu` opción 8 reinstalan esas líneas según `programacion.json`. Si `enabled` es false, el wrapper omite la corrida. Los grupos viven en Mongo `store_categories` (bootstrap desde el registry).

Capturas de oferta en Telegram/correo: opcionales (`OFFER_SCREENSHOTS=1`). La imagen slim no trae Chromium; usar `Dockerfile.screenshots` o instalar Playwright en el contenedor. Ver `docs/offer_screenshots.md`.

La corrida de `retail` es deliberadamente completa: el wrapper fuerza
`ADAPTIVE_SCRAPING=0` y no aplica un corte por tiempo. Si todavía sigue activa al
horario del día siguiente, el lock omite ese disparo para no duplicar consultas.
Los demás grupos conservan la priorización adaptativa y el presupuesto configurado.

## `.env` (servidor)

Ver `.env.production.example`. Lo mínimo:

```env
MONGODB_URI=mongodb://precios-mongo:27017
MONGODB_DB=scraping
QDRANT_URL=http://precios-qdrant:6333
REDIS_URL=redis://precios-redis:6379/0
RETAIL_SECRET=<hex largo>
RETAIL_ADMIN_EMAIL=...
RETAIL_ADMIN_PASSWORD=...
```

Usa los `container_name` (`precios-redis`, etc.). El hostname `redis` en `platform-net` apunta al Redis de plataforma (con contraseña) y rompe la caché.

### Concurrencia de scrape

El tope no es solo `max_workers` de cada pool: `retail/concurrency.py` reserva un slot
global (y otro Chromium) en Redis (`REDIS_URL` → `precios-redis`) para que varios
procesos Uvicorn u otros contenedores compartan el mismo presupuesto. Sin Redis,
cae a semáforos in-process.

```
             precios-web / batch
                      |
            Límite global: 8 tareas
                      |
             +--------+--------+
             |                 |
        HTTP directo       Playwright
        hasta 8            máximo 3
             |                 |
             +--------+--------+
                      |
                   MongoDB
```

| Variable | Default | Rol |
|----------|---------|-----|
| `RETAIL_SCRAPE_CONCURRENCY` | `8` | Slots globales de scrape (HTTP + Chromium) |
| `RETAIL_CHROMIUM_CONCURRENCY` | `3` | Navegadores Playwright simultáneos (también ocupan un slot global) |
| `RETAIL_STORE_WORKERS` | `8` | Pool HTTP por búsqueda (acotado por el global) |
| `RETAIL_THUMB_WORKERS` | `2` | Miniaturas en paralelo (fuera del presupuesto scrape) |
| `RETAIL_OPTIONAL_STORE_WORKERS` | `2` | Pool de tiendas opcionales (movistar/salcobrand) |
| `BATCH_PRODUCT_WORKERS` | `2` (tope duro `4`) | Productos en paralelo en batch por grupo |

Tras cambiar estas vars: recrear `precios-web` (p. ej. `docker compose ... up -d --force-recreate web`).

El borde es **Cloudflare Tunnel** (`http://precios.meincart.com` en Caddy, `auto_https off`). En Zero Trust, Public Hostname igual que `rent.meincart.com` → `http://platform-caddy:80`.

Mongo/Qdrant/Redis de este compose son **propios** de precios (no los de plataforma). No abrir 27017/6333/6379 al WAN.

## GitHub Actions

Un push a `main` despliega solo. El workflow `.github/workflows/deploy-bmax.yml` corre en un runner self-hosted en BMAX (etiqueta `bmax`), porque `192.168.1.198` no es alcanzable desde los runners de GitHub.

El job sincroniza el checkout a `~/precios` con `scripts/sync-to-precios.sh` (conserva `.env` y la programación remota) y ejecuta `EDGE=platform scripts/deploy-prod.sh`.

## Qué no hacer

- No sustituir el `Caddyfile` de platform-caddy por el de esta app (borraría rent y el resto).
- No publicar otro Caddy en `:80`/`:443`.
- No commitear `.env` ni `.push-defaults`.
