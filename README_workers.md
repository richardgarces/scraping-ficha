Workers & Discovery
====================

Este directorio contiene artefactos mínimos para desplegar:
- Un servicio `discoverer` que lee `SITEMAP_URLS` y encola URLs en Redis.
- Un servicio `worker` (Go) que consume la cola priorizada (`schedule:urls`) y procesa páginas concurrentemente.

Cómo ejecutar (en la raíz `scraping`):

```bash
# exporta sitemaps separados por comas
export SITEMAP_URLS="https://tienda1.cl/sitemap.xml,https://tienda2.cl/sitemap.xml"
docker compose -f docker-compose.workers.yml up --build
```

Variables importantes:
- `REDIS_URL` default `redis://redis:6379/0`
- `SITEMAP_URLS` lista de sitemaps para discovery
- `WORKER_CONCURRENCY` concurrencia del worker Go

Notas:
- Este es un scaffold inicial: en producción deberías añadir logging, retries, backoff, control de circuit breaker, y parsers específicos por tienda.
- Para priorización avanzada, almacena métricas de volatilidad en `product:meta:{url}` y ajusta `frequency` dinámicamente.
