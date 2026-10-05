# Ofertas reales

Página `/reales` (API `/api/reales`). Lista avisos cuyo descuento se sostiene al **comparar tiendas** o al **historial**, no solo el “antes” de vitrina.

Requiere sesión. Código: `retail/reales.py`, listado en `retail/mongo.py` (`real_offers`), UI en `retail/web/static/reales.html` + `reales.js`.

## Por qué a veces no hay productos

1. **Ningún tipo de oferta activo.** Si «Ofertas en comparación», «Bajó de precio» y «Mismo precio» están todos desmarcados, la UI muestra *«Activa al menos un tipo de oferta.»* y el backend responde lista vacía a propósito. Con cero tipos no se calcula nada.
2. **Filtros demasiado estrechos** (categoría, tienda, % vs otra tienda, solo super ofertas).
3. **Datos insuficientes** en Mongo: el producto no aparece en ≥2 tiendas con la **misma identidad de nombre**, falta historial, confianza de identidad baja, o está agotado.

Por defecto en HTML vienen marcados comparación e historial. Si la captura muestra los cuatro checks apagados, eso explica el vacío inmediato.

## Qué debe cumplir un producto para aparecer

### Datos previos (Mongo)

- Precio de venta (`price` > 0) y nombre no vacío.
- **Al menos dos tiendas** distintas con el **mismo producto por nombre/identidad** (ver regla de matching abajo).
- Misma **identidad** de producto (envase/pack, condición, etc.): no se compara 1 unidad vs pack de 6.
- **Confianza de identidad ≥ 80%** entre pares (`identity_match_confidence` / huella de nombre). No basta con compartir un SKU o `compare_code` de tienda.
- No marcado como **agotado** / sin stock (nombre, estado o stock ≤ 0).
- Descuento propio o verificado de **al menos 10%** (ver abajo). Rebajas menores no entran.

El pipeline usa hasta los **últimos 40** puntos de `price_history` por producto.

### Matching entre tiendas (regla)

Los códigos de producto (`product_id`, SKU, `compare_code` guardado) **dependen de cada tienda** y **no** se usan solos para armar pares.

Para ofertas reales el agregador:

1. Carga avisos con precio y nombre.
2. Los agrupa con `cluster_offer_rows` / identidad de `retail/compare.py` (marca, modelo, capacidad, envase, texto normalizado; EAN solo si es GTIN real, no SKU interno).
3. Dentro del grupo, `pick_real_offer` vuelve a exigir `same_product_identity` (≥ 0.84) y `group_entity_confidence` ≥ 0.80.

Así dos fichas del mismo shampoo con SKUs distintos sí se comparan; dos nombres genéricos o productos distintos no.

El **historial** de la misma tienda no cambia: sigue usando `price_history` del propio aviso (no necesita códigos cruzados).

### Tipos de oferta (checks)

Hay que activar al menos uno. Un aviso puede llevar varios `kinds` a la vez.

| Tipo | Check UI | Criterio resumido |
|------|----------|-------------------|
| **Comparación** | Ofertas en comparación | Otra tienda cobra cerca del *precio normal* de esta (≥ 90% del listado) **y** al menos **10% más cara** que el precio de venta de la oferta. Hay brecha real entre tiendas. |
| **Historial** | Bajó de precio | Hubo un día anterior a **precio lleno** (≥ 95% del normal) distinto del precio actual, **o** baja verificada ≥ 10% vs mediana de precios previos observados (hace falta ≥ 2 precios distintos en el historial). Sigue haciendo falta otra tienda en el grupo. |
| **Mismo precio** | Mismo precio | Solo si **no** calificó como comparación ni historial: todas las otras tiendas del grupo están a ±**3%** del mismo precio de venta (p. ej. Easy/Paris al mismo aviso). El % off es de vitrina, no brecha entre tiendas. |
| **Super ofertas** | Descuento > 50% | Filtro extra: debe ser comparación o historial **y** `gap_percent` > 50 **o** descuento (publicado o verificado) > 50. «Mismo precio» **no** cuenta como super aunque el cartel diga 50%+. |

Constantes en `retail/reales.py`: `MIN_OWN_DISCOUNT=10`, `PEER_AT_LIST=0.90`, `MIN_SELLING_GAP=0.10`, `SAME_PRICE_RATIO=0.03`, `FULL_PRICE_RATIO=0.95`, `MIN_SUPER_PERCENT=50`, `MIN_ENTITY_CONFIDENCE=0.80`.

### Descuento comercial vs ahorro real

- **Comercial (publicado):** `(price_normal − price) / price_normal`. Es el cartel de la tienda.
- **Ahorro real:** baja respecto a la mediana de precios **realmente vistos** y/o vs mediana/mínimo de otras tiendas con identidad ≥ 80%. No depende del “antes” inflado.

Para entrar hace falta comercial ≥ 10% **o** verificado ≥ 10%, y además superar los filtros anti-vitrina de abajo.

### Señales anti-vitrina (criterio `real-offer-v2`)

1. **Inflación de lista:** si `price_normal` subió ≥ 15% en 7–30 días y el precio de venta vuelve cerca (±5%) del precio previo, **no** es oferta real. Ejemplo: normal 10.000 → 14.000, “−29%” a 10.000 → ahorro real ≈ 0.
2. **Ancla cross-store:** si el precio en oferta está a ≤ 3% de la mediana o del mínimo de otras tiendas (confianza ≥ 80%), no califica como gran oferta; el motivo habla de “similar a otras tiendas”.
3. **Pre-evento / Cyber CL:** ventanas heurísticas Mayo–Jun, fin Sep–Oct y fin Nov. Si el precio (lista o venta) subió ≥ 10% en ~14 días previos y el “descuento” no deja un ahorro real ≥ 10%, se descarta. Constantes: `CHILE_EVENT_WINDOWS` en `retail/reales.py`.

El worker diario (`retail/real_offer_worker.py`, versión `real-offer-v2`) persiste estas marcas en `daily_real_offers.analysis`. `/reales` **lee** las marcas; no recalcula en el request.

### Qué no filtra esta página

- **No** usa `ignore_fake_discounts` / `fake_discount()` de las alertas del batch (esa lógica mira alzas del *precio de venta*). Aquí la inflación de *lista* y el ancla cross-store son propias de ofertas reales.
- Easy/Paris (o Falabella/Sodimac) al **mismo** precio se colapsan en un aviso; solos no generan comparación (hace falta un rival de otra familia más caro, o el check «Mismo precio»).

### Envío

Si **todas** las tiendas del grupo informan despacho comparable, se compara precio + envío (`landed_price`). Si falta algún dato, se compara solo el precio del producto.

## Filtros de la UI

| Control | Parámetro API | Efecto |
|---------|---------------|--------|
| Ofertas en comparación | `comparacion` | Incluye tipo comparación (default `true`). |
| Bajó de precio | `historial` | Incluye tipo historial (default `true`). |
| Mismo precio | `iguales` | Incluye tipo iguales (default `false`). |
| Super ofertas > 50% | `super` | Deja solo `is_super_offer` (default `false`). |
| Categoría / tienda | `category`, `store` | Filtra la oferta ganadora del grupo. |
| % vs otra tienda | `min_gap` | Exige `gap_percent` ≥ umbral. |
| Mostrar | `size` | Página de 24 / 40 / 80. |
| Buscar | `q` | Texto en nombre, marca, tienda, código, categoría. |

Orden de resultados: mayor `gap_percent`, luego mayor ahorro en pesos.

`/super` redirige a `/reales?super=1`. La API `/api/super` fuerza comparación+historial y umbral 50%.

## Mensaje TimesFM (secundario, solo admin)

Texto tipo *«TimesFM aún no se muestra en ofertas: Faltan series evaluadas (0/30)»*:

- Visible solo para usuarios con rol **admin** (`data-admin` + chequeo en `reales.js` / `super.js`).
- Es una **señal experimental** opcional sobre ofertas ya clasificadas.
- **No** decide qué entra o sale de la lista ni el orden.
- Se habilita cuando la validación TimesFM registra ≥ **30** series, mejora ≥ 5% vs baseline y acierto de dirección ≥ 55% (ver `docs/TIMESFM_DATOS.md` y `retail/predictive_alerts.py`).
- Con `0/30` la página sigue con el análisis tradicional; el aviso es informativo.

## Checklist operativo si “no hay ofertas”

1. ¿Hay al menos un tipo de oferta marcado?
2. ¿Hay el mismo producto (por nombre/identidad) en ≥2 tiendas con confianza ≥ 80%?
3. ¿Existe historial con precios anteriores (para “Bajó de precio”) o un rival a precio lleno (para comparación)?
4. ¿El descuento publicado o verificado llega al 10%?
5. ¿Filtros de tienda / categoría / min_gap / super están vaciando el resultado?

Relacionado: `docs/inteligencia_comercial.md` (identidad, despacho, stock), `docs/TIMESFM_DATOS.md` (señal TimesFM).
