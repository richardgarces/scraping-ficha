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

## Almacenamiento y limpieza

- Archivos PNG en `output/offer_screenshots/` (volumen `./output` del compose).
- Antes de cada captura se borran archivos más viejos que `OFFER_SCREENSHOT_RETENTION_DAYS` (por defecto 7).

## Telegram / correo

- Telegram: `sendPhoto` con archivo local (multipart) o URL de imagen de producto.
- Correo: imagen embebida (`cid:offer-screenshot`) cuando hay captura local.
