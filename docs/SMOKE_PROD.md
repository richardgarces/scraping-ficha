# Smoke post-deploy (producción)

Checklist para cerrar la validación funcional tras un despliegue en BMAX.
Marcar cada ítem solo tras probarlo en el entorno real (fecha + cuenta usada).

Base: `https://precios.meincart.com` (ajustar si el host cambia).

## 1. Salud

- [ ] `GET /api/health` → `ok: true`, `mongo: true`, `degraded: false`, `redis` y `qdrant` según diseño, `products` > 0.
- [ ] Si `degraded: true` o `mongo_error` distinto de `null`/`unavailable`, no continuar el smoke hasta reparar Mongo.
- [ ] `real_offer_worker.healthy` y `cyber_day.worker_healthy` coherentes con los contenedores activos.

## 2. Público

- [ ] `/` búsqueda conocida (p. ej. un genérico del índice) con resultados o mensaje claro; stream sin colgarse.
- [ ] `/catalogo` navega categorías/tiendas.
- [ ] `/hoy` lista ofertas del día o vacío explicable.
- [ ] `/producto?store=…&id=…` ficha con precio e historial (o aviso si falta).

## 3. Auth y cuenta

- [ ] `/entrar` login admin y usuario approved.
- [ ] Tras login, `next=/pronosticos`, `next=/tiendas`, `next=/cambios-precio`, `next=/cotizaciones` redirigen al destino (admin).
- [ ] Preferencias de tiendas en cuenta se guardan y vuelven a cargar.
- [ ] `/siguiendo`: alta/baja de watch; prueba admin de push si hay VAPID configurado.

## 4. Login-gated

- [ ] `/reales` muestra ofertas del día (`is_real`) o vacío con worker al día (revisar jobs failed si vacío inesperado).
- [ ] `/reales?super=1` (alias `/super`) filtra super ofertas.
- [ ] `/comparar?store=…&id=…` abre comparación para cuenta approved.

## 5. Admin

- [ ] `/ofertas`, `/cron`, `/cyber-day`, `/estadisticas`, `/usuarios`, `/tiendas`, `/pronosticos`, `/cambios-precio`, `/analisis-producto`, `/cotizaciones` abren con sesión admin.
- [ ] Miembro approved **no** ve Análisis en el menú y recibe redirect/403 en `/analisis-producto` y `POST /api/product-analysis`.
- [ ] `/cron`: última corrida visible; si el host cron falló un grupo, el exit code del script no debe ser 0 (`ofertas-diarias-soyo.sh`).
- [ ] `/cotizaciones`: lista multi-tienda (grupo supermercados) + export CSV de cotización; badges de frescura 48 h coherentes.
- [ ] Push/Telegram de prueba desde Medios de alerta (admin) llega al canal configurado; enlaces `https://lnk.meincart.cl/o/<id>` resuelven a ficha.

## 6. Supermercados / Jumbo

- [ ] Confirmado en registry: `jumbo` y `santa_isabel` en grupo `supermercados`.
- [ ] Si aún tienen 0 productos en Mongo, programar probe/scrape (ver `docs/tiendas.md`); la matriz de cotizaciones no inventará filas.

## Criterio de cierre

Registrar en `docs/PENDIENTES.md` / `PENDIENTES.md`: fecha, commit desplegado, cuenta de prueba y resultado por sección. Solo entonces marcar el smoke post-deploy como hecho.
