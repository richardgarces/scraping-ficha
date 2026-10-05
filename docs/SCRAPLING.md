# Piloto Scrapling (2 tiendas, HTML frágil)

Scrapling cubre **solo** fetch HTML opcional para parsers que se rompen cuando
cambia el DOM. **No** reemplaza FlareSolverr ni evade CAPTCHA / PRESS&HOLD.

## Tiendas del piloto

| Store id | Por qué |
|----------|---------|
| `hites` | Demandware/SFCC: grilla `Search-UpdateGrid` y rutas de imagen cambian (`/pim/…` → `images/original/…`); parsers por regex. |
| `santaritaonline` | WooCommerce: la Store API suele devolver 500; el cliente scrapea HTML de listado/ficha con selectores frágiles. |

**Fuera de alcance a propósito:** Líder, Ripley, Falabella (desafíos antibot → FlareSolverr / capturas). Scrapling no se usa para bypass.

## Activar (soyo / batch)

```bash
# En el venv del worker (no en la imagen web):
pip install -e '.[scrapling]'

# En .env del worker:
SCRAPLING_STORES=hites,santaritaonline
```

Sin la variable o sin el paquete, el flujo HTTP habitual no cambia.

## Contrato

1. Scrapling solo obtiene HTML.
2. Siguen los parsers existentes (`parse_hites_grid`, `parse_listing_html` / `parse_product_html`).
3. Salida: mismo modelo `Product` → `upsert` Mongo.

## Límites

- Piloto de **2** fuentes; otras ids en `SCRAPLING_STORES` se ignoran con warning.
- Sin StealthyFetcher / headless antibot en este path.
- No inflar la imagen `precios-web`: el extra `scrapling` es opcional y de batch.
- Reintentos y presupuesto de corrida siguen en el cliente / runner habitual.
