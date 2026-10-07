# Cyber Junio 2026 (`cyber_junio2026`)

Grupo de scraping diario con **100 queries Sonic** (Celulares, TV, Gaming…). Loop continuo vía worker dedicado; controles en el admin de corridas como retail/farmacias.

## Identidad

| Campo | Valor |
|-------|--------|
| **id** | `cyber_junio2026` |
| **título** | Cyber Junio 2026 |
| **lista** | `data/cyber_junio2026.json` (alias `data/cyber_day_sonic.json`) |
| **colección** | `cyber_day_products` (por `list_id`) + `cyber_day_lists` |
| **estado** | `app_settings.cyber_day_run:{slug}` (legacy `cyber_day_run`) |
| **categoría Mongo** | `store_categories` (`kind: query_list`) |

## Ruta admin

1. Menú **Cuenta → Cyber Day** (solo `role === admin`) → [`/cyber-day`](https://precios.meincart.com/cyber-day) (alias `/cyber`)
2. Selector de listas + **Nueva lista** (nombre/slug, seed / copiar / vacía)
3. Controles: **Iniciar** · **Parar** · **Continuar** · **Reiniciar** + import/export CSV/JSON
4. También en **Cron / lotes** (`/cron`) como grupo `cyber_junio2026` (muestra **100 queries**, no tiendas)

API (admin):

- `GET /api/admin/cyber-day?list=slug`
- `GET|POST /api/admin/cyber-day/lists`
- `POST /api/admin/cyber-day/start|stop|continue|restart?list=slug`
- `POST /api/admin/cyber-day/import`
- `GET /api/admin/cyber-day/export.csv` · `export.json`
- `GET /api/admin/cyber-day/items/{n}/evolution?list=slug&day=YYYY-MM-DD` — evolución del mejor precio ese día (America/Santiago)
- `POST /api/admin/cron-batches/cyber_junio2026/start` `{ "mode": "continue"|"restart"|omit }`

Informe UI: [`/cyber-day/evolucion?list=slug&n=12`](/cyber-day/evolucion) (columna **Evolución → Informe** en la tabla). Historial en Mongo `cyber_day_price_history` (un punto por cambio de precio/tienda/normal en el día).

### Pronóstico experimental

Los cambios de mejor precio de las listas **Cyber octubre 2026** y **Cyber junio 2026** (`cyber_oct2026` / `cyber_junio2026` y alias cercanos) se vuelcan al `price_history` del producto de catálogo y alimentan el **Pronóstico experimental** de la ficha (`/api/forecasts/...`).

- Tras cada observación nueva: se alimenta el historial; con ≥5 cambios Cyber (o forecast viejo) se intenta generar/actualizar.
- Al cerrar cada vuelta del worker: pasada de gaps sobre esa lista.
- Cron BMAX (`run_on_bmax.sh`): prioriza todos los productos Cyber elegibles (historial enriquecido) y vuelve a asegurar forecasts con TimesFM cuando hay ≥30 días distintos.

Si hay muchos cambios pero aún no hay 30 días de precios válidos, el panel sigue indicando que faltan datos; el contador `missing_forecast_with_many_changes` en el run marca el gap.

## Comportamiento

- Por cada query: catálogo + scrape ligero + refresh top matches.
- Al terminar 1→100: `lap++` y reinicia (loop).
- `%` avance, tiempo de vuelta, ETA.
- Telegram (canal admin) + push (admins / seguidores) si cambia precio u oferta.
- Cron host `retail batch --grupo cyber_junio2026` enciende el loop (delega a `precios-cyber-worker`).

## Worker

```bash
python -m retail.cyber_day
```

Compose: `cyber-worker` → `precios-cyber-worker` (BMAX) o `precios-cyber-worker-soyo`.

## Seed

Si `cyber_day_products` está vacío, carga automática del JSON oficial (100 ítems). Reimport opcional desde el panel.

## Deploy

```bash
./push-to-server.sh
ssh -p 2222 richard@192.168.1.198 'cd ~/precios && EDGE=platform ./scripts/deploy-prod.sh'
```

Sin FlareSolverr. Sin `--force-recreate` de volúmenes.
