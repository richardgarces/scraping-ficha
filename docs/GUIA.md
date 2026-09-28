# Guía de la aplicación

Qué hace, cómo se arma y dónde se configura cada cosa. Para la lista de tiendas, los comandos de scraping por tienda y cómo agregar una nueva fuente, mira el [README](../README.md).

## Qué hace

Es un comparador de precios del retail chileno. Busca un producto en todas las tiendas registradas a la vez, descarta lo que no corresponde a la consulta, junta las ofertas del mismo producto y dice cuál conviene, apoyándose en el historial de precios que va acumulando.

Tres usos, en orden de cuánto trabajo te ahorran:

1. **Buscar ahora.** Escribes "tv 50 pulgadas" y en un minuto tienes las tiendas que lo venden, ordenadas, con el precio normal, el de internet y el de tarjeta de cada una.
2. **Vigilar solo.** Un cron diario recorre un catálogo de 1000 búsquedas populares, guarda los precios y te avisa por Telegram o correo cuando algo baja de verdad.
3. **Seguir un producto.** Marcas un producto con un precio objetivo y te avisa cuando llega.

La pregunta que responde y que un buscador de tienda no responde: **¿este descuento es real?** Si un producto estuvo a $100.000 tres meses, subió a $150.000 la semana pasada y hoy aparece con "40% off" a $90.000, el descuento es cierto pero la referencia es falsa. La app compara contra la mediana histórica, no contra el precio de ayer.

## Cómo está armado

| Pieza | Archivo | Qué resuelve |
|---|---|---|
| Fuentes | `retail/sources/` | Una tienda por módulo, se descubren solas |
| Motores | `retail/platforms/` | VTEX, Shopify y Magento compartidos |
| Modelo | `retail/models.py` | `Product` común y validación de descuentos |
| Relevancia | `retail/relevance.py` | Puntaje de cuánto calza el producto con la consulta |
| Intención | `retail/intent.py` | Si el producto **es** lo pedido o solo lo menciona |
| Banda de precio | `retail/priceband.py` | Si el precio vive en la nube que la consulta implica |
| Precios | `retail/pricing.py` | Mediana, mínimo, máximo y descuentos inflados |
| Persistencia | `retail/mongo.py` | Productos, historial, alertas, corridas y seguimientos |
| Semántica | `retail/qdrant_index.py` | Vectores para afinar el orden de resultados |
| Índice genérico | `retail/index/` | Qué producto es la consulta y a qué tiendas ir |
| Batch | `retail/batch/` | Catálogo, reglas, canales de alerta y cron |
| Web | `retail/web/` | API y páginas |

### Por qué hay dos bases de datos

**MongoDB** guarda el estado: cada producto con su precio actual y su historial completo, las búsquedas, las alertas emitidas, las corridas del batch y los productos que sigues. Es lo que hace posible decir "está 12% bajo su precio habitual".

**Qdrant** guarda un vector por producto y sirve para ordenar mejor: cuando buscas algo que ya buscaste antes, los resultados conocidos suben. Es un apoyo, no un requisito. Si Qdrant no está arriba la app funciona igual, solo pierde ese afinado.

**Redis** guarda dos cosas distintas:

1. El **resultado de cada búsqueda** (por ejemplo «sal») hasta la **medianoche de Chile**, en claves `search:AAAA-MM-DD:...`. Un día va de 00:00:00 a 23:59:59 en `America/Santiago`, incluidos los cambios de horario. La misma consulta, origen, tiendas y filtros reutiliza el resultado durante ese día; también se conservan búsquedas completas sin coincidencias. Los errores y búsquedas canceladas no se guardan como resultados completos. «Forzar tiendas» ignora ese caché.
2. El **índice de productos genéricos** (`retail:pindex:`): qué es la consulta (tv, no «tv led»), a qué grupos pertenece y por tanto en qué tiendas buscar. La semilla durable está en Mongo (`product_index_seed`); Redis es la copia caliente, renovada cada día por el cron y a mano con `retail indice`. Cada búsqueda deja rastro en `product_index_queries`.

Si Redis no está arriba, cada búsqueda va de nuevo a las tiendas y el índice se resuelve contra la semilla en memoria (Mongo, o el JSON si Mongo tampoco está). Si la consulta no calza con ningún genérico, se recorta a `retail` + `tecnologia` (no a todas las tiendas).

Qdrant indexa las consultas con resultados del día. Una errata de letra duplicada,
como «ssal», puede reutilizar «sal» si esa consulta sigue guardada hoy en Redis.
No se cambian modelos, capacidades, medidas ni calificadores: «sal de fruta»
conserva su propia búsqueda. La interfaz indica la consulta corregida.

Las categorías del producto se consultan completas. Al explorar categorías
adicionales fuera del índice se prueba primero una tienda: si no devuelve
productos relevantes, se salta el resto de esa categoría; si encuentra, se
consulta el resto. Un timeout o error prueba otra tienda, sin descartar la
categoría. Retail general, tiendas elegidas expresamente y categorías ya
asociadas al producto conservan su cobertura completa. Este muestreo puede
omitir hallazgos en categorías todavía desconocidas para el índice.

La comparación reproducible `python scripts/benchmark_search_categories.py`
mide consultas y tiempos con latencias simuladas, sin acceder a tiendas reales.

Claves del índice (`retail:pindex:`):

| Clave | Contenido |
|---|---|
| `retail:pindex:meta` | Versión, hash de la semilla, origen (`mongo`/`json`), fecha de carga y cantidad |
| `retail:pindex:letter:{a-z0}` | IDs de producto que empiezan con esa letra (sin tildes) |
| `retail:pindex:product:{id}` | Nombre, alias y grupos |
| `retail:pindex:alias:{alias}` | ID del producto (`televisor` → `tv`) |
| `retail:pindex:all` | Todos los IDs, para listar |

La semilla viva es la colección Mongo `product_index_seed`. `retail/index/productos.json` arranca esa colección si está vacía y sirve de respaldo local. Al arrancar la web, si Redis no tiene el índice o el hash no calza con Mongo, se recarga solo. El cron diario y `retail indice` fuerzan la recarga. Cómo se resuelve una consulta y qué tiendas salen está en [el índice de productos](indice.md).

Ninguna de las tres bases es obligatoria para buscar. Si falta alguna, la interfaz busca en las tiendas igual y avisa qué no pudo guardar.

## Puesta en marcha

```bash
cd scraping
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

docker compose up -d          # levanta Mongo, Qdrant y Redis
retail web --host 127.0.0.1 --port 8080
```

Abre `http://127.0.0.1:8080`. Para confirmar que quedó todo conectado:

```bash
curl -s http://127.0.0.1:8080/api/health
# {"ok":true,"mongo":true,"qdrant":true,"redis":true,"stores":24,"products":476}
```

Si `mongo`, `qdrant` o `redis` salen en `false`, revisa `docker compose ps`. Sin Redis cada búsqueda vuelve a las tiendas. Sin Mongo o Qdrant sigue usable, pero sin historial ni alertas.

## Configuración

Hay dos lugares donde se configura: **variables de entorno** para las conexiones y los secretos, y **archivos JSON** para las reglas de negocio. Los JSON se editan desde la interfaz web; no hace falta tocarlos a mano.

### Variables de entorno

| Variable | Default | Para qué |
|---|---|---|
| `MONGODB_URI` | `mongodb://localhost:27017` | Conexión a Mongo |
| `MONGODB_DB` | `scraping` | Base de datos |
| `QDRANT_URL` | `http://127.0.0.1:6333` | Conexión a Qdrant |
| `QDRANT_COLLECTION` | `products` | Colección de vectores |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Caché de búsquedas e índice de productos genéricos |
| `RETAIL_THUMBS` | `1` | `0` desactiva las miniaturas |
| `RETAIL_THUMB_SIDE` | `240` | Lado máximo de la miniatura en píxeles |
| `RETAIL_THUMB_LIMIT` | `24` | Miniaturas que se descargan por búsqueda |
| `RETAIL_STORE_WORKERS` | `8` | Tiendas que se consultan en paralelo por búsqueda |
| `RETAIL_SEARCH_TIMEOUT` | `12` | Timeout por tienda en la búsqueda web (el CLI sigue pasando el suyo) |

Las miniaturas se guardan en Mongo como base64 y se sirven desde `/api/thumb`. Bajarlas cuesta tiempo en cada búsqueda: si vas a correr el batch completo de 1000 productos, conviene `RETAIL_THUMBS=0`.

### Archivos de configuración

| Archivo | Contenido | Se edita en |
|---|---|---|
| `retail/batch/catalogo_electronicos.json` | Las 1000 búsquedas del batch | `/ofertas` |
| `retail/batch/reglas_ofertas.json` | Cuándo algo es oferta | `/ofertas` |
| `retail/batch/programacion.json` | Hora del cron y modo de la corrida | `/ofertas` |
| `retail/index/productos.json` | Bootstrap de genéricos (tv, leche…) si Mongo está vacío | `retail indice` |
| `output/canales.local.json` | Tokens de Telegram y SMTP | `/ofertas` |
| `scripts/ofertas-diarias.sh` | Lo que ejecuta el cron | a mano |

`output/canales.local.json` tiene credenciales: no lo subas al repositorio.

### Reglas de oferta

Definen qué merece una alerta. Viven en `retail/batch/reglas_ofertas.json` y se editan en `/ofertas`.

```json
{
  "enabled": ["price_drop_percent", "price_drop_amount", "cross_store_gap", "below_median"],
  "min_price": 10000,
  "max_price": null,
  "price_drop_percent": 40.0,
  "price_drop_amount": 20000,
  "cross_store_gap_percent": 10.0,
  "below_median_percent": 12.0,
  "ignore_fake_discounts": true,
  "digest": true,
  "digest_top": 25,
  "channels": ["log", "file", "telegram", "email"]
}
```

| Regla | Dispara cuando |
|---|---|
| `price_drop_percent` | El precio bajó ese porcentaje respecto de la última medición |
| `price_drop_amount` | El precio bajó esa cantidad de pesos |
| `cross_store_gap` | La tienda más barata está ese porcentaje bajo la segunda |
| `below_median` | El precio está ese porcentaje bajo su mediana histórica |

`enabled` decide cuáles corren: una regla con su valor configurado pero fuera de esa lista no dispara. `min_price` y `max_price` acotan el rango de precios que vale la pena mirar, para no llenarte de alertas de artículos de $2.000.

`ignore_fake_discounts` es la más importante. Con `true`, una baja que solo deshace un alza reciente no genera alerta. La lógica está en `fake_discount()` de `retail/pricing.py`: toma como referencia la mediana de los últimos 90 días **ignorando la última semana**, para que el alza reciente no contamine la referencia.

### Canales de alerta

`channels` acepta cuatro destinos:

- `log`: a la salida estándar
- `file`: una línea JSON por alerta en `output/alerts.jsonl`
- `telegram`: mensaje al chat configurado
- `email`: correo por SMTP

Los dos últimos necesitan credenciales, por variable de entorno o desde `/ofertas` (que las guarda en `output/canales.local.json`). La variable de entorno tiene prioridad.

Para cada destinatario y canal, un mismo producto al mismo precio no vuelve a
notificarse durante **5 días (120 horas)**. Esta ventana se comparte entre
ofertas, productos seguidos y alertas predictivas. Si el precio cambia y luego
vuelve a un valor ya notificado, se respeta la fecha del aviso de ese valor;
los intentos repetidos no reinician la espera.

### Resumen en vez de goteo

Con `digest` en `true` (lo predeterminado), Telegram y correo reciben **un solo mensaje al terminar la corrida** con las mejores `digest_top` ofertas ordenadas por ahorro y agrupadas por categoría. Importa con catálogos grandes: una corrida sobre las 2957 categorías de Falabella puede levantar cientos de alertas, y una notificación por hallazgo termina con el canal silenciado.

Si la tienda entrega una imagen del producto, las notificaciones de Telegram y correo incluyen la imagen de la mejor oferta. Si Telegram no puede descargarla, envía automáticamente el texto sin imagen.

`log` y `file` siguen registrando cada alerta por separado, así que no se pierde nada: el detalle completo queda en `output/alerts.jsonl` y en Mongo, y se ve en `/hoy`.

Los productos que sigues desde `/siguiendo` son la excepción: esos avisan al instante por todos los canales, porque son los que pediste explícitamente.

```
TELEGRAM_BOT_TOKEN   TELEGRAM_CHAT_ID
SMTP_HOST   SMTP_PORT   SMTP_USER   SMTP_PASSWORD   SMTP_FROM   ALERT_EMAIL_TO
```

`SMTP_PORT` por defecto es 587.

### Programación del cron

`retail/batch/programacion.json` guarda hora base, modo y pausa. El modo por defecto es **un cron por grupo de tiendas** (`groups.mode: per_group`), escalonado cada `stagger_minutes` (45). Los grupos salen de Mongo `store_categories` (bootstrap desde el registry). Desde `/ofertas` el botón instala las líneas en tu crontab; también a mano:

```cron
# retail-ofertas-begin
0 6 * * * /ruta/al/proyecto/scripts/ofertas-diarias.sh retail
45 6 * * * /ruta/al/proyecto/scripts/ofertas-diarias.sh farmacias
… (un slot por grupo)
# retail-ofertas-end
```

En BMAX el host usa `scripts/ofertas-diarias-bmax.sh <grupo>` (prod-menu opción 8 / `install-host-cron.sh`).

| Campo | Qué hace |
|---|---|
| `enabled` | Si las líneas quedan instaladas en el crontab |
| `hour` / `minute` | Hora del **primer** grupo |
| `groups.mode` | `per_group` (default) o `single` (un solo batch sin filtro) |
| `groups.stagger_minutes` | Minutos entre grupos (5–180) |
| `groups.enabled` | `null` = todos; o lista `["tecnologia","retail"]` |
| `source` | `scrape`, `db` o `both` |
| `pause` | Segundos entre productos del catálogo |

A mano: `retail batch --grupo tecnologia` (o `retail batch tecnologia`). Sin `--grupo` corre el catálogo completo (y los seguidos). Con grupo, solo tiendas de esa categoría y consultas del catálogo cuyo genérico en `product_index_seed` incluye el grupo.

`pause` es el freno: con 1000 productos y 3 segundos, una corrida completa toma varias horas. Bájalo con cuidado, las tiendas cortan si las golpeas seguido.

El script lee source/pause solo; para cambiar la hora base o el stagger hay que reinstalar el cron (opción 8 en BMAX).

### El catálogo del batch

`retail/batch/catalogo_electronicos.json` tiene 1000 búsquedas repartidas en 27 categorías. Cada ítem es así:

```json
{
  "id": "celular-galaxy-s25-512gb",
  "query": "celular galaxy s25 512gb",
  "category": "smartphones",
  "brand": "Samsung"
}
```

El `id` tiene que ser único: identifica al producto entre corridas y es lo que usas con `--ids`. La `category` alimenta el filtro por categoría del catálogo web.

### Categorías de Falabella

`data/falabella_categorias.json` tiene las 2957 categorías publicadas por falabella.cl, cada una con su identificador listo para `retail falabella categoria CATG10000 --nombre Cocina`. Sirve para armar catálogos nuevos sin adivinar IDs.

```bash
python scripts/falabella_categorias.py              # solo la lista
python scripts/falabella_categorias.py --jerarquia  # agrega padres y ruta
```

La lista sale del sitemap que declara el `robots.txt` de la tienda, que es la fuente completa; no existe un endpoint con el árbol de categorías. La jerarquía es opcional porque cuesta una petición por categoría: agrega `parent_id`, `parents`, `depth` y `path` ("Niños y Juguetería - Juguetes / Figuras de acción y coleccionables / Figuras de Acción"). Guarda cada 25 categorías, así que se puede cortar y retomar.

## Las páginas

| Ruta | Para qué |
|---|---|
| `/` | Buscar en las tiendas ahora |
| `/catalogo` | Navegar lo ya guardado, sin buscar |
| `/hoy` | Ofertas del día con el ahorro real y el resumen de la corrida |
| `/producto` | Ficha con historial de 7/30/90 días, "¿compro o espero?" y precios de otras tiendas |
| `/tiendas` | Qué tan confiable es el "antes" de cada cadena |
| `/siguiendo` | Productos con precio objetivo |
| `/ofertas` | Reglas, canales, catálogo y cron |

En la búsqueda, si dejas **Todas** las tiendas, el índice elige los grupos que corresponden al producto («Buscando TV en Tecnología, Retail, Hogar, Supermercados»). Si marcas un subconjunto a mano, se respeta esa elección. La tabla filtra por tienda, marca, rango de precio y descuento mínimo, con el conteo de cada opción, y ordena por precio, descuento o cuánto está bajo lo habitual.

### Cómo leer los precios

Cada fila muestra el precio efectivo arriba y debajo la escalera tal como la publica la tienda:

> **$499.990** · con tarjeta CMR · Internet $519.990 · Normal ~~$1.089.990~~

El rótulo de la tarjeta importa: ese precio solo lo consigues con la tarjeta de esa cadena. Sin la marca estarías comparando un precio con tarjeta CMR contra uno que no exige nada.

El porcentaje es el que anuncia la tienda, validado contra la resta de precios por `sane_discount()` en `retail/models.py`. Se agregó porque Lider mandaba el ahorro en pesos en el campo del porcentaje y aparecían descuentos de -10819%.

### ¿Compro o espero?

La ficha del producto responde con el patrón del propio producto, en `buy_or_wait()` de `retail/pricing.py`: cada cuánto baja, cuánto baja cuando lo hace, y dónde queda el precio de hoy dentro de todo lo que le hemos visto.

- **Conviene comprar**: está en su mínimo, o a menos de 10% de él
- **Conviene esperar**: suele bajar cada N días y la última fue hace menos, o está en la parte alta de su rango
- **Todavía no se puede decir**: con menos de 14 días de historial no opina, y dice cuántos días faltan

Esa última respuesta es a propósito. Un veredicto sacado de tres días de datos es peor que no dar ninguno, porque igual se lee como una recomendación.

### Cuánto vale el "antes" de cada tienda

`/tiendas` cuenta, cadena por cadena, cuántas de sus bajas de precio solo deshacen un alza de los días previos. Usa el mismo criterio que la alerta de descuento falso, pero agregado. Necesita al menos 30 días de historial para decir algo: con menos, la página lo advierte arriba.

### El historial de precios

Es lo que sostiene todo lo anterior, y se guarda en `price_history` dentro de cada producto: **un punto por día, más cualquier cambio dentro del mismo día**, con tope de 400 puntos, que son unos trece meses.

La condición está en `should_record()` de `retail/mongo.py` y no es un detalle. Antes cada búsqueda empujaba su punto sin preguntar: en una corrida del catálogo de categorías un mismo televisor aparece en decenas de búsquedas, así que la ventana se gastaba en días y las estadísticas se quedaban sin pasado que mirar.

### Qué se descarta de los resultados

Buscar "tv 50 pulgadas" traía racks y soportes, porque comparten todas las palabras de la consulta. `retail/intent.py` decide si el producto es lo pedido:

- Descarta accesorios (`rack`, `soporte`, `funda`, `cargador`…) cuando no los pediste
- Descarta los nombres del tipo "para TV" o "compatible con"
- Descarta muebles cuando el aparato buscado nunca lo es
- Descarta las medidas que no calzan: un TV de 55" no aparece si pediste 50"

Después de eso, `retail/priceband.py` mira los precios que quedaron. Si hay una nube clara (varios productos en un rango y otro aislado muy lejos), descarta el que no calza. Buscar "tv" no mezcla un conversor de $9.990 con televisores de $300.000. Si pediste "tv barato" o "notebook gamer", elige la nube barata o la cara. Con pocos resultados, o si todos los precios están cerca, no recorta. En la búsqueda hay un check **Filtrar banda de precio** (activo por defecto) para apagarlo.

El resumen de cada búsqueda dice cuántos se fueron por cada motivo, para que el filtro no sea una caja negra. Si ves que descarta de más, los diccionarios `DEVICES` y `ACCESSORIES` de `retail/intent.py` son la perilla.

### Cuándo dos tiendas venden lo mismo

Es lo que sostiene toda la comparación, y vive en `retail/compare.py`. Dos productos quedan en el mismo grupo si comparten **cualquiera** de estas señales:

- El mismo código de barras, validado con su dígito de control
- La misma huella de identidad: marca, modelo, almacenamiento y pulgadas
- La misma familia de modelo, cuando una tienda publica el código largo del fabricante (`UN50U8000HGXZS`) y otra el corto (`U8000H`)

Basta una para unirlos, y eso importa: antes se agrupaba por una sola clave y cada tienda caía en un espacio distinto, así que un producto con código de barras en Líder nunca se juntaba con el mismo producto sin código en Falabella.

Dos cuidados que evitan comparar peras con manzanas:

- **Las pulgadas entran en la huella.** Un U8000H de 43" y uno de 65" son productos distintos. Sin esto compartían código y la regla `cross_store_gap` anunciaba un ahorro enorme que en realidad era la diferencia de tamaño.
- **No todo número largo es un código de barras.** Tottus manda su SKU de 9 dígitos y Ripley uno del rango `200`, que GS1 reserva para uso interno de cada comercio. Los `product_id` de Falabella tienen 8 dígitos y uno de cada diez pasa el dígito de control por casualidad. Se exige largo válido, verificador correcto, y prefijo chileno `780` para los de 8 dígitos.

Las variantes de un mismo aviso (una cortina en cuatro anchos, con cuatro `product_id`) se guardan todas por separado en Mongo pero se muestran en una sola fila, con la más barata y el rango de las otras.

Al cambiar estas reglas, los productos ya guardados conservan el código con que se calcularon. Para ponerlos al día:

```bash
retail recodificar --dry-run   # cuántos cambiarían
retail recodificar             # aplicar
```

## Comandos

```bash
retail web --host 127.0.0.1 --port 8080   # interfaz
retail tiendas                            # fuentes registradas
retail batch --dry-run                    # ver el catálogo sin scrapear
retail batch --limit 5                    # probar con los primeros 5
retail batch --grupo tecnologia --dry-run # solo tiendas de ese grupo
retail batch --ids galaxy-s25-512,iphone-16-128
retail batch                              # corrida completa (todos + seguidos)
retail recodificar                        # recalcular códigos de comparación
retail indice                             # recargar genéricos + store_categories
retail indice letra t                     # tv, tablet, taladro…
retail indice resolver "tv 50 pulgadas"   # → tv
retail indice sin-match                   # consultas sin genérico
```

Opciones de `batch`:

| Opción | Para qué |
|---|---|
| `--grupo` / positional | Solo ese grupo de tiendas (Mongo `store_categories`) |
| `--catalogo` | Otro JSON de productos |
| `--reglas` | Otro JSON de reglas |
| `--source` | `scrape`, `db` o `both` |
| `-n / --max` | Productos por tienda en cada búsqueda |
| `--delay` | Pausa entre requests dentro de una búsqueda |
| `--pausa` | Pausa entre productos del catálogo |
| `--limit` | Solo los primeros N |
| `--ids` | IDs del catálogo separados por coma |
| `--dry-run` | Lista sin scrapear |

Antes de dejar el cron suelto, corre `retail batch --limit 5` y revisa que lleguen las alertas por donde esperas.

## Diagnóstico

```bash
curl -s http://127.0.0.1:8080/api/health          # conexiones y conteo
tail -f logs/ofertas-diarias.log                  # qué hizo el cron
tail -f output/alerts.jsonl                       # alertas emitidas
python -m pytest tests -q                         # 78 tests
```

Si una tienda deja de responder, la búsqueda no se cae: el resultado trae `store_errors` con el detalle y la interfaz lo muestra abajo.

## Uso responsable

Respeta los términos de cada tienda y no bajes el `delay` sin necesidad. Lider usa PerimeterX: las fichas `/ip/` y algunas categorías por slug se bloquean, por eso el cliente usa la búsqueda pública `/browse?query=`. Mercado Libre responde 403 al listado general, así que se usan las ofertas públicas.
