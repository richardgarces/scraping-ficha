# Cotizaciones y listas de compra

La página `/cotizaciones`, disponible solo para administradores (como `/ofertas`)
desde el menú Cuenta, ofrece **dos modos**:

1. **Lista de compra (carrito)** — buscás productos en el catálogo, los agregás al
   carrito con cantidad, elegís tiendas por categoría (add/remove) y pulsáis
   **Cotizar** para armar una **matriz** lista × tiendas con el mejor match por
   tienda usando **precios de Mongo** (ventana 48 h; badge stale). Si una celda
   queda vacía, se encola **scrape async** por tienda+query y la UI muestra
   «buscando en tienda…» hasta el rebuild/poll.
2. **Cotización con precios de referencia** — importas una cotización de proveedor
   **con** `precio_unitario`, confirmas coincidencias y comparas ahorro potencial
   vs retail.

Cada cuenta admin accede solo a sus listas/cotizaciones (`owner_id`). Los precios
importados son referencias privadas: no modifican el catálogo ni el historial.
**Cotizar responde desde Mongo** (sin esperar FlareSolverr). Los misses encolan
jobs en `quote_miss_jobs` (worker en `precios-web` o `python -m retail.quote_miss_jobs`).
«Actualizar precios» solo sube prioridad de scrape de SKUs ya matcheados.

### Celdas vacías

| `empty_reason` | Significado |
|----------------|-------------|
| `no_catalog` | 0 productos en Mongo para esa tienda+query |
| `no_match` | Hay docs pero no pasan identidad ≥80% ni query⊆nombre con **envase compatible** |
| `searching` | Scrape on-miss encolado / en curso |

Matching grocery: el fallback laxo exige envase compatible (`pack_tokens`: 1 kg ≠ 1.5 kg).
Semilla jumbo/santa_isabel: `python scripts/seed-supermercado-miss.py`.

## Modo lista de compra (carrito)

1. En `/cotizaciones`, pestaña **Lista de compra**.
2. Nombre de la lista.
3. **Buscar productos** en el catálogo (`/api/catalog`, solo Mongo) → **Agregar**
   al carrito con cantidad. También podés quitar ítems o vaciar el carrito.
4. **Tiendas a cotizar**: checkboxes agrupados por categoría (`store-groups`);
   «Todas» / «Ninguna» por grupo.
5. **Guardar lista** persiste el borrador en Mongo sin armar matriz.
6. **Cotizar** guarda si hace falta, resuelve precios desde Mongo y encola scrape
   async en celdas vacías (poll automático ~8 s mientras haya «buscando…»).
7. Revisar celdas (stale en amarillo; buscando en azul; sin catálogo / sin match
   diferenciados); clic para confirmar match (incluye sugerencias `query_subset`).
8. Exportar CSV de la matriz. Si la canasta no está completa o hay celdas stale/
   buscando, el CSV es **parcial**: se descarga igual pero el estado no pasa a
   **Exportada**. Los totales de canasta usan solo precios **usable** (frescos).

CSV opcional (details «Importar desde CSV»): columnas `nombre` (obligatorio);
opcionales `cantidad`, `marca`, `ean`, `unidad`. Usa las tiendas marcadas.

Tiendas del grupo **supermercados** en el registry: `lider`, `unimarc`, `tottus`,
`alvi`, `cugat`, `jumbo`, `santa_isabel` (y las que estén en `STORE_GROUP` con
ese grupo).

## Modo cotización (referencia)

1. Pestaña **Cotización con precios de referencia**.
2. Pegar CSV o cargar JSON convertido (Docling).
3. Confirmar IVA, revisar filas, confirmar coincidencias.
4. Exportar CSV de comparación (ahorro potencial sin despacho).

Ejemplo CSV:

```csv
nombre;cantidad;precio_unitario;marca;unidad
Samsung Galaxy S25 256GB;2;700000;Samsung;unidad
```

También se reconoce `descripción`, `precio`, `ean` y sus equivalentes en inglés.
`$10.990` se interpreta como 10990 CLP; decimales ambiguos se rechazan. Se valida
el dígito verificador GTIN. Máximo 100 productos y 512 KB de CSV; el piloto admite
200 cotizaciones por cuenta. Las correcciones invalidan las coincidencias anteriores.

## Playbook PDF offline (5 pasos)

Solo aplica al modo cotización:

1. Obtener el PDF o imagen del proveedor en un entorno con Docling (`pip install -e '.[documents]'` o el entorno `scraping`/Soyo).
2. Convertir a JSON del piloto: `python scripts/convert_quote_document.py proveedor.pdf --output output/cotizacion.json --title "…" --supplier "…"`.
3. Abrir `/cotizaciones`, modo cotización, iniciar sesión como administrador, importar el JSON o pegar CSV equivalente.
4. Confirmar IVA, vigencia y filas con avisos; buscar y confirmar coincidencias por línea.
5. Exportar CSV de comparación; registrar feedback útil/corrección si aplica.

## Reglas comerciales

- Coincidencia mínima 80%, con las restricciones de identidad existentes.
- Precio del catálogo positivo en CLP y observado en las últimas 48 horas.
- Cantidad disponible suficiente. Una señal general de disponibilidad solo
  permite comparar una unidad; pedidos múltiples requieren cantidad observada.
- **Cotización:** IVA de la referencia confirmado y cotización vigente.
- **Lista de compra:** IVA/precio de referencia no obligatorios; la matriz usa
  solo precios del catálogo.
- Unidades de peso, volumen o longitud: con factores documentados
  (`retail/quote_units.py`). Si el catálogo declara el envase, se compara precio
  por kg/l/m; si no, la fila queda pendiente.
- La comparación es por productos, sin costos de despacho.
- Cambios concurrentes se rechazan con 409.

## Job async Docling

`POST /api/quotes/convert-jobs` (multipart) encola conversión en Mongo.
Worker: `python -m retail.quote_docling_jobs --once`. La UI muestra el panel solo
en el modo cotización.

## Estados del piloto

Cada cotización avanza `borrador → revisión → comparada → exportada`:

- **Borrador:** carrito guardado o importada sin matriz útil.
- **Revisión:** matches parciales o avisos pendientes.
- **Comparada:** (cotización) todas las filas comparables; (lista) canasta completa
  en al menos una tienda del set.
- **Exportada:** se descargó el CSV con comparación/matriz completa.

## API y métricas

La API canónica es `/api/quotes`. El alias español `/api/cotizaciones` expone las
mismas rutas. La página HTML sigue en `/cotizaciones` y exige rol administrador.

Endpoints relevantes (lista / carrito):

| Método | Ruta | Uso |
|--------|------|-----|
| GET | `/api/quotes/store-groups` | Categorías + tiendas para el selector |
| POST | `/api/quotes/shopping-cart` | Guardar borrador carrito (sin matriz) |
| POST | `/api/quotes/{id}/items` | Agregar producto al carrito |
| DELETE | `/api/quotes/{id}/items/{i}?version=` | Quitar producto |
| PUT | `/api/quotes/{id}/stores` | Actualizar tiendas/categoría |
| POST | `/api/quotes/{id}/cotizar` | Matriz Mongo-only (`enqueue_refresh=false`) |
| POST | `/api/quotes/import-csv` | `mode=shopping_list` + `store_group` / `store_ids` |
| POST | `/api/quotes/{id}/rebuild-matrix` | Regenerar matriz (puede boost scrape) |
| GET | `/api/quotes/{id}/candidates/{i}?store=` | Candidatos por celda |
| PUT | `/api/quotes/{id}/selection` | Confirmar match |
| GET | `/api/quotes/{id}/export.csv` | CSV matriz o comparación (parcial no marca Exportada) |

CSV de matriz (lista): columnas por tienda incluyen `usable`, `confirmada`,
`estado` (`matched` / `empty_reason`), motivo y ficha; el pie resume
`generated_at`, celdas match/stale/buscando y si la canasta es completa.

Colecciones Mongo: `business_quotes` (por `owner_id`; campos `mode`, `store_group`,
`store_ids`, `store_matches`, `resolved_stores`) y `business_quote_events`.

`GET /api/admin/purchasing-metrics` resume importaciones, matches, exportaciones y
feedback. Resultados privados: `Cache-Control: no-store`.

## Verificación

```bash
.venv/bin/python -m pytest tests/test_quotes.py tests/test_quotes_api.py tests/test_shopping_list.py -q
node --check retail/web/static/cotizaciones.js
```

## Despliegue

Empujar con `./push-to-server.sh` y en BMAX `EDGE=platform ./scripts/deploy-prod.sh`
(compose habitual). Mantener `precios-cyber-worker` parado si el scrape Cyber corre
en otro host. Verificar `https://precios.meincart.cl/cotizaciones` con sesión admin:
flujo carrito → Cotizar → matriz.
