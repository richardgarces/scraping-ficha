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
