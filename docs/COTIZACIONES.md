# Cotizaciones y listas de compra

La página `/cotizaciones`, disponible solo para administradores (como `/ofertas`)
desde el menú Cuenta, ofrece **dos modos**:

1. **Lista de compra multi-tienda** — subes productos (sin precio obligatorio),
   eliges una categoría de tiendas (p. ej. supermercados → Líder, Unimarc, Tottus
   y otras del grupo en el catálogo) y la app arma una **matriz** lista × tiendas
   con el mejor match ≥80% por tienda usando precios frescos de Mongo.
2. **Cotización con precios de referencia** — importas una cotización de proveedor
   **con** `precio_unitario`, confirmas coincidencias y comparas ahorro potencial
   vs retail.

Cada cuenta admin accede solo a sus listas/cotizaciones. Los precios importados
son referencias privadas: no modifican el catálogo ni el historial de las tiendas.
**No hay scrape live síncrono** en la petición: se usa el catálogo Mongo; los SKUs
matcheados pueden recibir un boost opcional de prioridad de scrape (mayor si hay
Seguimiento activo).

## Modo lista de compra

1. En `/cotizaciones`, pestaña **Lista de compra**.
2. Nombre de la lista + categoría de tiendas (grupo del registry / `store_categories`).
3. Pegar o subir CSV. Columnas: `nombre` (obligatorio); opcionales: `cantidad`,
   `marca`, `ean`, `unidad`, `precio_unitario` (solo referencia).
4. **Importar y comparar tiendas** → la API busca en el catálogo por cada ítem y
   rellena celdas (precio, confianza, link a ficha). Sin match: «sin stock o sin match».
5. Revisar celdas; clic en una celda para confirmar o cambiar el match de esa tienda.
6. Resumen: mejor tienda para la canasta (suma donde hay match; marca faltantes) y
   mejor precio por ítem.
7. Exportar CSV de la matriz.

Ejemplo CSV:

```csv
nombre;cantidad;marca
Azúcar granulada 1 kg;1;Iansa
Café molido 500 g;2;Juan Valdez
Papel higiénico 12 un;1;
```

Tiendas del grupo **supermercados** en el catálogo actual (sin Jumbo hasta que
exista scraper/registro): `lider`, `unimarc`, `tottus`, `alvi`, `cugat` (las que
esten registradas y listadas en el grupo).

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
2. Convertir a JSON del piloto: `python scripts/convert_quote_document.py proveedor.pdf --output output/cotizacion.json --title "…" --supplier "…"` (revisar avisos en consola).
3. Abrir `/cotizaciones`, modo cotización, iniciar sesión como administrador, importar el JSON o pegar CSV equivalente.
4. Confirmar IVA, vigencia y filas con avisos; buscar y confirmar coincidencias por línea.
5. Exportar CSV de comparación; registrar feedback útil/corrección si aplica. No usar URLs arbitrarias dentro del contenedor web.

## Conectar scraping/Docling

`scraping/scripts/scrape_and_convert.py` exporta documentos Docling JSON. El puente
de retail lee sus tablas sin cargar modelos de OCR:

```bash
.venv/bin/python scripts/convert_quote_document.py proveedor.docling.json \
  --output output/cotizacion-proveedor.json --title "Equipos" --supplier "Proveedor"
```

Luego importar `output/cotizacion-proveedor.json` en `/cotizaciones` (modo cotización).
Se conservan archivo de origen, SHA-256, tabla, página y fila. La conversión informa
estado, número de páginas, productos y filas/tablas que requieren revisión. Los avisos
viajan con la cotización; no se muestra una comparación completa hasta revisar
el documento original cuando hubo avisos de extracción.

Para convertir un PDF o imagen directamente, ejecutar el mismo puente en un
entorno separado con Docling (`pip install -e '.[documents]'` o el entorno de
`scraping`/Soyo donde Docling ya esté instalado). La instalación opcional no se
añade al contenedor web; OCR y conversión se ejecutan fuera de la petición HTTP.
No se descargan URLs proporcionadas por los usuarios. Si el servicio Docling en
Soyo no está disponible o no hay espacio/CPU, el flujo CSV/JSON + UI sigue
siendo el camino soportado del piloto.

```bash
python scripts/convert_quote_document.py proveedor.pdf \
  --output output/cotizacion-proveedor.json --title "Equipos" \
  --supplier "Proveedor" --tax-included --valid-until 2026-10-31
```

Usar `--tax-included` solo después de verificar la base del precio. Las tablas
deben tener encabezados reconocibles. El JSON de salida es revisable; no se
extraen precios mediante un LLM ni se inventan filas a partir del texto.

## Reglas comerciales

- Coincidencia mínima 80%, con las restricciones de identidad existentes.
- Precio del catálogo positivo en CLP y observado en las últimas 48 horas.
- Cantidad disponible suficiente. Una señal general de disponibilidad solo
  permite comparar una unidad; pedidos múltiples requieren cantidad observada.
- **Cotización:** IVA de la referencia confirmado y cotización vigente.
- **Lista de compra:** IVA/precio de referencia no obligatorios; la matriz usa
  solo precios del catálogo.
- Unidades de peso, volumen o longitud: con factores documentados
  (`retail/quote_units.py`: 1 L = 1000 ml, 1 kg = 1000 g, 1 m = 100 cm/1000 mm).
  Si el catálogo declara el envase, se compara precio por kg/l/m; si no, la fila
  queda pendiente.
- La comparación es por productos, sin agregar ni multiplicar costos de despacho.
- Si varias filas usan el mismo SKU, se verifica la cantidad combinada (modo cotización).
- Cambios concurrentes se rechazan con 409 para evitar sobrescribir revisiones.

## Job async Docling

`POST /api/quotes/convert-jobs` (multipart: `file`, `title`, `supplier`) encola la
conversión en Mongo (`quote_docling_jobs`). El worker
`python -m retail.quote_docling_jobs --once` (idealmente en Soyo con Docling)
produce `result.json`. Estados: `queued` → `processing` → `done` |
`needs_docling` | `failed`.

- Sin Docling en BMAX el job queda `needs_docling` (stub); usar entorno
  `scraping`/Soyo o `scripts/convert_quote_document.py`.
- `GET /api/quotes/convert-jobs/{id}` consulta el estado.
- `POST /api/quotes/convert-jobs/{id}/import` carga el JSON revisable como cotización.

La UI `/cotizaciones` muestra el panel de conversión en el modo cotización.

## Estados del piloto

Cada cotización avanza `borrador → revisión → comparada → exportada`:

- **Borrador:** importada, sin coincidencias ni ediciones.
- **Revisión:** hay correcciones, coincidencias parciales o avisos pendientes.
- **Comparada:** (cotización) todas las filas comparables; (lista) canasta completa
  en al menos una tienda del set.
- **Exportada:** se descargó el CSV con una comparación/matriz completa.

Una edición invalida coincidencias y vuelve a revisión (en lista regenera la matriz).

## API y métricas

La API canónica es `/api/quotes`. El alias español `/api/cotizaciones` expone las
mismas rutas. La página HTML sigue en `/cotizaciones` y exige rol administrador.

Endpoints relevantes:

| Método | Ruta | Uso |
|--------|------|-----|
| GET | `/api/quotes/store-groups` | Categorías + tiendas para el selector |
| POST | `/api/quotes/import-csv` | `mode=quote` o `mode=shopping_list` + `store_group` |
| POST | `/api/quotes/{id}/rebuild-matrix` | Regenerar matriz (solo lista) |
| GET | `/api/quotes/{id}/candidates/{i}?store=` | Candidatos (filtro tienda opcional) |
| PUT | `/api/quotes/{id}/selection` | Confirmar match (celda o fila) |
| GET | `/api/quotes/{id}/export.csv` | CSV comparación o matriz |

Colecciones Mongo: `business_quotes` (por `owner_id`; campos `mode`, `store_group`,
`store_matches`, `resolved_stores`) y `business_quote_events`.

`GET /api/admin/purchasing-metrics` resume importaciones, matches, exportaciones y
feedback. Resultados privados: `Cache-Control: no-store`.

## Verificación

```bash
.venv/bin/python -m pytest tests/test_quotes.py tests/test_quotes_api.py tests/test_shopping_list.py -q
node --check retail/web/static/cotizaciones.js
# En un entorno que ya incluya Playwright/Chromium (no toca producción):
.venv/bin/python tests/browser/purchasing_smoke.py
```

## Despliegue

El piloto vive en `scraping-ficha`. Empujar código con `./push-to-server.sh` y en
BMAX aplicar `scripts/deploy-prod.sh` con los compose habituales
(`docker-compose.prod.yml` + `platform` + `soyo-access` si corresponde),
`Dockerfile.screenshots`, sin `--force-recreate` y sin tocar volúmenes
Mongo/Redis/Qdrant. Verificar `https://precios.meincart.cl/cotizaciones`
sin sesión (redirect a `/entrar`) y con sesión de administrador: pestañas
Lista de compra / Cotización.
