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
- [ ] Prueba funcional en producción con cuenta admin: import CSV, confirmar match, exportar CSV.
- [ ] Smoke de navegador en CI (`tests/browser/purchasing_smoke.py` con Playwright).
- [x] Job async Docling (conversión PDF fuera de la petición HTTP, cola/worker dedicado).
- [ ] Export XLSX / informe con marca (post-MVP).
- [ ] Despacho incluido en totales de comparación (hoy solo producto, sin inventar costos).
- [x] Unidades kg/l y conversiones de peso/volumen/longitud con reglas explícitas.- [ ] Ventana de precio de catálogo configurable (piloto fijo 48 h; evaluar categoría + SLA por vertical).
- [ ] TimesFM, Scrapling masivo, multi-tenant comercial (fuera de este piloto).

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
- [ ] Smoke post-deploy: búsqueda, ficha, auth, preferencias, alertas y `/cotizaciones`.
- [ ] Retirar o actualizar `precios-web-release` si aún aplica.

## Scraping, alertas, UX, seguridad

Ver [`PENDIENTES.md`](../PENDIENTES.md) para el detalle de scraping/cron, push, catálogo, interfaz móvil, anti-scraping y dependencias externas.

## Criterio de cierre

1. Cambio o configuración aplicada.
2. Prueba ejecutada y resultado.
3. Entorno validado: local o BMAX.
4. Fecha de despliegue y commit cuando corresponda.
