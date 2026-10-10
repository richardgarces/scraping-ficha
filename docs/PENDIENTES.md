# Pendientes

Última actualización: 5 de octubre de 2026.

Este documento reúne trabajo pendiente o que todavía requiere validación. Una tarea solo debe marcarse como terminada después de probarla en el entorno correspondiente.

El listado histórico más amplio sigue en [`PENDIENTES.md`](../PENDIENTES.md) en la raíz del repo.

## Piloto cotizaciones (MVP)

- [x] UI `/cotizaciones`, API `/api/quotes`, estados borrador → exportada, métricas admin (`GET /api/admin/purchasing-metrics`).
- [x] Despliegue BMAX con commit `3f4eb7b` (precios-web + workers habituales).
- [x] Índices Mongo idempotentes: `business_quotes` (`owner_id` + `created_at`, `owner_id` + `status`) y `business_quote_events` (`owner_id` + `at`, `quote_id` + `at`) en `retail/mongo.py`.
- [x] Alias API español `/api/cotizaciones` → mismo comportamiento que `/api/quotes`.
- [x] Acceso solo administrador (UI + API + menú Cuenta), como `/ofertas`.
- [x] Modo **lista de compra multi-tienda** (matriz lista × tiendas, grupo supermercados, export CSV, sin scrape live en request).
- [x] UX carrito: búsqueda catálogo → carrito → tiendas por categoría → Guardar / **Cotizar** (Mongo-only).
- [ ] Prueba funcional en producción con cuenta admin: carrito + Cotizar + cotización CSV, confirmar match, exportar. Checklist: [`docs/SMOKE_PROD.md`](SMOKE_PROD.md).
- [ ] Smoke de navegador en CI (`tests/browser/purchasing_smoke.py` con Playwright).
- [x] Job async Docling (conversión PDF fuera de la petición HTTP, cola/worker dedicado).
- [ ] Export XLSX / informe con marca (post-MVP).
- [ ] Despacho incluido en totales de comparación (hoy solo producto, sin inventar costos).
- [x] Unidades kg/l y conversiones de peso/volumen/longitud con reglas explícitas.
- [ ] Ventana de precio de catálogo configurable (piloto fijo 48 h; evaluar categoría + SLA por vertical).
- [ ] TimesFM, Scrapling masivo, multi-tenant comercial (fuera de este piloto).
- [x] Jumbo y Santa Isabel registrados en grupo `supermercados` (`retail/sources/jumbo.py`, `santa_isabel.py`, `STORE_GROUP`). Semilla grocery: `scripts/seed-supermercado-miss.py` (hasta salir de 0 en [`docs/tiendas.md`](tiendas.md)).
- [x] Cotizar: scrape async on-miss (`quote_miss_jobs` + pack gate envase + poll UI).
Rutas clave:

| Recurso | Ruta |
|--------|------|
| UI | `/cotizaciones` |
| API | `/api/quotes` (alias `/api/cotizaciones`) |
| Docs | [`docs/COTIZACIONES.md`](COTIZACIONES.md) |

## Prioridad alta (plataforma)

- [ ] Revisar cambios locales no versionados en auth, catálogo y pricing.
- [ ] Ejecutar suite completa de pruebas y corregir regresiones.
- [x] Desplegar en BMAX cambios aprobados (incl. piloto cotizaciones).
- [ ] Smoke post-deploy: búsqueda, ficha, auth, preferencias, alertas y `/cotizaciones` — [`docs/SMOKE_PROD.md`](SMOKE_PROD.md).
- [ ] Retirar o actualizar `precios-web-release` si aún aplica.
- [ ] Correr `scripts/seed-supermercado-miss.py` en soyo/BMAX y actualizar conteos en [`docs/tiendas.md`](tiendas.md).

## Scraping, alertas, UX, seguridad

- [x] Priorizar scrape diario de productos en Siguiendo (`watches` + `price_alerts` de usuarios approved) vía `scrape_priority_boost` + métrica `scrape_following_boost:AAAA-MM-DD`.
- [x] Piloto Scrapling en 2 fuentes HTML frágiles (`hites`, `santaritaonline`); ver [`docs/SCRAPLING.md`](SCRAPLING.md). Extra opcional `.[scrapling]` solo batch/soyo.

Ver [`PENDIENTES.md`](../PENDIENTES.md) para el detalle de scraping/cron, push, catálogo, interfaz móvil, anti-scraping y dependencias externas.

## Criterio de cierre

1. Cambio o configuración aplicada.
2. Prueba ejecutada y resultado.
3. Entorno validado: local o BMAX.
4. Fecha de despliegue y commit cuando corresponda.
