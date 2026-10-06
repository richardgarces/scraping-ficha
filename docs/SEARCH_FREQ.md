# Ranking de búsquedas frecuentes (Redis top 10)

Ventana: **día civil `America/Santiago`**, misma noción de día que `search_cache`.
TTL: `ttl_until_midnight` (tope `RETAIL_SEARCH_CACHE_MAX_TTL`, default 4 h). No se sirven datos de otro día.

## Claves Redis

| Clave | Tipo | Contenido |
|---|---|---|
| `search:freq:YYYY-MM-DD` | ZSET | member = query canónica (`fold` + alfanum), score = conteo del día |
| `search:top:YYYY-MM-DD:{norm}` | STRING JSON | payload útil (`rows`/`groups`) del resultado del día |

Cada búsqueda web incrementa la **query completa** y, si difiere, la **primera palabra**.

## Flujo al buscar

1. Caché de resultado existente (`search:…:result:v2:…`) — sin cambios.
2. Si no hay hit: top 10 del día.
   - Query exacta en top **y** con payload → servir Redis.
   - Primera palabra en top **y** con payload → cargar ese set y **filtrar** por tokens extra (nombre/marca/attrs, case-insensitive).
3. Miss → path actual (Mongo/Qdrant/scrape). Al terminar, si la query quedó en el top 10, se popula `search:top:…`.

`search_cache` (TTL diario / max 4 h) sigue igual; este módulo es una capa adicional.

## Tiendas

**Top global** del día. Si el API pide un subconjunto de tiendas, se filtra el payload multi-tienda cacheado. No hay ranking por tienda separado.

## Admin

`/api/admin/stats` → `search_freq`. Panel en `/estadisticas` («Top 10 del día»).

## Código

- `retail/search_freq.py` — ranking, lookup, filtro, store
- Contador: `_log_web_search` en `retail/web/app.py`
- Lookup/store: `retail/search.py` (`lookup_top_search` / `store_top_search_result`)
