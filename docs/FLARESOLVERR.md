# FlareSolverr en soyo

El cron retail corre en soyo. FlareSolverr se despliega allí junto al worker:

```bash
cd ~/precios
docker compose -f docker-compose.flaresolverr.yml up -d
```

Agregar a `.env` (sin publicar ese archivo):

```dotenv
FLARESOLVERR_URL=http://127.0.0.1:8191
FLARESOLVERR_MAX_TIMEOUT=60000
```

`HttpSession` conserva HTTP normal y solo consulta el solver ante desafíos
Cloudflare en GET. Reutiliza cookies y User-Agent del navegador para reintentar
la petición original, incluidas las URLs de APIs con parámetros. Si HTTP sigue
bloqueado, devuelve el HTML del navegador. Los POST no activan este respaldo.
Errores del solver se reportan como `HttpError`; no se guardan páginas de desafío.

El cron carga `.env` antes de ejecutar el venv. Para un worker Docker, conectar
ambos servicios a la misma red y usar `http://flaresolverr:8191`; la dirección de
loopback de un contenedor no apunta al host. BMAX mantiene web y bases de datos.
No es necesario reiniciarlas para activar el respaldo del cron.

El solver no garantiza resolver todos los desafíos ni CAPTCHA. El puerto queda
accesible solo desde el host. Para volver al flujo anterior, quitar
`FLARESOLVERR_URL` y detener el servicio con `docker compose -f
docker-compose.flaresolverr.yml down`.

para implementar en otro host, ver [FlareSolverr](https://github.com/FlareSolverr/FlareSolverr)

paso 1: instalar docker y docker-compose
paso 2: crear un archivo `docker-compose.flaresolverr.yml` con el contenido:

```yaml
version: "3.8"
services:
  flaresolverr:
    image: flaresolverr/flaresolverr:latest
    container_name: flaresolverr
    restart: unless-stopped
    ports:
      - "8191:8191"
    environment:
      - LOG_LEVEL=info
      - LOG_TIMESTAMP=true
      - LOG_JSON=false
      - LOG_COLOR=true
      - LOG_FILE=/dev/stdout

## Capturas de Líder

Playwright puede llegar a la intersticial PerimeterX/HUMAN («Robot or human?»)
mientras FlareSolverr sí accede a la ficha. Ante una captura bloqueada,
`capture_offer_screenshot` solicita `returnScreenshot` al solver. Verifica que
el HTML ya no sea una comprobación antibot y que la imagen sea un PNG válido
antes de usarla. La captura y el HTML provienen del mismo navegador, sin abrir
una nueva sesión Playwright que volvería a perder las cookies.

Si el respaldo falla o sigue bloqueado, se mantiene la imagen del producto.
No se envía una captura de la intersticial ni se da por resuelto un desafío
solo porque FlareSolverr devuelve `status: ok`.

## Capturas de Falabella

El mismo respaldo de capturas cubre Falabella. Su ficha puede incluir el script
pasivo de Cloudflare `/cdn-cgi/challenge-platform/scripts/jsd/main.js`; ese
recurso por sí solo no indica una intersticial. Se mantiene la detección por
títulos de desafío, marcadores de la intersticial y texto de verificación.
En la prueba desde soyo, Playwright recibió un 403 y FlareSolverr obtuvo la
ficha con foto y precio. Esto verifica esa ficha, no garantiza acceso a todas.
