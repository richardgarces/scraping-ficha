# Índice de productos genéricos

Qué consulta es (tv, no «tv led»), a qué grupos de tiendas pertenece y por tanto **en cuáles scrapear**. No filtra accesorios ni ranking: eso sigue en `intent` y `relevance`. El código vive en `retail/index/` y se aplica en `retail/search.py` cuando no marcaste un subconjunto de tiendas a mano.

## Para qué sirve

Sin el índice, «tv 50 pulgadas» iría a las 150 tiendas registradas, incluidas farmacias y ferreterías que no venden televisores. Con el índice:

1. La consulta se reduce a un **producto genérico** (`tv`, `leche`, `taladro`…).
2. Ese genérico declara **grupos** (`tecnologia`, `supermercados`, `ferreteria`…).
3. Solo se consultan las tiendas cuyo `STORE_GROUP` en `retail/registry.py` está en esos grupos.

Si la consulta no calza con ningún genérico, **no** se recorren las ~150 tiendas. El recorte base es `retail` + `tecnologia` (department stores y electrónica: Falabella, PC Factory, etc.). Quedan fuera moda, té, calzado, etc. Si la consulta **parece medicamento** (`retail.intent.looks_pharmacy`: formas como jarabe/comprimido, palabras de farmacia, sufijos tipo INN, o nombre + dosis `500 mg` — nunca `mg` solo), se suman `farmacias` y `supermercados`. Una palabra al azar (`xyzzy`, `colun`) no activa farmacias; `notebook` resuelve a genérico de tecnología y tampoco las incluye.

## Semilla en Mongo, copia viva en Redis

La **verdad** de los genéricos vive en Mongo, colección `product_index_seed` (base `scraping`, el mismo cliente que productos y búsquedas). Cada documento es un ítem como el JSON: `id`, `name`, `aliases`, `groups`, más `updated_at`, `hit_count` y `last_seen_at`.

`retail/index/productos.json` (hoy 73 genéricos, `version: 1`) no se borra: **arranca** Mongo si la colección está vacía y queda de respaldo si Mongo no está. Al cargar con `retail indice` o el cron diario, los `id` del JSON que aún no están en Mongo se insertan; los documentos que ya existen **no se pisan** (se conservan nombre, grupos y estadísticas). Los **alias nuevos del JSON** sí se suman (`$addToSet`): por eso `mini led` / `miniled` llegan a un `tv` que ya vivía en Mongo. Genéricos nuevos del JSON (p. ej. `ozempic`, `medicamento`) también se insertan por ese upsert.

Redis bajo `retail:pindex:` sigue siendo la copia de trabajo: se consulta en cada búsqueda. El hash SHA-256 de 16 caracteres en `retail:pindex:meta` se calcula sobre la semilla **Mongo** (versión + id/name/aliases/groups). Si no calza, la web recarga sola al arrancar. El cron diario y `retail indice` fuerzan la recarga aunque el hash no haya cambiado.

Cada búsqueda escribe un documento en `product_index_queries` (texto, fold, `product_id` o nulo, grupos, `store_count`, `applied`, fecha). Si resolvió un genérico, sube `hit_count` y `last_seen_at` en la semilla y, si la consulta trae tokens de más, esos tokens se suman como **alias del mismo genérico** (`jbl` y `partibox` en «parlante jbl partibox» quedan en el documento `parlante`). Si no resolvió, la consulta queda en la cola de sin-match (`unmatched: true`) para que un humano pueda promoverla a alias; **no** se crean productos desde texto libre (`colun` no se vuelve un genérico).

| Clave | Contenido |
|---|---|
| `retail:pindex:meta` | `version`, `seed_hash`, `loaded_at`, `count`, `source` (`mongo` o `json`) |
| `retail:pindex:manifest` | Lista de claves escritas, para borrar las que ya no existen |
| `retail:pindex:letter:{a-z0}` | Set de IDs que empiezan con esa letra (sin tildes; dígitos van a `0`) |
| `retail:pindex:product:{id}` | JSON con nombre, alias y grupos |
| `retail:pindex:alias:{alias}` | ID del genérico (`televisor` → `tv`) |
| `retail:pindex:all` | Todos los IDs |
| `retail:pindex:sweep:{id}` | Candado del barrido extra (`tv`). TTL: resto del día en Chile, mínimo 4 h |

Los alias se guardan ya plegados: sin tildes, en minúsculas, y también sin espacios (`smart tv` y `smarttv`).

## Cómo se resuelve la consulta

1. Se pliega el texto (`fold` de `retail/relevance.py`): tildes fuera, minúsculas, guiones y barras como espacio. «Televisión» y «televisor» quedan comparables.
2. Se arman candidatos de **más tokens a menos**: frases enteras, la misma frase sin espacios, y cada subcadena. Los tokens que son solo dígitos (`50`) se descartan.
3. El primero que exista como `retail:pindex:alias:…` gana. Por eso «silla de auto bebe» cae en `silla-auto` y no en `silla`: el alias largo `silla de auto` se prueba antes que `silla`.
4. Con ese ID se lee `retail:pindex:product:{id}` y salen los grupos.
5. `stores_for` recorre las tiendas disponibles y deja las cuyo grupo está en esa lista, **en el mismo orden**.

Si Redis falla a mitad de camino, se usa la semilla en memoria (Mongo si ya se cargó al arrancar; si no, el JSON).

## Ejemplo: «tv 50 pulgadas»

En `/` dejas **Todas** las tiendas (o no mandas `stores` en la API) y buscas `tv 50 pulgadas`.

El JSON de `tv` en la semilla es:

```json
{
  "id": "tv",
  "name": "TV",
  "aliases": ["televisor", "televisores", "smart tv", "television", "televisiones", "tvs", "tele", "mini led", "miniled"],
  "groups": ["tecnologia", "retail", "hogar", "supermercados"]
}
```

**Plegado.** La consulta ya está en minúsculas y sin tildes: `tv 50 pulgadas`. (Si hubieras escrito «Televisión 55», el fold daría `television 55` y el alias que pega es `television`, no `tv`.)

**Candidatos**, del más largo al más corto: `tv 50 pulgadas`, `tv50pulgadas`, `tv 50`, `tv50`, `50 pulgadas`, `50pulgadas`, `tv`, `pulgadas`. `50` solo no entra porque es un número.

**Lectura en Redis.** Un `MGET` sobre esas claves `retail:pindex:alias:…`. Las primeras no existen. La que pega es:

| Clave | Valor |
|---|---|
| `retail:pindex:alias:tv` | `tv` |
| `retail:pindex:product:tv` | `{"id":"tv","name":"TV","aliases":[…],"groups":["tecnologia","retail","hogar","supermercados"]}` |

El resto de candidatos (`pulgadas`) no se usa: gana el primero que existe. No hay un genérico «tv led»; «TV LED 50» también cae en `tv` porque en la lista aparece el token `tv`. «mini led» y `miniled` son alias de `tv` (mismo set de grupos). `tv mini` y `tv mini led` ya pegaban por el token `tv`.

**Grupos → tiendas.** De las 150 de `STORE_GROUP`, quedan **33**:

| Grupo | Cuántas | Ejemplos que sí entran |
|---|---|---|
| `tecnologia` | 7 | `pcfactory`, `belkin`, `centrale`, `migo`, `motorola`, `movistar`, `entel` |
| `retail` | 4 | `falabella`, `paris`, `ripley`, `mercadolibre` |
| `hogar` | 17 | `ikea`, `rosen`, `cannon`, `flex`, `kitchencenter` |
| `supermercados` | 5 | `lider`, `tottus`, `unimarc`, `alvi`, `cugat` |

No entran, entre otras: `ahumada` / `cruzverde` (farmacias), `sodimac` / `easy` (ferretería), `audiomusica` (música), `nike` (deporte).

La interfaz lo dice en el resumen: «Buscando TV en Tecnología, Retail, Hogar, Supermercados (33 tiendas)». Eso sale de `product_index` cuando `applied` es verdadero (`productIndexLabel` en `retail/web/static/app.js`).

Para verlo sin buscar:

```bash
retail indice resolver "tv 50 pulgadas"
# «tv 50 pulgadas» → tv (TV) · Tecnología, Retail, Hogar, Supermercados
```

**Si marcas tiendas a mano.** En la web, si no están todas las casillas, se manda `stores=lider` (o las que hayas dejado). `_explicit_store_filter` en `search.py` trata eso como elección explícita: **no se recorta** la lista. Sigue resolviendo el genérico (el payload trae `id: tv`) pero `applied` queda en `false` y se scrapea solo lo que pediste. «Forzar tiendas» del caché de 24 h es otra palanca; esto es solo el recorte por grupos.

**Si la consulta no es un genérico.** `colun` (sin «leche») no tiene alias. `resolve` devuelve `None` y `stores_for` recorta a `retail` + `tecnologia` (no las 150). Si además parece médico (p. ej. una marca no indexada con forma `…statina` o `… 500mg`), suma `farmacias` + `supermercados`.

## Cuándo se aplica y cuándo no

| Qué eligió el usuario | Qué pasa |
|---|---|
| Nada, o las 150 tiendas (Todas) | Se enruta con el índice si hay genérico |
| Un subconjunto (`stores=lider` o tres casillas) | Se respeta esa lista; el índice no recorta |
| Genérico desconocido y Todas | `retail` + `tecnologia`; +`farmacias`/`supermercados` si parece médico |

La web no envía `stores` cuando todas las casillas están marcadas, así que «Todas» y «no filtrar» son el mismo caso.

## Búsqueda única y segundo plano

La unicidad no es el texto crudo: es el **id del genérico** que salió de `resolve`. `tele`, `televisor`, `tv`, `tv mini`, `mini led` y `mini tv` son la **misma** búsqueda (`tv`). `mini led` es alias de `tv` en la semilla.

Eso importa cuando el índice **sí recortó** tiendas (`applied: true`):

1. **Primer plano.** Se scrapean solo las tiendas de los grupos del genérico. El stream SSE termina con esos resultados; la UI no espera al resto.
2. **Segundo plano.** Al terminar esa pasada (también si salió del caché de 24 h) se lanzan las tiendas **que no estaban** en ese set — el resto del registro, sin tiendas deshabilitadas porque `list_stores()` ya es el universo. Un hilo daemon reusa `scrape_all` / `scrape_store`. Si falla, la búsqueda principal no se cae.

No hay fase 2 si marcaste tiendas a mano, si no hubo genérico (el fallback sin match no dispara el barrido extra) o si `applied` es falso. El candado Redis (o memoria si Redis no está) evita un segundo barrido del mismo `tv` el mismo día: buscar `tv` y un minuto después `televisor` no vuelve a pegarle a farmacias y ferreterías.

**Overlay y stragglers.** El overlay se suelta cuando el *wait-set* llega a ~80% de tiendas terminadas, o cuando hay al menos una oferta y el 50%+ ya respondió. Miniaturas, Qdrant y el persist en Mongo corren **después** de ese `done`. Los chips siguen actualizándose. **Movistar** está en el registro y se consulta (timeout 5 s, sin reintento de oleada), pero **no forma parte del wait-set**: overlay y `done` no la esperan; si llega tarde se fusiona como cualquier chip tardío; si se pasa de tiempo, queda `error`. Tampoco se relanza una tienda que ya hizo timeout en la misma búsqueda (los 403/429 cortos dentro del cliente de esa tienda sí pueden repetir).

**Retroalimentar.** Si una tienda de fuera devolvió coincidencias reales (después de `filter_relevant`), se agregan **solo los grupos de esas tiendas** a `product_index_seed.groups`, más `extra_groups` y `discovered_stores`. Mongo se actualiza al instante y se parcha `retail:pindex:product:{id}` para que la siguiente búsqueda del día ya incluya esos grupos, sin reconstruir todo Redis. Un miss extra solo se loguea; no se sacan grupos.

La interfaz, si hay barrido reservado, alarga el resumen: «Buscando TV en … (33 tiendas). Revisando más tiendas en segundo plano».

## Alias que nacen de la consulta

Si la consulta ya pegó un genérico, los tokens que sobran se indexan **en ese mismo documento**, no como productos nuevos.

Ejemplo real: el id en la semilla es `parlante` (nombre «Parlante», grupos `tecnologia`, `retail`, `musica`). «parlante jbl partibox» resuelve a `parlante` por el token largo `parlante`. Quedan `jbl` y `partibox`. Esos dos se `$addToSet` en `product_index_seed.aliases` y se escriben `retail:pindex:alias:jbl` / `alias:partibox` → `parlante`. Una búsqueda posterior de `jbl` o `partibox` enruta como parlante.

No se indexan:

- artículos, preposiciones y conjunciones (`de`, `por`, `para`, `según`, `y`, `el`, `la`, `con`, `sin`, …): la lista está en `ALIAS_STOPWORDS` de `retail/index/products.py`
- números sueltos (`50`) y unidades (`pulgadas`, `cm`, `ml`, `kg`, `w`, …): `ALIAS_UNITS`
- el token que ya identificó el genérico (`parlante`, `televisor`, `tv`)
- tokens de 1 carácter
- un token que **ya** es alias de **otro** genérico (`xbox` en «parlante xbox» se queda en `consola`; no se fusionan productos)

Si no hay genérico (`colun`), no se inventan alias. Si en una frase hay dos genéricos, ganan los tokens extra el que ganó `resolve` (el alias más largo / el primero).

## Recargar y consultar

```bash
retail indice                             # Mongo → Redis (force); inserta ids nuevos del JSON
retail indice letra t                     # tv, tablet, taladro…
retail indice resolver "tv 50 pulgadas"   # → tv
retail indice resolver "leche colun"      # → leche
retail indice sin-match                   # consultas que no pegaron un genérico
```

`retail pindex` es el mismo comando. `letra` lee `retail:pindex:letter:t` (o memoria si Redis no está). `resolver` usa `resolve()`; si no hay match imprime «Sin producto genérico».

Para agregar un genérico: edita `productos.json` (grupos que existan en `GROUP_TITLES`, alias que no choquen con otro `id`) y corre `retail indice`. Eso inserta el `id` nuevo en Mongo, **suma alias nuevos** a documentos que ya existían, y reescribe Redis. Cambiar nombre o grupos de un genérico **ya** presente en Mongo hay que hacerlo en la colección `product_index_seed`.

## Arranque, cada búsqueda y el cron diario

Al levantar la web, `_bootstrap_product_index` llama `ensure_loaded(sync_json=True)`: si Mongo está vacío, copia el JSON; si Redis no tiene `meta` o el `seed_hash` no coincide con Mongo, escribe el índice. Si Redis no responde, el índice queda en memoria a partir de esa semilla; las búsquedas siguen y el recorte de tiendas también.

Cada búsqueda, después de resolver tiendas, alimenta Mongo en segundo plano (`feed_search`): no bloquea al usuario y, si Mongo falla, la búsqueda sigue. Guarda la consulta, el genérico (o la falta de uno) y, si hubo match, los alias sobrantes. El barrido de tiendas fuera del índice arranca al terminar la pasada principal (`launch_other_store_sweep` desde `iter_search_events`).

Una vez al día el cron (`scripts/ofertas-diarias.sh <grupo>` / `ofertas-diarias-bmax.sh <grupo>`, hora base y stagger en `retail/batch/programacion.json`) corre `retail indice` y el batch llama `refresh_product_index()` al arrancar: **Mongo → Redis**. También sincroniza `store_categories` (grupos de tiendas) desde el registry sin pisar títulos ni `store_ids` enriquecidos. `retail indice` a mano hace lo mismo.

### Categorías de tiendas en Mongo

Colección **`store_categories`**: `id`, `title`, `store_ids`, `sort_order`, `updated_at`. Arranca desde `GROUP_TITLES` / `STORE_GROUP` en `retail/registry.py`. El batch `retail batch --grupo tecnologia` lee las tiendas de ahí (fallback registry) y filtra el catálogo con los `groups` de **`product_index_seed`**.

La colección **`categories`** sigue siendo el árbol de categorías de una tienda (p. ej. Falabella); no confundir con los grupos de tiendas.

`retail indice` sin Redis avisa y deja el índice solo en memoria hasta que Redis esté arriba.

## No es el caché de 24 horas

Redis guarda **dos** cosas:

| | Índice `retail:pindex:` | Caché `search:…` |
|---|---|---|
| Qué es | Mapa genérico → grupos → tiendas | Resultado ya scrapeado de una consulta |
| Dónde nace | Semilla Mongo `product_index_seed` (JSON de arranque) | Cada scrape |
| Cuánto vive | Hasta el cron diario, un `retail indice`, o un cambio de hash | 24 h (`RETAIL_SEARCH_CACHE_TTL`) |
| Para qué | Decidir **adónde** ir | No volver a pegarle a las cadenas |
| Si Redis cae | Se resuelve contra la semilla en memoria | Cada búsqueda va de nuevo a las tiendas |

El índice corre **antes** de scrapear y de mirar el caché: primero se elige el set de tiendas, después se busca un resultado de 24 h para esa consulta y esas tiendas. «Forzar tiendas» (fresh) ignora el caché; no desactiva el índice.

## Otros genéricos (misma mecánica)

| Consulta | Genérico | Grupos | Tiendas (de 150) | Entran | No entran |
|---|---|---|---|---|---|
| `tv 50 pulgadas` | `tv` | tecnologia, retail, hogar, supermercados | 33 | `pcfactory`, `falabella`, `ikea`, `lider` | `ahumada`, `sodimac` |
| `leche colun` | `leche` | supermercados | 5 | `lider`, `tottus`, `unimarc`, `alvi`, `cugat` | `falabella`, `pcfactory` |
| `taladro` | `taladro` | ferreteria, retail | 16 | `sodimac`, `easy`, `falabella`, `ripley` | `lider`, `ahumada` |
| `ozempic` | `ozempic` | farmacias, supermercados, retail | 15 | `ahumada`, `cruzverde`, `salcobrand`, `drsimi`, `falabella` | `pcfactory`, `sodimac`, `nike` |
| `paracetamol` | `paracetamol` | farmacias, supermercados | 10 | `ahumada`, `cruzverde`, `lider` | `pcfactory`, `nike` |
| `amoxicilina` / `jarabe` | `medicamento` | farmacias, supermercados, retail | 15 | `ahumada`, `salcobrand`, `falabella` | `pcfactory`, `sodimac` |
| `notebook` | `notebook` | tecnologia, retail | 11 | `pcfactory`, `falabella` | `ahumada` |
| `xyzzy` (sin match) | — | retail, tecnologia | ~11 | `falabella`, `pcfactory` | `ahumada`, `nike` |

`leche` no incluye `retail`: Falabella no se consulta aunque venda lácteos. `taladro` sí mezcla ferretería y retail, y deja fuera supermercados y farmacias.

**Cuándo entran farmacias**

1. El genérico resuelto declara `farmacias` (`medicamento`, `ozempic`, `paracetamol`, `ibuprofeno`, `vitaminas`, `shampoo`, …).
2. No hay genérico, pero `looks_pharmacy` es verdadero → fallback `retail`+`tecnologia`+`farmacias`+`supermercados`.
3. En cualquier otro caso (tv, notebook, palabra random) **no** se añaden farmacias al set inicial.

El match sigue siendo el alias **más largo** primero: `ozempic` gana sobre formas genéricas; un alias aprendido después (leftover) en `medicamento` no pisa un producto más específico si ese alias ya pertenece a otro `id`.
