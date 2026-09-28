# Inteligencia comercial del scraping

La implementación sigue el orden de los cinco pilares y conserva el análisis
anterior como respaldo. Los datos ausentes se muestran como desconocidos: no se
inventan precios, stock ni despacho.

## 1. Identidad del producto

- La huella de comparación prioriza EAN/GTIN y códigos del fabricante. Cuando
  esos datos faltan combina marca, modelo, capacidad, RAM, tamaño, contenido y
  texto normalizado, incluso si las tiendas ordenan las palabras de otra forma.
- Dos capacidades o cantidades de RAM diferentes no comparten historial.
- Tampoco se mezclan packs, regalos o bundles, condición ni tamaños distintos.
- Qdrant indexa nombre, especificaciones y condición para recuperar candidatos.
- La similitud sirve para proponer candidatos; los atributos estrictos deciden
  si realmente se pueden comparar.
- Cada unión guarda el método y un nivel de confianza. Las comparaciones y
  alertas entre tiendas exigen una confianza mínima de 80%.
- El administrador puede unir productos equivalentes, separarlos cuando sean
  variantes diferentes o restablecer la decisión automática desde la página de
  análisis. La corrección queda guardada en la base de datos.

La evaluación de una oferta conserva tres conceptos separados:

- **Descuento publicado:** compara el precio normal informado por la tienda con
  su precio actual.
- **Baja verificada:** compara el precio actual con observaciones anteriores del
  mismo producto y no depende del porcentaje anunciado por la tienda.
- **Mejor precio del mercado:** compara el costo actual entre las tiendas que
  venden la misma entidad. Cuando el despacho es comparable usa el total con
  envío.

Por eso una tienda puede mostrar el mayor porcentaje de descuento y, al mismo
tiempo, no tener el precio más bajo. La interfaz muestra ambas conclusiones y un
puntaje que también considera identidad, stock e historial.

## 2. Condición

- Se normalizan `new`, `refurbished`, `open_box`, `display`, `used` y `unknown`.
- Se reconocen expresiones como reacondicionado, grado A/B, caja abierta,
  devolución de cliente, exhibición y detalles estéticos.
- Un producto con uso explícito nunca comparte comparación ni mínimo histórico
  con uno nuevo. `unknown` se mantiene compatible con nuevo hasta contar con un
  dato explícito, para no vaciar el catálogo histórico existente.

## 3. Despacho y costo total

- Se guardan costo visible, umbral de despacho gratis, región y retiro en tienda.
- El costo comparable es `precio para todo medio + despacho`.
- El costo total solo ordena ofertas si todas las tiendas comparadas informan el
  despacho. Si falta un valor se mantiene la comparación por producto y se
  advierte que el despacho no está incluido.

## 4. Pago

- El precio para todo medio es el precio principal del historial y las alertas.
- El precio con tarjeta, la tarjeta requerida, cuotas, total financiado, CAE y
  condiciones se guardan como datos separados.
- El perfil permite indicar tarjetas disponibles. Una alerta que dependa de una
  tarjeta no declarada por el usuario se descarta.
- El historial nuevo usa la base `all_payment`; cuando existen puntos limpios no
  se mezclan con puntos antiguos de base desconocida.

## 5. Stock y variantes

- Se guardan variantes, cantidades, señales de poco stock y tallas extremas.
- Las ofertas agotadas no generan alertas.
- Una oferta limitada a tallas extremas solo se avisa cuando coincide con las
  tallas preferidas del usuario.
- En el análisis administrativo se puede validar una cantidad desconocida
  mediante la simulación de checkout de tiendas VTEX autorizadas. La prueba no
  crea carrito ni orden y está limitada en tiendas, productos y cantidad.

## Extracción asistida opcional

Los parsers y APIs de las tiendas siempre tienen prioridad. Ollama puede completar
campos vacíos desde el texto ya obtenido, usando JSON estructurado y temperatura
cero. Se activa explícitamente:

```env
COMMERCIAL_LLM_ENABLED=1
COMMERCIAL_LLM_MODEL=llama3.2:3b
COMMERCIAL_LLM_MAX_PER_BATCH=10
```

Si Ollama no está disponible, el scraping continúa sin interrumpirse.

La validación administrativa de stock se controla por lista permitida:

```env
STOCK_VALIDATION_STORES=easy
STOCK_VALIDATION_MAX=50
```

No conviene habilitar masivamente la simulación: aumenta las consultas y puede
provocar bloqueos. Debe ampliarse tienda por tienda después de verificar su API.

## Puesta en marcha recomendada

1. Desplegar los campos y mantener Ollama desactivado.
2. Simular la preparación existente con
   `python3 scripts/backfill_commercial_fields.py` y, tras revisar el total,
   guardar con `python3 scripts/backfill_commercial_fields.py --apply`.
3. Ejecutar scraping normal para formar historial con precio para todo medio.
4. Revisar muestras de condición, variantes y despacho por tienda.
5. Activar Ollama en lotes pequeños si los parsers dejan campos relevantes vacíos.
6. Ampliar la lista de validación de stock solo para APIs confirmadas.
