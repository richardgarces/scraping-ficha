# TimesFM: preparación de datos

El proceso usa por defecto `google/timesfm-2.5-200m-pytorch` (pesos Apache 2.0).
Instalar sus dependencias en el entorno del host BMAX con
`.venv/bin/python -m pip install -r requirements-timesfm.txt`.
El proceso carga `.env` del proyecto para acceder a MongoDB con autenticación.
Si la URI del host no incluye autenticación, toma la conexión vigente de
`precios-web` y adapta su dirección a la red del contenedor MongoDB.
Antes de la primera carga del modelo ejecutar el verificador de recursos de
`timesfm/timesfm-forecasting/scripts/check_system.py` en BMAX.
TimesFM 3 se conserva para configuraciones explícitas mediante `TIMESFM_CHECKPOINT`;
sus pesos predeterminados tienen restricciones para uso en producción.

La API omite simulaciones al construir el resumen y busca el primer pronóstico
utilizable entre los últimos 20 registros. La fecha del resumen corresponde al
registro seleccionado; consultar un producto no ejecuta inferencia ni envía avisos.

Antes de generar un pronóstico, cada producto debe pasar estas reglas:

- identidad estable `tienda:product_id`; no se mezclan productos de tiendas ni variantes con IDs distintos;
- precio positivo y fecha válida (`scraped_at`, con compatibilidad para formatos antiguos);
- historial ordenado por fecha en la zona horaria `America/Santiago`;
- una observación por día: se conserva el último precio visto ese día;
- producto actualmente disponible (se excluyen estados `agotado` y `sin stock`);
- al menos 30 días distintos observados y 30 días de extensión temporal.

Los documentos de `forecasts` guardan `forecast_key`, tienda, producto, cantidad de observaciones,
inicio y fin del historial y la frecuencia diaria. Para una misma combinación producto, horizonte y
modelo se actualiza el pronóstico vigente en vez de acumular duplicados.

Si TimesFM falla, el proceso se identifica como `last_value_baseline`; nunca se guarda como un
pronóstico TimesFM simulado. Las simulaciones solo se generan al usar explícitamente `--simulate`.

Ejemplo:

```bash
python timesfm_poc/forecast_from_mongo.py --sample 20 --horizon 7 --min-history-days 30
```

## Listas Cyber (octubre / junio 2026)

El scraping Cyber registra cambios en `cyber_day_price_history`. Esos puntos se
reutilizan para el pronóstico experimental:

1. Se empujan al `price_history` del `store:product_id` ganador.
2. Con **serie densa** (muchos puntos y cambios reales en el día, buckets de
   ~15 min) se genera `cyber_event_dense`: resto del Cyber actual + consejo
   comprar/esperar. Si no alcanza densidad, cae a `cyber_event_trend` (≥3
   observaciones). **No usa TimesFM**.
3. Con **≥2 Cybers densos previos** del mismo producto se genera
   `cyber_future_transfer`: patrón tipico del próximo evento (curva mediana
   normalizada por precio de apertura). Tampoco depende de TimesFM diario.
4. La generación diaria (cron BMAX / `ensure_cyber_list_forecasts`) prioriza
   listas octubre/junio 2026; TimesFM diario (≥30 días) queda como fallback.
5. Al preparar la serie diaria se vuelve a mezclar el historial Cyber por si
   faltó algún punto en catálogo.

Desactivar prioridad Cyber en el batch TimesFM: `FORECAST_INCLUDE_CYBER=0` o
`--no-include-cyber`.

## Presentación experimental

La ficha del producto consulta `/api/forecasts/{product_id}?store={tienda}` y muestra:

- tendencia probable frente al precio actual;
- rango esperado (cuantiles del modelo cuando existen; valores centrales en caso contrario);
- confianza orientativa según el modelo, la cantidad de días y la existencia de incertidumbre;
- fecha, horizonte y cantidad de observaciones usadas.

Si no existe un pronóstico utilizable, la ficha explica que todavía se necesitan datos. Esta sección
es únicamente informativa: ningún módulo de alertas, scraping, ofertas o recomendación de compra
consume el pronóstico.

## Cumplimiento experimental (`/pronosticos`)

Al generar un pronóstico se guarda un snapshot inmutable en `forecast_outcomes`
(la colección `forecasts` sigue sobrescribiendo la versión vigente). El cron
BMAX (`scripts/evaluate_forecast_outcomes.py`, enganchado en `run_on_bmax.sh`)
revisa cada día los snapshots `pending` contra el `price_history` real:

- **Cumplió:** algún precio diario del horizonte cae en el rango esperado, o
  hay un movimiento ≥2% en la dirección pronosticada;
- **No cumplió:** el horizonte termina sin hit;
- **Pendiente:** aún quedan días; la ETA estima cuándo debería cumplirse.

La página admin `/pronosticos` lista todos los snapshots, muestra cumplimiento,
ETA/días a cumplir y estadísticas (hit rate, mediana de días, desglose por modelo).

## Alertas predictivas y validación

Cada cuenta puede seleccionar `Alertas predictivas experimentales` junto con sus canales de correo
y Telegram. La selección queda guardada, pero el envío tiene un bloqueo independiente y solo se
habilita cuando una validación cumple simultáneamente:

- al menos 30 series evaluadas reservando los últimos siete días;
- error de TimesFM al menos 5% menor que repetir el último precio conocido;
- dirección correcta (sube/baja) en al menos 55% de las series.

`scripts/validate_timesfm.py` registra esas métricas en `app_settings.timesfm_validation`.

En BMAX, `scripts/install-host-cron.sh` agrega `scripts/run_on_bmax.sh` a las
21:30 (hora de Santiago), después de los lotes de scraping. El proceso valida,
genera pronósticos y recién entonces evalúa las suscripciones. Aunque un usuario
active la opción, no se envía ninguna alerta mientras la validación esté cerrada.

## Señal complementaria en ofertas reales

Las páginas de ofertas reales y superofertas pueden mostrar una señal experimental
cuando existe un pronóstico TimesFM validado y generado durante las últimas 48 horas:

- **Caída excepcional:** el precio quedó bajo el límite inferior esperado.
- **Precio sobre lo esperado:** el precio quedó sobre el límite superior esperado.
- **Dentro del rango esperado:** TimesFM no detecta una desviación excepcional.

Esta señal se adjunta después de ejecutar el análisis histórico y entre tiendas.
No agrega ni elimina ofertas, no cambia sus porcentajes, no altera su orden y no
participa en la clasificación de superofertas. Si la validación está cerrada, la
interfaz explica el motivo y continúa mostrando únicamente el análisis tradicional.
`scripts/send_predictive_alerts.py` aplica el bloqueo, evita repetir el mismo pronóstico por usuario
y solo entonces envía avisos predictivos.

Los avisos anticipados de baja usan un bloqueo más exigente: al menos 50 series,
10% de mejora frente al precio constante y 70% de acierto en la dirección. Además,
el producto debe estar sin una oferta de 10% o más, el pronóstico debe tener menos
de 48 horas, usar al menos 90 días y su cuantil superior debe seguir apuntando a
una baja de al menos 2% en 60% de los próximos siete días. El promedio pronosticado
también debe bajar al menos 5%. Así una tendencia débil no se presenta como una
“posibilidad alta”.

## Scraping adaptativo y patrones

Después de generar pronósticos, `scripts/build_scrape_priorities.py` analiza el
historial y guarda un plan por consulta de catálogo en `scrape_priorities`. Una
consulta sube de prioridad si contiene precios volátiles, patrones temporales o
una baja TimesFM que también se sostiene en el límite superior del pronóstico.
Los productos estables pasan gradualmente de revisión diaria a cada 3 o 7 días.

Tras armar el plan, `boost_watched_and_offer_priorities` adelanta catálogos con
productos en Siguiendo (`watches` + `price_alerts` de usuarios *approved*) con
score 95 e intervalo de 6 h, por encima del catálogo genérico y de candidatos de
oferta del día (score 85). Es idempotente: no dispara un scrape aparte; el batch
adaptativo solo reordena y respeta presupuesto / «Continuar». La métrica diaria
queda en `app_settings` bajo `scrape_following_boost:AAAA-MM-DD`
(`following_boosted` = catálogos seguidos boosteados ese día).

El batch solo aplica este plan cuando TimesFM ha superado la validación general.
Los productos sin plan se revisan normalmente y un plan de más de 48 horas se
descarta automáticamente, ejecutando el catálogo completo. `ADAPTIVE_SCRAPING=0`
permite desactivar la optimización temporalmente.

La generación diaria toma hasta 50 series por defecto (`FORECAST_SAMPLE`) y el
plan admite seis horas de margen para que pequeñas variaciones en la duración del
cron no conviertan una frecuencia diaria en una revisión cada dos días.

Los patrones detectados se guardan por producto en `price_patterns` y vencen si
no se renuevan. Incluyen promociones por día de semana, meses históricamente bajos,
coincidencias con ventanas Cyber, alzas prenavideñas, fin de temporada y bajas
persistentes compatibles con ciclos tecnológicos. La interfaz los describe como
asociaciones observadas y no como causas comprobadas.
