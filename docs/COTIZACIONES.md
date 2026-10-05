# Piloto de cotizaciones comparadas

La página `/cotizaciones`, disponible solo para administradores (como `/ofertas`)
desde el menú Cuenta, permite importar una lista, revisar sus filas, confirmar
productos del catálogo y exportar una comparación. Cada cuenta admin accede
exclusivamente a sus cotizaciones. Los precios importados son referencias
privadas: no modifican el catálogo ni el historial de las tiendas.

## Uso

1. Pegar una lista CSV o cargar un archivo CSV/JSON de cotización convertido.
2. Confirmar si los precios de referencia incluyen IVA.
3. Revisar cantidades, unidades, precios y vigencia; guardar las correcciones.
4. Buscar y confirmar las coincidencias. Se reutilizan las reglas de identidad,
   condición, packs y variantes del comparador.
5. Revisar pendientes y exportar el CSV. La diferencia es potencial, sin despacho;
   no representa una venta ni ahorro realizado.

Ejemplo CSV (pesos CLP enteros):

```csv
nombre;cantidad;precio_unitario;marca;unidad
Samsung Galaxy S25 256GB;2;700000;Samsung;unidad
```

También se reconoce `descripción`, `precio`, `ean` y sus equivalentes en inglés.
`$10.990` se interpreta como 10990 CLP; decimales ambiguos se rechazan. Se valida
el dígito verificador GTIN. Máximo 100 productos y 512 KB de CSV; el piloto admite
200 cotizaciones por cuenta. Las correcciones invalidan las coincidencias anteriores.

## Playbook PDF offline (5 pasos)

1. Obtener el PDF o imagen del proveedor en un entorno con Docling (`pip install -e '.[documents]'` o el entorno `scraping`/Soyo).
2. Convertir a JSON del piloto: `python scripts/convert_quote_document.py proveedor.pdf --output output/cotizacion.json --title "…" --supplier "…"` (revisar avisos en consola).
3. Abrir `/cotizaciones`, iniciar sesión como administrador, importar el JSON o pegar CSV equivalente.
4. Confirmar IVA, vigencia y filas con avisos; buscar y confirmar coincidencias por línea.
5. Exportar CSV de comparación; registrar feedback útil/corrección si aplica. No usar URLs arbitrarias dentro del contenedor web.

## Conectar scraping/Docling

`scraping/scripts/scrape_and_convert.py` exporta documentos Docling JSON. El puente
de retail lee sus tablas sin cargar modelos de OCR:

```bash
.venv/bin/python scripts/convert_quote_document.py proveedor.docling.json \
  --output output/cotizacion-proveedor.json --title "Equipos" --supplier "Proveedor"
```

Luego importar `output/cotizacion-proveedor.json` en `/cotizaciones`. Se conservan
archivo de origen, SHA-256, tabla, página y fila. La conversión informa estado,
número de páginas, productos y filas/tablas que requieren revisión. Los avisos
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
- IVA de la referencia confirmado y cotización vigente.
- Unidades de peso, volumen o longitud: con factores documentados
  (`retail/quote_units.py`: 1 L = 1000 ml, 1 kg = 1000 g, 1 m = 100 cm/1000 mm).
  Si el catálogo declara el envase, se compara precio por kg/l/m; si no, la fila
  queda pendiente.
- La comparación es por productos, sin agregar ni multiplicar costos de despacho.
- Si varias filas usan el mismo SKU, se verifica la cantidad combinada.
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

La UI `/cotizaciones` muestra el panel de conversión y permite actualizar estado
e importar el resultado.

## Estados del piloto

Cada cotización avanza `borrador → revisión → comparada → exportada`:

- **Borrador:** importada, sin coincidencias ni ediciones.
- **Revisión:** hay correcciones, coincidencias parciales o avisos pendientes.
- **Comparada:** todas las filas son comparables (precio vigente, stock/unidad/IVA/vigencia OK).
- **Exportada:** se descargó el CSV con una comparación completa.

Una edición invalida coincidencias y vuelve a revisión. Las cantidades/unidades sin
confirmar y las referencias vencidas quedan pendientes: no generan ahorro inventado.

## API y métricas

La API canónica es `/api/quotes`. El alias español `/api/cotizaciones` expone las
mismas rutas (por ejemplo `GET /api/cotizaciones` lista cotizaciones; sin sesión
responde 401, no 404; usuario approved no-admin responde 403). La página HTML
sigue en `/cotizaciones` y exige rol administrador (`require_admin_html`, igual
que `/ofertas`).

`POST /api/quotes/import-csv`, `POST /api/quotes`, `GET /api/quotes`,
`GET/PUT /api/quotes/{id}`, `GET /api/quotes/{id}/candidates/{index}`,
`PUT /api/quotes/{id}/selection`, `GET /api/quotes/{id}/export.csv` y
`POST /api/quotes/{id}/feedback` exigen administrador (`current_user(..., admin=True)`)
y filtran por propietario.

Colecciones Mongo: `business_quotes` (por `owner_id`) y `business_quote_events`
(import, review, confirm, export, feedback, error).

El administrador puede consultar `GET /api/admin/purchasing-metrics`: importaciones,
matches/filas confirmadas, exportaciones, errores, ahorro potencial exportado y
feedback útil/corrección. Los resultados privados tienen `Cache-Control: no-store`.

Exportación del piloto: CSV (informe mínimo). XLSX/PDF de marca no están en el MVP;
el PDF de origen se convierte fuera de la petición web con Docling.

El piloto materializa la conexión documental y retail. La activación de nuevos
motores de extracción se debe decidir con pruebas por fuente; la facturación y
los planes comerciales requieren resultados de pilotos reales. TimesFM conserva
sus requisitos de historial y validación, y las alertas existentes se siguen
gestionando desde la ficha del producto.

## Verificación

```bash
.venv/bin/python -m pytest tests/test_quotes.py tests/test_quotes_api.py -q
node --check retail/web/static/cotizaciones.js
# En un entorno que ya incluya Playwright/Chromium (no toca producción):
.venv/bin/python tests/browser/purchasing_smoke.py
```

El smoke de navegador intercepta `/api/quotes` con datos sintéticos; requiere
`playwright install chromium` la primera vez.

La prueba de navegador usa respuestas sintéticas y no modifica producción ni envía avisos.

## Despliegue

El piloto vive en `scraping-ficha` (no requiere cambios en el contenedor de
Docling). Empujar código con `./push-to-server.sh` y en BMAX aplicar
`scripts/deploy-prod.sh` con los tres compose habituales
(`docker-compose.prod.yml` + `platform` + `soyo-access` si corresponde),
`Dockerfile.screenshots`, sin `--force-recreate` y sin tocar volúmenes
Mongo/Redis/Qdrant. Verificar `https://precios.meincart.cl/cotizaciones`
sin sesión (redirect a `/entrar`) y con sesión de administrador.
