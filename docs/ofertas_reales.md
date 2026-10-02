# Ofertas reales

Página `/reales` (API `/api/reales`). Lista avisos cuyo descuento se sostiene al **comparar tiendas** o al **historial**, no solo el “antes” de vitrina.

Requiere sesión. Código: `retail/reales.py`, listado en `retail/mongo.py` (`real_offers`), UI en `retail/web/static/reales.html` + `reales.js`.

## Cómo se emparejan productos entre tiendas

Cada tienda tiene su propio `product_id` / SKU. **No** se comparan por ese código de tienda.

La comparación cruzada usa el **nombre del producto** (normalizado / identidad de nombre en el agregador). Dos avisos pueden ser el mismo producto aunque sus IDs sean distintos, siempre que el nombre (y envase/condición) coincidan con confianza suficiente.

Ejemplo de emparejamiento válido:

| Tienda | product_id | Nombre |
|--------|------------|--------|
| Falabella | `8814523` | Shampoo Pantene Restauración 400 ml |
| Ripley | `MPM000123456` | Shampoo Pantene Restauración 400 ml |

Mismo producto para ofertas reales, pese a IDs distintos.

No califica si solo se parece el nombre pero el envase difiere (1 unidad vs pack de 6), o si la confianza de identidad queda bajo el umbral (p. ej. match solo por nombre genérico débil).

## Por qué a veces no hay productos

1. **Ningún tipo de oferta activo.** Si «Ofertas en comparación», «Bajó de precio» y «Mismo precio» están todos desmarcados, la UI muestra *«Activa al menos un tipo de oferta.»* y el backend responde lista vacía a propósito. Con cero tipos no se calcula nada.
2. **Filtros demasiado estrechos** (categoría, tienda, % vs otra tienda, solo super ofertas).
3. **Datos insuficientes** en Mongo: el producto no aparece en ≥2 tiendas con el mismo nombre/identidad, falta historial, confianza baja, o está agotado.

Por defecto en HTML vienen marcados comparación e historial. Si la captura muestra los cuatro checks apagados, eso explica el vacío inmediato.

**Ejemplo — lista vacía a propósito:** entras a `/reales`, desmarcas «Ofertas en comparación», «Bajó de precio» y «Mismo precio». Aunque Mongo tenga el shampoo de Falabella a $6.000 y Ripley a $10.000, la API no evalúa nada y la página pide activar al menos un tipo.

**Ejemplo — filtros estrechos:** hay 12 ofertas reales, pero eliges tienda = Lider y `min_gap` = 40. Si la única oferta de Lider tiene 22% vs otra tienda, el listado queda vacío aunque el resto del catálogo sí califique.

## Qué debe cumplir un producto para aparecer

### Datos previos (Mongo)

- Precio de venta (`price` > 0).
- **Al menos dos tiendas** distintas con el **mismo producto por nombre/identidad** (no por `product_id` de cada tienda).
- Misma **identidad** de producto (envase/pack, condición, etc.): no se compara 1 unidad vs pack de 6.
- **Confianza de identidad ≥ 80%** (`entity_confidence`). Match débil solo por nombre genérico no entra.
- No marcado como **agotado** / sin stock (nombre, estado o stock ≤ 0).
- Descuento propio o verificado de **al menos 10%** (ver abajo). Rebajas menores no entran.

El pipeline usa hasta los **últimos 40** puntos de `price_history` por producto.

**Ejemplo — envase distinto (no entra):**

| Tienda | product_id | Nombre | Precio |
|--------|------------|--------|--------|
| Lider | `L-100` | Ozempic 1 unidad | $80.000 (lista $120.000) |
| Paris | `P-200` | Ozempic 6 unidades | $400.000 |

Misma marca, distinto envase → no hay oferta por comparación.

**Ejemplo — agotado (no entra):** Falabella publica «Agotado Shampoo Pantene 400 ml» a $6.000 y Ripley el mismo nombre a $10.000. El aviso barato está agotado → no aparece.

### Tipos de oferta (checks)

Hay que activar al menos uno. Un aviso puede llevar varios `kinds` a la vez.

| Tipo | Check UI | Criterio resumido |
|------|----------|-------------------|
| **Comparación** | Ofertas en comparación | Otra tienda cobra cerca del *precio normal* de esta (≥ 90% del listado) **y** al menos **10% más cara** que el precio de venta de la oferta. Hay brecha real entre tiendas. |
| **Historial** | Bajó de precio | Hubo un día anterior a **precio lleno** (≥ 95% del normal) distinto del precio actual, **o** baja verificada ≥ 10% vs mediana de precios previos observados (hace falta ≥ 2 precios distintos en el historial). Sigue haciendo falta otra tienda con el mismo producto. |
| **Mismo precio** | Mismo precio | Solo si **no** calificó como comparación ni historial: todas las otras tiendas del grupo están a ±**3%** del mismo precio de venta (p. ej. Easy/Paris al mismo aviso). El % off es de vitrina, no brecha entre tiendas. |
| **Super ofertas** | Descuento > 50% | Filtro extra: debe ser comparación o historial **y** `gap_percent` > 50 **o** descuento (publicado o verificado) > 50. «Mismo precio» **no** cuenta como super aunque el cartel diga 50%+. |

Constantes en `retail/reales.py`: `MIN_OWN_DISCOUNT=10`, `PEER_AT_LIST=0.90`, `MIN_SELLING_GAP=0.10`, `SAME_PRICE_RATIO=0.03`, `FULL_PRICE_RATIO=0.95`, `MIN_SUPER_PERCENT=50`, `MIN_ENTITY_CONFIDENCE=0.80`.

#### Ejemplo — comparación entre tiendas

Producto: **Shampoo Pantene Restauración 400 ml**

| Tienda | product_id | Precio venta | Precio normal |
|--------|------------|--------------|---------------|
| Falabella | `8814523` | $6.000 | $10.000 |
| Ripley | `MPM000123456` | $10.000 | $10.000 |

Con «Ofertas en comparación» activo: entra como **comparación**. Falabella tiene 40% off y Ripley cobra el precio lleno (≥ 90% del normal y ≥ 10% más caro). `gap_percent` ≈ 40. No es super oferta (umbral 50%).

Si Ripley también estuviera a $6.100 (casi el mismo precio barato), **no** hay brecha real → no califica como comparación.

#### Ejemplo — bajó de precio (historial)

Producto: **Notebook Lenovo IdeaPad 3 15" Ryzen 5**

| Tienda | product_id | Hoy | Historial |
|--------|------------|-----|-----------|
| Falabella | `F-NB-771` | $479.990 | 1 ago: $799.990 (cerca del normal); hoy: $479.990 |
| Ripley | `R-NB-882` | $749.990 | — |

Con «Bajó de precio» activo: entra como **historial** (hubo un día a precio lleno). Sigue haciendo falta Ripley (u otra tienda) con el mismo nombre para armar el grupo.

Si el historial solo tiene $479.990 → $479.990 (nunca hubo precio lleno distinto y no hay baja verificada ≥ 10%), **no** califica solo por historial.

**Variante — baja verificada sin “antes” de vitrina:** la tienda no publica `price_normal`, pero el historial muestra $12.000 → $11.800 → $8.000. La mediana previa es ~$11.900 y hoy $8.000 → descuento verificado ≈ 33% → puede entrar como historial.

#### Ejemplo — mismo precio (vitrina compartida)

Producto: **Taladro Bosch GSB 13 RE**

| Tienda | product_id | Precio venta | Precio normal |
|--------|------------|--------------|---------------|
| Easy | `E-99101` | $399.990 | $819.990 |
| Paris | `P-44022` | $399.990 | $829.990 |

Easy y Paris son familia Cencosud: mismo precio de venta (±3%). Con solo «Ofertas en comparación» **no** entra (no hay rival más caro). Con «Mismo precio» activo: entra como **iguales**. El ~51% off es cartel de vitrina, no brecha entre tiendas. **No** es super oferta aunque el % publicado > 50.

Si además Ripley vende el mismo taladro a $829.990 (precio lleno), sí entra como **comparación** (rival fuera de la familia) y puede ser super si la brecha > 50%.

#### Ejemplo — super ofertas > 50%

Producto: **Smart TV Samsung 55" UHD**

| Tienda | product_id | Precio | Normal / rival |
|--------|------------|--------|----------------|
| Easy | `E-TV-55` | $399.990 | — |
| Paris | `P-TV-55` | $399.990 | — |
| Ripley | `R-TV-55` | $829.990 | precio lleno |

Brecha vs Ripley ≈ 52% → comparación **y** super oferta.

Otro caso: Falabella baja de $10.000 a $4.500 (55% publicado) con historial a precio lleno y Ripley a $7.000. Entra por historial; el descuento > 50% → super aunque el `gap_percent` vs Ripley sea < 50.

### Descuento publicado vs verificado

- **Publicado:** `(price_normal − price) / price_normal`.
- **Verificado:** baja respecto a la mediana de precios **realmente vistos** (excluye el precio actual; mediana de hasta los últimos 30 puntos previos). No depende del “antes” de la tienda.

Para entrar hace falta publicado ≥ 10% **o** verificado ≥ 10%.

**Ejemplo:** Paris vende un perfume a $8.000 con normal $9.000 (publicado 11%). Ripley el mismo nombre a $12.000. Entra (publicado ≥ 10% + comparación). Si el publicado fuera 5% y no hubiera historial con baja real, **no** entra.

### Qué no filtra esta página

- **No** usa `ignore_fake_discounts` / `fake_discount()` de las alertas del batch. El criterio aquí es comparación entre tiendas + historial propio.
- Easy/Paris (o Falabella/Sodimac) al **mismo** precio se colapsan en un aviso; solos no generan comparación (hace falta un rival de otra familia más caro, o el check «Mismo precio»).

### Envío

Si **todas** las tiendas del grupo informan despacho comparable, se compara precio + envío (`landed_price`). Si falta algún dato, se compara solo el precio del producto.

**Ejemplo:** mismo aire acondicionado en Lider ($299.990 + envío $9.990) y Falabella ($309.990 + envío $0). Si ambos publican envío comparable, la brecha usa precio landed; si una no informa envío, se usa solo el precio del producto.

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

**Ejemplo — filtro tienda:** el shampoo gana en Falabella ($6.000). Con `store=falabella` se ve; con `store=ripley` no, porque el ganador del grupo no es Ripley.

**Ejemplo — min_gap:** el shampoo tiene `gap_percent` 40. Con `min_gap=30` sigue; con `min_gap=45` desaparece.

**Ejemplo — buscar:** `q=pantene` encuentra el shampoo; `q=ozempic` no, aunque haya otras ofertas en la página.

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
