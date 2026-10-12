# Auditorías de calidad

Las auditorías son herramientas internas y no modifican los precios, la identidad
ni la publicación de productos. Ambas conservan sus datos históricos en MongoDB.

## Auditoría del matching de búsquedas

### Muestra y estratificación

La muestra toma búsquedas de personas de `searches` con `relation_status:
complete` de los últimos 30 días. Excluye las filas de procesos batch y las
búsquedas sin resultados de producto utilizables. Consultas normalizadas se
consolidan en una sola búsqueda: se conserva su resultado más reciente y se
cuenta cuántas veces apareció en la ventana.

La frecuencia se divide en terciles `low`, `medium` y `high`; los empates
permanecen juntos, así que un bucket puede quedar vacío. Para determinar la
categoría y tienda de una búsqueda se usa la categoría y tienda más frecuentes
entre sus hasta tres primeros resultados guardados; los empates siguen el orden
de resultados. Se forma cada estrato con **categoría × tienda × frecuencia**.
Los 300 cupos se asignan proporcionalmente al tamaño de cada estrato con el
método de restos mayores y se eligen búsquedas aleatorias dentro de cada estrato.
No se fuerza un mínimo por estrato pequeño. La semilla aleatoria queda guardada
en la corrida para poder explicar y reproducir la asignación. Una búsqueda
seleccionada genera hasta tres comparaciones, por lo que una corrida tiene un
máximo de 900.

### Uso de la interfaz

1. La auditoría parte **desactivada**. Una persona administradora aprobada
   puede habilitarla en **Configurar → Auditoría de matching** (`/ofertas`).
   El ajuste se guarda en `app_settings` y se aplica a la página y a todos sus
   endpoints. Si se apaga, las corridas históricas se conservan pero la vista
   y la API dejan de estar disponibles.
2. Con la opción habilitada, abre `/auditoria-matching` (también está enlazada
   desde Análisis de producto) y selecciona **Crear muestra**. La interfaz
   conserva las corridas anteriores.
3. Cada comparación debe ser etiquetada por dos administradores distintos:
   **Exacta**, **Variante**, **No equivalente** o **Incierta**. La nota es
   opcional. Un revisor no puede ocupar ambos espacios.
4. Los desacuerdos aparecen en **Arbitraje de desacuerdos** y solo puede
   resolverlos una tercera persona.
5. **Exportar CSV** descarga las comparaciones con snapshots y etiquetas,
   separado por punto y coma y codificado en UTF-8.

La vista `/auditoria-matching` y su copia estática directa quedan protegidas
por el mismo interruptor. Todos los endpoints están bajo
`/api/admin/matching-audit/` y vuelven a validar el rol administrador; la
protección de la página HTML no es la única barrera.

También se puede crear la muestra desde línea de comandos, respetando el mismo
interruptor administrativo:

```bash
.venv/bin/python -m retail.matching_audit
.venv/bin/python -m retail.matching_audit --seed 42 --search-count 100
```

La segunda forma se limita a 100 búsquedas; ambas guardan la corrida en Mongo y
devuelven sus conteos/estratos en JSON. El tamaño permitido es de 1 a 300.

### Métricas

- **Matching exacto** = etiquetas finales `exact` / etiquetas finales
  concluyentes (`exact`, `variant`, `not_equivalent`). `uncertain` y
  comparaciones aún no resueltas no entran al denominador.
- **Kappa de Cohen** es nominal, con las cuatro etiquetas. Si una corrida usa
  varios pares de revisores, se calcula kappa por cada par estable de personas
  y se informa el promedio ponderado por sus comparaciones dobles; la interfaz
  muestra también el número de pares y el número de dobles revisiones. Una
  categoría degenerada sin kappa calculable se excluye del promedio.

### Colecciones

| Colección | Contenido principal |
|---|---|
| `matching_audit_runs` | `_id`, `created_at`, `created_by`, `seed`, `status`, `search_window_days`, `search_count_requested`, `recent_query_count`, `eligible_query_count`, `sampled_search_count`, `comparison_count`, `strata_allocations`, `completed_build_at`. |
| `matching_audit_items` | `_id`, `run_id`, `search_id`, `product_id`, `query`, `query_normalized`, `search_created_at`, `category`, `store`, `frequency_count_30d`, `frequency_bucket`, `position`, snapshot `offer`, `reviewer_ids`, `status`, `final_label`, `arbitrator_id`, `arbitration_note`, `created_at`, `resolved_at`. Índice único por corrida/búsqueda/tienda/producto. |
| `matching_audit_reviews` | `_id`, `run_id`, `item_id`, `reviewer_id`, `label`, `note`, `created_at`. Índice único por corrida/comparación/revisor. |
| `app_settings` | Documento `_id: "matching_audit"` con `enabled` y `updated_at`; si falta, el valor es `false`. |

## Verificación de ofertas publicadas

### Ejecución

El job toma hasta 100 ofertas aleatorias elegibles de las ofertas reales
publicadas durante el día de Chile. Usa el mismo criterio público de ofertas
vigentes y comparables; no publica ni repara datos.

```bash
MONGODB_URI="mongodb://localhost:27017" \
MONGODB_DB="scraping" \
.venv/bin/python -m retail.offer_verification
```

Para una corrida pequeña o una carpeta de reportes distinta:

```bash
.venv/bin/python -m retail.offer_verification \
  --sample-size 25 \
  --report-directory reports/offer-verification
```

Para automatizarlo, agenda ese comando una vez por semana en un scheduler
configurado para la zona `America/Santiago`. Por ejemplo, si el cron del host
usa esa zona, ejecuta el job los lunes a las 04:30. El comando devuelve el ID,
los conteos y la ruta del informe como JSON; el proceso falla con código no
cero si no puede completar y guardar la corrida.

### Política de verificación

- El job limita las URLs a los dominios registrados para cada tienda y a los
  puertos web estándar. No sigue una redirección a un host ajeno a esa tienda.
- Consulta `robots.txt` antes de cada URL/API del parser, respeta `Crawl-delay`
  y `Request-rate` y aplica como mínimo un segundo entre peticiones al mismo
  origen. La política de robots se cachea por una hora y el limitador de tasa
  se comparte entre las sesiones del job.
- Una URL bloqueada por robots o un campo que el parser no pueda confirmar
  queda como **No verificado**, no como diferencia ni como éxito. Una URL que
  responde con error HTTP o falla al conectarse se cuenta como no funcional.
- Se contrastan por separado precio sin tarjeta, precio normal, precio con
  tarjeta, precio con cupón, condiciones/código, stock y despacho. El stock
  solo se compara si la referencia y la observación están verificadas. Costos
  de despacho solo se comparan si la región coincide.

### Métricas y reportes

- **Enlaces funcionales** = respuestas HTTP finales exitosas / URLs intentadas
  con resultado (`functional` o `broken`). URLs que no se pudieron intentar
  por política robots se informan aparte.
- **Discrepancia de precio sin tarjeta** = precios comparables distintos /
  precios comparables. Se reportan además la diferencia absoluta media en CLP
  y la diferencia relativa media entre los precios discrepantes verificables.
- La tabla de cobertura del Markdown registra comparables, diferencias y
  campos no verificados para todos los precios, condiciones, stock y despacho.
- Cada corrida compara esos indicadores agregados con la corrida completada
  más reciente de al menos seis días antes. Las muestras son aleatorias e
  independientes, no un panel de los mismos productos.
- El informe se escribe en
  `reports/offer-verification/offer-verification-<run_id>.md` por defecto.
  La fecha del informe está en hora de Chile; la base guarda timestamps UTC.

| Colección | Contenido principal |
|---|---|
| `offer_verification_runs` | `_id`, `started_at`, `finished_at`, `status`, `requested_sample_size`, `sample_size`, `source_day`, `selection_method`, `candidate_count`, objeto `metrics`, `previous_run_id`, `report_path`, `error`. |
| `offer_verification_checks` | `_id`, `run_id`, `store`, `source_product_id`, `product_id`, `url`, `final_url`, `checked_at`, `url_status`, `url_response_status`, `verification_status`, `verification_error`, snapshots `expected`/`observed`, mapa `differences`, `parser_updated_at`. Índices únicos por corrida/tienda/producto y por tienda/fecha. |

## Despliegue y permisos

La página de revisión requiere una sesión aprobada de administrador. El job de
ofertas se ejecuta como proceso CLI independiente en el entorno que tenga
acceso a MongoDB y a la salida `reports/`. Las nuevas colecciones e índices se
crean con los índices de `ProductRepository`; no hay migración destructiva.
Antes de usar la interfaz o programar el job en producción, despliega el código
y confirma que la aplicación y el worker comparten la misma base `MONGODB_DB`.
