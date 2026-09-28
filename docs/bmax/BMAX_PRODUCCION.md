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
| `deploy/caddy/Caddyfile.platform-edge` | Solo el bloque `precios.meincart.com` |
| `scripts/link-platform-caddy.sh` | **Fusiona** ese bloque; no pisa `rent.meincart.com` |

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

`precios-web` es una imagen slim: **no tiene `crontab`**. El horario se guarda en `retail/batch/programacion.json` (volumen del compose). El job lo dispara el **cron del usuario `richard`** en el host, **una línea por grupo** de tiendas:

```
# retail-ofertas-begin
CRON_TZ=America/Santiago
0 6 * * * /home/richard/precios/scripts/ofertas-diarias-bmax.sh retail >> .../logs/ofertas-diarias-retail.log
45 6 * * * /home/richard/precios/scripts/ofertas-diarias-bmax.sh farmacias >> ...
…
# retail-ofertas-end
```

El wrapper hace `docker exec precios-web retail batch --grupo <grupo> ...`. Cada deploy y `prod-menu` opción 8 reinstalan esas líneas según `programacion.json`. Si `enabled` es false, el wrapper omite la corrida. Los grupos viven en Mongo `store_categories` (bootstrap desde el registry).

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

El borde es **Cloudflare Tunnel** (`http://precios.meincart.com` en Caddy, `auto_https off`). En Zero Trust, Public Hostname igual que `rent.meincart.com` → `http://platform-caddy:80`.

Mongo/Qdrant/Redis de este compose son **propios** de precios (no los de plataforma). No abrir 27017/6333/6379 al WAN.

## Qué no hacer

- No sustituir el `Caddyfile` de platform-caddy por el de esta app (borraría rent y el resto).
- No publicar otro Caddy en `:80`/`:443`.
- No commitear `.env` ni `.push-defaults`.
