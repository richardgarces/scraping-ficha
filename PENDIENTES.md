# Pendientes

Última actualización: 24 de septiembre de 2026.

Este documento reúne trabajo pendiente o que todavía requiere validación. Una tarea solo debe marcarse como terminada después de probarla en el entorno correspondiente.

**Piloto cotizaciones y pendientes recientes:** ver [`docs/PENDIENTES.md`](docs/PENDIENTES.md).

## Prioridad alta

- [ ] Revisar los cambios locales aún no versionados en `retail/web/auth_api.py`, `retail/web/static/catalogo.html`, `retail/web/static/settings.js` y `tests/test_pricing.py`.
- [ ] Ejecutar la suite de pruebas completa y corregir cualquier regresión.
- [x] Desplegar en BMAX los cambios aprobados y verificar que la versión pública los sirva.
- [ ] Hacer una prueba funcional de producción después del despliegue: búsqueda, filtros, ficha de producto, autenticación, preferencias de tiendas y alertas.
- [ ] Retirar o actualizar `precios-web-release`; la recarga de Caddy después del despliegue ya quedó automatizada.
- [x] Reducir el contexto de construcción Docker de 618,7 MB a 13,9 MB excluyendo datos y artefactos operacionales.

## Scraping y cron

- [x] Reindexar en Qdrant las categorías históricas: 141.103 productos indexados, 0 omitidos (BMAX, 24-09-2026).
- [ ] Completar la corrida de recuperación de Retail iniciada el 24-09-2026 con sus 22.477 productos y registrar duración, errores, bloqueos y consumo de recursos.
- [ ] Confirmar que Retail incluya siempre el catálogo completo en sus corridas diarias, semanales y mensuales.
- [ ] Reintentar las tiendas o categorías que hayan terminado con error y verificar que el avance se muestre en administración.
- [ ] Evaluar concurrencia adicional entre productos usando los resultados de una corrida completa, sin aumentar bloqueos ni límites de las tiendas.
- [ ] Validar el scraper de Tika Foods con toda la colección de ofertas y comprobar precios, stock, imágenes y enlaces.
- [ ] Completar y validar la integración de Mercado Libre Chile mediante una alternativa permitida y estable, idealmente su API oficial.
- [ ] Validar las fuentes de automóviles nuevos y usados, incluyendo todas las categorías autorizadas de cada sitio.
- [x] Definir retención, almacenamiento y actualización de capturas de pantalla de las páginas donde se detectan ofertas (`retail/offer_screenshot.py`, `output/offer_screenshots/`, retención 7 días, `docs/offer_screenshots.md`).

## Alertas y notificaciones

- [x] Canal Celular (push) en Medios de alerta, prueba admin y envío integrado con preferencias de Siguiendo (pendiente validar en dispositivo real tras deploy).
- [ ] Probar de extremo a extremo las notificaciones push para usuarios autenticados: permiso, suscripción, envío, enlace y baja.
- [ ] Confirmar que una alerta seguida se active ante cualquier cambio de precio, tanto al subir como al bajar, sin solicitar un precio objetivo.
- [ ] Verificar la deduplicación de Telegram con ejecuciones simultáneas y reintentos de workers.
- [ ] Validar que los enlaces de todas las notificaciones usen `https://lnk.meincart.cl/o/<id>` y redirijan a la ficha correcta.

## Catálogo y comparación

- [ ] Auditar categorías históricas para fusionar definitivamente duplicados por mayúsculas, minúsculas, tildes y variantes singular/plural.
- [ ] Revisar falsos positivos de comparación entre productos distintos y ajustar umbrales con casos reales.
- [x] Confirmar que `Knasta` nunca se muestre al usuario: usar el comercio final cuando sea identificable y `Otro` en caso contrario.
- [ ] Validar que cada categoría abra todos sus productos y que los conteos solo sean visibles para administradores.
- [ ] Completar la revisión visual de iconos para todas las categorías normalizadas.

## Interfaz y experiencia de usuario

- [ ] Verificar en móvil que el nombre de la tienda y el botón `Ver ficha` no se superpongan en ningún ancho habitual.
- [ ] Probar que todos los menús con filtros usen el componente colapsable, indiquen filtros activos y comiencen en el estado definido.
- [ ] Confirmar que el buscador principal permanezca arriba y que las opciones y filtros aparezcan debajo cuando correspondan.
- [ ] Validar en escritorio y móvil la unión y separación de los gráficos de precio normal y precio de oferta.
- [ ] Revisar accesibilidad: navegación por teclado, foco visible, contraste, etiquetas y lectores de pantalla.
- [ ] Validar el submenú móvil para iniciar sesión y, para administradores, acceder a todas las opciones autorizadas.

## Seguridad y operación

- [ ] Revisar las protecciones contra extracción automatizada: rate limiting, cuotas, caché, reglas por IP/usuario y monitoreo de abuso.
- [ ] Confirmar que los controles anti-scraping no bloqueen buscadores permitidos, enlaces compartidos ni usuarios legítimos.
- [ ] Ocultar el menú de tiendas a usuarios normales tanto en la interfaz como en las rutas y API del servidor.
- [ ] Revisar copias de seguridad y restauración de Redis después de la reparación del AOF local.
- [ ] Definir una política periódica de limpieza local de caché Docker, archivos temporales y respaldos antiguos.

## Dependencias externas

- [ ] Confirmar DNS y certificado TLS de `lnk.meincart.cl`.
- [x] Documentar credenciales, variables de entorno y permisos necesarios para push, Telegram y acortamiento de enlaces, sin guardar secretos en Git.
- [ ] Revisar términos de uso, `robots.txt`, límites y permisos de cada fuente antes de activar nuevos scrapers en producción.

## Criterio de cierre

Para cerrar una tarea se debe registrar, como mínimo:

1. Cambio o configuración aplicada.
2. Prueba ejecutada y resultado.
3. Entorno validado: local o BMAX.
4. Fecha de despliegue cuando corresponda.
5. Evidencia o referencia al commit asociado.
