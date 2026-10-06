# Cyber Day — loop de queries Sonic

Modo especial de scraping para días Cyber: recorre **100 queries fijas** (Tablas Sonic), muestra avance y tiempo por vuelta, y avisa por **Telegram + push** si cambia el precio/oferta de algún match monitoreado.

## Lista oficial

- Seed: [`data/cyber_day_sonic.json`](../data/cyber_day_sonic.json) y CSV gemelo [`data/cyber_day_sonic.csv`](../data/cyber_day_sonic.csv).
- Cada ítem es una **query de búsqueda** + categoría (Celulares, TV, Gaming, …).
- Si la colección Mongo `cyber_day_products` está vacía, se carga el seed automáticamente (`ensure_seed`).
- Scribd no se usa (paywall/challenge). Reimportá CSV/JSON desde el admin si querés editar la lista.

## Controles admin

En **Cron / lotes** (`/cron`), panel **Cyber Day**:

| Botón | Efecto |
|-------|--------|
| **Iniciar** | Vuelta 1 desde query #1 |
| **Parar** | `stopped` (conserva cursor) |
| **Continuar** | Reanuda desde el cursor |
| **Importar lista** | Reemplaza la lista (CSV/JSON: `n,query,category`) |

Progreso: `%` = procesados/total de la vuelta, tiempo transcurrido, ETA, número de vuelta, matches y mejor precio por query.

## Worker

```bash
python -m retail.cyber_day           # loop
python -m retail.cyber_day --once    # una query
python -m retail.cyber_day --seed    # solo asegurar seed
python -m retail.cyber_day --healthcheck
```

Compose:

- BMAX: servicio `cyber-worker` → contenedor `precios-cyber-worker` en `docker-compose.prod.yml`.
- Soyo (preferible si el scrape pesa): `cyber-worker` en `docker-compose.worker.soyo.yml` → `precios-cyber-worker-soyo`. **No** corras ambos a la vez.

Variables opcionales:

| Env | Default | Rol |
|-----|---------|-----|
| `CYBER_DAY_DELAY_SECONDS` | `2.5` | Pausa entre queries |
| `CYBER_DAY_TOP_MATCHES` | `6` | Matches rankeados por query |
| `CYBER_DAY_REFRESH_TOP` | `3` | Refresh puntual de ficha |
| `CYBER_DAY_SEARCH_MAX_ITEMS` | `4` | Ítems por tienda en scrape |

## Flujo por query

1. `find_by_query` en catálogo Mongo.
2. `search_products(source=both)` ligero (sin FlareSolverr).
3. Refresh de top fichas + boost en `scrape_priorities`.
4. Compara firmas `precio:normal:card` con la observación anterior (la primera no notifica).
5. Si cambia → Telegram canal admin + push admins + alertas a quienes siguen el producto.
6. Al terminar 1→100: `lap++`, cursor=0, sigue sin parar.

Estado: `app_settings.cyber_day_run` (`idle|running|paused|stopped`, cursor, lap, processed/total, tiempos, last_error).

## Deploy

```bash
# Mac → BMAX
./push-to-server.sh
# En BMAX
cd ~/precios && EDGE=platform ./scripts/deploy-prod.sh
# Verificar
docker ps | grep cyber
curl -s http://127.0.0.1:8080/api/health | jq .cyber_day
```

En soyo (opcional, scrape remoto):

```bash
cd ~/precios
docker compose -f docker-compose.worker.soyo.yml up -d --build cyber-worker
# En BMAX: docker stop precios-cyber-worker
```

No uses `--force-recreate` de volúmenes. No actives FlareSolverr para este modo.
