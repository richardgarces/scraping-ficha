# Retail Chile

Un paquete (`retail`) con **fuentes registradas**. El HTTP, el modelo y el CLI son compartidos.

Para qué sirve la aplicación y cómo configurarla: **[docs/GUIA.md](docs/GUIA.md)**.

La arquitectura de identidad, condición, despacho, pagos y stock está descrita
en **[docs/inteligencia_comercial.md](docs/inteligencia_comercial.md)**.

El piloto de **[cotizaciones comparadas](docs/COTIZACIONES.md)** conecta listas
CSV y documentos de scraping/Docling con el catálogo, revisión de equivalencias
y comparación de costos. Disponible en `/cotizaciones` solo para administradores.

- `retail/sources/`: una tienda por módulo (se descubren solas)
- `retail/platforms/`: motores VTEX, Shopify y Magento
- `retail/scaffold/templates/`: plantillas de `retail nueva`

## Tiendas

| Comando | Sitio |
|---|---|
| `falabella` | www.falabella.cl |
| `ripley` | simple.ripley.cl |
| `paris` | www.paris.cl |
| `sodimac` | www.sodimac.cl |
| `easy` | www.easy.cl |
| `construplaza` | www.construplaza.cl |
| `prat` | www.ferreteriaprat.cl |
| `weitzler` | www.weitzler.cl |
| `audiomusica` | www.audiomusica.com |
| `casaroyal` | www.casaroyal.cl |
| `promusic` | www.promusic.cl |
| `dbs` | www.dbs.cl |
| `sallybeauty` | www.sallybeauty.cl |
| `bodyshop` | www.thebodyshop.cl |
| `lider` | www.lider.cl |
| `unimarc` | www.unimarc.cl |
| `alvi` | www.alvi.cl |
| `cugat` | www.cugat.cl |
| `mercadolibre` | www.mercadolibre.cl |
| `ikea` | www.ikea.com/cl |
| `nike` | www.nike.cl |
| `fashionspark` | www.fashionspark.com |
| `doite` | www.doite.cl |
| `lippi` | www.lippioutdoor.com |
| `drsimi` | www.drsimi.cl |
| `colloky` | www.colloky.cl |
| `intime` | www.intime.cl |
| `amphora` | www.amphora.cl |
| `pcfactory` | www.pcfactory.cl |
| `tottus` | www.tottus.cl |
| `weplay` | www.weplay.cl |
| `antartica` | www.antartica.cl |
| `rosen` | www.rosen.cl |
| `sparta` | www.sparta.cl |
| `cannon` | www.cannonhome.cl |
| `tiendaflores` | tiendaflores.cl |
| `eliteperfumes` | www.eliteperfumes.cl |
| `loccitane` | cl.loccitane.com |
| `lush` | www.lush.cl |
| `pichara` | www.pichara.cl |
| `silkperfumes` | www.silkperfumes.cl |
| `preunic` | preunic.cl |
| `azaleia` | www.azaleia.cl |
| `cardinale` | www.cardinale.cl |
| `converse` | www.converse.cl |
| `crocs` | www.crocs.cl |
| `hushpuppies` | www.hushpuppies.cl |
| `vans` | www.vans.cl |
| `allnutrition` | www.allnutrition.cl |
| `andesgear` | www.andesgear.cl |
| `asics` | www.asics.cl |
| `bikehouse` | bikehouse.cl |
| `hakahonu` | www.hakahonu.cl |
| `head` | www.head.cl |
| `mammut` | www.mammut.cl |
| `merrell` | www.merrell.cl |
| `newbalance` | www.newbalance.cl |
| `nutrapharm` | www.nutrapharm.cl |
| `oxford` | www.oxfordstore.cl |
| `patagonia` | www.patagonia.cl |
| `puma` | cl.puma.com |
| `reebok` | www.reebok.cl |
| `salomon` | www.salomon.cl |
| `sportika` | www.sportika.cl |
| `supletech` | www.supletech.cl |
| `thenorthface` | www.thenorthface.cl |
| `underarmour` | www.underarmour.cl |
| `dellanatura` | www.dellanatura.cl |
| `atika` | www.atika.cl |
| `budnik` | www.budnik.cl |
| `mk` | www.mk.cl |
| `stretto` | www.stretto.cl |
| `adagio` | www.adagio.cl |
| `cafehaiti` | www.cafehaiti.cl |
| `lavinoteca` | www.lavinoteca.cl |
| `marleycoffee` | www.marleycoffee.cl |
| `mundovino` | www.elmundodelvino.cl |
| `wineclub` | www.santiagowineclub.cl |
| `varsovienne` | www.varsovienne.cl |
| `byp` | www.byp.cl |
| `flex` | www.flex.cl |
| `interdesign` | www.interdesign.cl |
| `kitchencenter` | www.kitchencenter.cl |
| `mashini` | www.mashini.cl |
| `medular` | www.medular.cl |
| `oster` | www.oster.cl |
| `simplepuro` | www.simplebypuro.cl |
| `thomas` | www.thomas.cl |
| `tramontina` | www.tramontina.cl |
| `bebesit` | www.bebesit.cl |
| `ficcus` | www.ficcus.cl |
| `limonada` | www.limonada.cl |
| `opaline` | www.opaline.cl |
| `artenostro` | www.artenostro.cl |
| `contrapunto` | www.contrapunto.cl |
| `ferialibro` | www.feriachilenadellibro.cl |
| `torre` | www.torre.cl |
| `bananarepublic` | www.bananarepublic.cl |
| `calvinklein` | www.calvinklein.cl |
| `dockers` | www.dockers.cl |
| `ellus` | www.ellus.cl |
| `kipling` | www.kipling.cl |
| `levis` | www.levi.cl |
| `lounge` | www.lounge.cl |
| `trial` | www.trial.cl |
| `econopticas` | www.econopticas.cl |
| `gmo` | www.gmo.cl |
| `opv` | www.opv.cl |
| `schilling` | www.schilling.cl |
| `mosso` | www.mosso.cl |
| `swarovski` | www.swarovski.cl |
| `belkin` | www.belkin.cl |
| `centrale` | www.centrale.cl |
| `migo` | www.migo.cl |
| `motorola` | www.motorola.cl |
| `movistar` | catalogo.movistar.cl |
| `entel` | miportal.entel.cl |
| `dcshoes` | www.dcshoes.cl |
| `totaltools` | www.totaltools.cl |
| `descorcha` | www.descorcha.com |
| `piwen` | www.piwen.cl |
| `tika` | tika.cl |
| `betterlife` | www.betterlife.cl |
| `janome` | www.janome.cl |
| `mundotransfer` | www.mundotransfer.cl |
| `maui` | www.mauiandsons.cl |
| `ripcurl` | www.ripcurl.cl |
| `volcom` | www.volcom.cl |
| `speedo` | www.speedo.cl |
| `liquimoly` | www.liqui-moly.cl |
| `needle` | www.needle.cl |
| `ansaldo` | www.ansaldo.cl |
| `toyng` | www.toyng.cl |
| `piedrabruja` | www.piedrabruja.cl |
| `catalonia` | www.catalonia.cl |
| `nacional` | nacional.cl |
| `etienne` | www.etienne.cl |
| `petrizzio` | www.petrizzio.cl |
| `gap` | www.gap.cl |
| `ferouch` | www.ferouch.cl |
| `perryellis` | www.perryellis.cl |
| `tommy` | cl.tommy.com |
| `hugoboss` | www.hugoboss.cl |
| `guess` | www.guess.cl |
| `fdv` | www.fdv.cl |
| `amesti` | www.amesti.cl |
| `dartel` | www.dartel.cl |

```bash
retail tiendas
```

## Instalación

```bash
cd scraping
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Comparador web

Busca el mismo producto en todas las tiendas, deja solo resultados que correspondan a la consulta, los muestra en una tabla y marca la empresa con el menor precio cuando el código coincide. Cada búsqueda se guarda en MongoDB y se indexa en Qdrant para afinar búsquedas siguientes.

```bash
docker compose up -d
# Mongo: mongodb://localhost:27017  base scraping
# Qdrant: http://127.0.0.1:6333
# Redis: redis://127.0.0.1:6379/0
retail web --host 127.0.0.1 --port 8080
```

Abre `http://127.0.0.1:8080`. Los resultados se filtran por nombre, marca o código, rango de precio y descuento mínimo. La opción “Productos con descuentos” muestra productos con precio válido y descuento positivo, excluyendo descuentos marcados como falsos. Se pueden ordenar por precio, descuento o cuánto están bajo lo habitual, y limitar a “mismo código”, “menor precio” u “ofertas reales”. Cada fila muestra el precio con tarjeta, el de internet y el anterior, el descuento, la evaluación contra el historial y la nota de si es su mínimo histórico.

Los precios se muestran como los publica la tienda: el precio efectivo arriba, y debajo la escalera con el precio internet y el normal tachado. Cuando el más bajo solo se consigue con la tarjeta de la cadena queda rotulado (`con tarjeta CMR`, `Cencosud`, `Ripley`…), para no comparar un precio con tarjeta contra uno sin ella. El porcentaje es el que anuncia la tienda; `sane_discount` en `retail/models.py` lo descarta cuando es imposible, porque Lider mandaba el ahorro en pesos en ese campo y aparecían descuentos de -10819%.

Páginas públicas: `/` busca, `/catalogo` navega lo ya guardado, `/hoy` ofertas del día, `/producto` ficha con historial, `/siguiendo` watches y push. Con login: `/reales` (super vía `?super=1`), `/comparar`. Solo admin: `/ofertas`, `/cron`, `/cyber-day`, `/cambios-precio`, `/estadisticas`, `/pronosticos`, `/usuarios`, `/tiendas`, `/cotizaciones`, `/analisis-producto`. Smoke post-deploy: [`docs/SMOKE_PROD.md`](docs/SMOKE_PROD.md).

### Qué queda fuera de los resultados

Buscar “tv 50 pulgadas” traía racks, soportes y muebles, porque comparten todas las palabras de la consulta. `retail/intent.py` decide si el producto **es** lo pedido o solo lo menciona: descarta accesorios (`rack`, `soporte`, `funda`, `cargador`…) cuando no se pidieron, los nombres del tipo “para TV”, los muebles cuando el aparato nunca lo es, y las medidas que no calzan (un TV de 55" no aparece si pediste 50"). El resumen de cada búsqueda dice cuántos se fueron por cada motivo.

Orígenes:

- **Tiendas y base de datos**: scrape en vivo + MongoDB + Qdrant
- **Solo tiendas**: scraping actual
- **Solo MongoDB / Qdrant**: histórico, sin pegarle a las tiendas

Si Redis está arriba, el resultado de una búsqueda (por ejemplo «tv») se guarda en clave diaria Chile (`search:AAAA-MM-DD:…`) con TTL hasta medianoche, acotado por `RETAIL_SEARCH_CACHE_MAX_TTL` (default 4 h). La siguiente vez sale de Redis; **Forzar tiendas** vuelve a consultar las cadenas.

Variables: `MONGODB_URI`, `MONGODB_DB`, `QDRANT_URL`, `REDIS_URL`. Si Mongo, Qdrant o Redis no están arriba, la interfaz igual busca en las tiendas y avisa qué no pudo persistir.

## Batch diario de ofertas

El catálogo `retail/batch/catalogo_electronicos.json` tiene 1000 búsquedas populares en Chile (tecnología, supermercado, hogar, moda y más). El cron recorre uno por uno, guarda precios en Mongo y, si una regla dispara, crea una alerta.

```bash
retail batch --dry-run
retail batch --limit 2 --ids galaxy-s25-512,iphone-16-128
retail batch
```

La página **Ofertas y alertas** (`http://127.0.0.1:8080/ofertas`) define reglas, canales, catálogo y cron. También se puede editar `retail/batch/reglas_ofertas.json` a mano. Canales: `log`, `file` (`output/alerts.jsonl`), Telegram y correo.

```
TELEGRAM_BOT_TOKEN  TELEGRAM_CHAT_ID
SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM ALERT_EMAIL_TO
```

La interfaz **Ofertas y alertas** (`http://127.0.0.1:8080/ofertas`) edita reglas, canales (Telegram/correo), el catálogo y instala el cron diario. Tokens se guardan en `output/canales.local.json`.

## Uso

```bash
retail falabella buscar "notebook" -n 20 -o output/fa.csv
retail paris categoria tecCompNotebooks -n 15
retail sodimac categoria CATG36264 --nombre Herramientas-y-maquinas
retail easy categoria herramientas/herramientas-electricas/taladros-y-atornilladores
retail lider buscar "leche colun" -n 20
retail lider categoria 65672745 -n 10
retail lider producto 00888833356718
retail mercadolibre buscar "notebook" -n 15
retail mercadolibre categoria MLC1648 -n 20
retail ikea buscar "silla" -n 10
retail nike buscar "air max" -n 10
retail doite buscar "carpa" -n 10
retail intime categoria pijamas -n 10
retail amphora buscar "cartera" -n 10
retail pcfactory buscar "notebook" -n 10
retail pcfactory producto 57695
retail tottus buscar "leche" -n 10
retail weplay buscar "lego" -n 10
retail antartica buscar "neruda" -n 10
retail rosen categoria camas-y-colchones/colchones -n 10
```

Atajos: `falabella`, `ripley`, `paris`, `sodimac`, `easy`, `lider`, `mercadolibre`, `ikea`, `nike`, `doite`, `lippi`, `drsimi`, `colloky`, `intime`, `amphora`, `fashionspark`, `pcfactory`.

| Opción | Descripción |
|---|---|
| `-p / --paginas` | Máximo de páginas |
| `-n / --max` | Tope de productos |
| `--orden` | `recomendados`, `precio_asc`, `precio_desc`, `rating` |
| `--detalle` | Enriquecer con la ficha (si la tienda lo soporta) |
| `-o / --salida` | `.csv` o `.json` |
| `--delay` | Pausa entre requests (default `1.0`) |

Categorías:

- Falabella / Sodimac: ID tipo `cat720161` o `CATG36264`
- Ripley / Easy: slug de URL
- Paris: ID interno tipo `tecCompNotebooks`
- Lider: ID numérico, por ejemplo `65672745` (sale del final de `/browse/.../ID`)
- Mercado Libre: ID tipo `MLC1648` (Computación). El cliente usa las **ofertas públicas** (`/ofertas`); el listado general y la API oficial responden 403 / challenge.
- IKEA: ID tipo `fu002` (sale del final de `/cat/sillas-fu002/`).
- Nike / Dr. Simi / Colloky / Intime: slug VTEX de la URL, por ejemplo `ropa/polerones`.
- Fashion Spark / Doite / Lippi / Amphora: handle de colección Shopify.
- Tottus: mismo stack de Falabella; categorías tipo `CATGxxxx`.
- WePlay / Antártica / Rosen / Sparta / Cannon / Tienda Flores: slugs Magento (`camas-y-colchones/colchones`). `tiendasflores.cl` no resuelve; el cliente usa `tiendaflores.cl`.

## Agregar otra empresa

Las fuentes viven en `retail/sources/` y se descubren solas. Los motores compartidos (VTEX, Shopify, Magento) están en `retail/platforms/`.

```bash
retail nueva acme --titulo "Acme Chile" --sitio www.acme.cl
retail nueva acme --titulo "Acme Chile" --sitio www.acme.cl --plataforma vtex --marca Acme
retail nueva acme --titulo "Acme Chile" --sitio www.acme.cl --plataforma shopify
retail nueva acme --titulo "Acme Chile" --sitio www.acme.cl --plataforma magento
```

`--plataforma custom` crea `retail/sources/<id>.py` con `StoreClient` + `_iter_listing()`. VTEX / Shopify / Magento reutilizan el factory y quedan listas para buscar. Si quieres atajo CLI, agrégalo en `pyproject.toml`.

## Desde Python

```python
from retail import get_client, list_stores

print([s.id for s in list_stores()])

with get_client("lider", delay=1.0) as client:
    productos = client.scrape("leche", max_pages=1, max_items=10)
```

## Uso responsable

Respeta los términos de cada tienda, usa `--delay` y no hagas barridos agresivos. Lider usa PerimeterX: las fichas `/ip/` y algunas categorías por slug pueden bloquearse; la búsqueda `/browse?query=` es la vía pública que usa este cliente.
# precios
