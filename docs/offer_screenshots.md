# Capturas de página en alertas

Al enviar una alerta por **Telegram** o **correo**, se puede adjuntar una captura de la página de la oferta (URL de la tienda; si falta, la ficha pública). **No** se captura en cada scrape. El push web sigue sin captura.

## Activar

1. Instalar Playwright + Chromium en el proceso que corre el batch (en BMAX es `precios-web` vía `docker exec`):

```bash
# Opción A: imagen con Chromium (recomendada si quieres capturas estables)
docker build -f Dockerfile.screenshots -t precios-web:screenshots .
# y desplegar esa imagen como precios-web

# Opción B: en el contenedor slim ya corriendo
docker exec -u root precios-web bash -lc \
  'pip install "playwright>=1.40" && playwright install --with-deps chromium'
```

2. Variables en `.env`:

```env
OFFER_SCREENSHOTS=1
OFFER_SCREENSHOT_TIMEOUT_MS=15000
OFFER_SCREENSHOT_RETENTION_DAYS=7
# OFFER_SCREENSHOT_DIR=output/offer_screenshots
```

3. Recrear / reiniciar el servicio para cargar el `.env`.

Si `OFFER_SCREENSHOTS` no está en `1`/`true`, o falta Playwright/Chromium, el envío usa el `image_url` del producto como hasta ahora. Un fallo de captura **nunca** tumba el aviso.

El admin puede apagar o prender las capturas en **Configurar** (`/ofertas`), sección «Capturas de oferta». Ese valor se guarda en Mongo `app_settings` con `_id` `offer_screenshots` (`enabled`: true/false) y lo leen tanto `precios-web` como el batch de soyo. Si no hay documento, sigue valiendo `OFFER_SCREENSHOTS`. Si el admin lo apaga, no se captura aunque el env esté en `1`. Si lo prende, se captura solo cuando Playwright/Chromium están disponibles; si no, se usa la foto del producto.

## Almacenamiento y limpieza

- Archivos PNG en `output/offer_screenshots/` (volumen `./output` del compose).
- Antes de cada captura se borran archivos más viejos que `OFFER_SCREENSHOT_RETENTION_DAYS` (por defecto 7).

## Lotes en alertas

Las corridas de alertas (`dispatch_alerts`, fan-out a usuarios, cambios de precio, predictivas) **deduplican** ofertas y capturan con `capture_offer_screenshots_batch` / `apply_offer_screenshots`:

- Un solo `chromium.launch` por lote (no un browser por alerta).
- Un slot Chromium compartido (`RETAIL_CHROMIUM_CONCURRENCY`, default 3) vía Redis/in-process (`retail.concurrency`).
- Hasta esa cantidad de **pages** en paralelo sobre el mismo browser.
- FlareSolverr, si hace falta, corre **en serie** después de cerrar Playwright.
- El tope global de scrape (`RETAIL_SCRAPE_CONCURRENCY`) sigue aplicando: la captura toma un slot scrape + uno Chromium.

## Telegram / correo

- Telegram: `sendPhoto` con archivo local (multipart) o URL de imagen de producto.
- Correo: imagen embebida (`cid:offer-screenshot`) cuando hay captura local.
