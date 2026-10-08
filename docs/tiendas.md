# Tiendas del Cyber (Cyber Monday 2026)

Inventario de marcas participantes del **Cyber Monday 2026** (CCS / cyber.cl) cruzadas con el scraper de este repo y conteos en Mongo (BMAX).

## Fuentes de datos

| Dato | Origen |
| --- | --- |
| Lista de tiendas / categoría | Listado público de marcas del Cyber Monday 2026 compilado en [cyberdaychile.com/marcas-cyber-monday-2026](https://www.cyberdaychile.com/marcas-cyber-monday-2026/) (519 marcas en 25 categorías; revisión 1-oct-2026; contador oficial cyber.cl ~523). Equivalente a la página de marcas de [cyber.cl/cyber/marcas](https://cyber.cl/cyber/marcas). |
| Incluido en scraping | `si` = hay cliente registrado en `retail/registry.py` / `retail/sources/*`. `no` = marca de retail/productos aún no registrada. `no es posible` = categoría o nombre de servicio (viajes, seguros, inmobiliarias, benéficas, cuponeras, educación, clínicas/hoteles/bancos, etc.) fuera del alcance de catálogo de productos. |
| Productos scrapeados / con descuento | Agregación Mongo BMAX (`products`), 2026-10-08: por `store`, total de documentos y filas con `price_normal > price`. Host `192.168.1.198` / DB `scraping`. Tienda `si` sin documentos → `0`. |
| Grupo Cyber del app | En Mongo `store_categories.cyber_junio2026` hay **246** `store_ids` (grupos `CYBER_STORE_GROUPS` en `retail/cyber_day.py`: retail, tecnología, deporte, hogar, belleza, moda, ferretería). No coincide 1:1 con la lista CCS (p. ej. Líder/Tottus/farmacias están scrapeadas pero fuera de esos grupos). |

## Resumen

- **Marcas en la lista Cyber:** 519
- **Scraping incluido (`si`):** 265 (incl. 37 nuevas por sondeo Shopify/VTEX/Magento, 2026-10-08)
- **No incluidas aún (`no`):** 147
- **No es posible (`no es posible`):** 107
- **Productos scrapeados (suma marcas `si`):** 190.991
- **Productos con descuento (suma marcas `si`):** 60.121

Notas:

- `N/D` = sin `store_id` en el registry (no hay conteo Mongo atribuible).
- Un `0` en productos significa tienda registrada pero sin documentos en `products` al momento del conteo.
- «Con descuento» = precio normal declarado mayor al precio actual; no implica oferta real (`/reales`).
- Actualización 2026-10-08: sondeo automático (`scripts/probe_cyber_stores.py`) scaffoldeó tiendas detectadas como Shopify/VTEX/Magento; detalle en `docs/tiendas_probe_results.json`. Conteos Mongo de las nuevas = 0 hasta el primer scrape.
- Marcas grandes ausentes del listado oficial CCS (Nike, PC Factory, Decathlon, abc, etc.) no aparecen en esta tabla aunque el repo sí las scrapee.

## Tabla

| Tienda | Categoría | Incluido | Productos scrapeados | Productos con descuento |
| --- | --- | --- | ---: | ---: |
| Amphora | Accesorios Moda | si | 229 | 0 |
| Aurus Joyeria | Accesorios Moda | no | N/D | N/D |
| Calu | Accesorios Moda | si | 0 | 0 |
| Djoyas | Accesorios Moda | no | N/D | N/D |
| Humana | Accesorios Moda | no | N/D | N/D |
| La Relojeria | Accesorios Moda | si | 173 | 0 |
| Mis Joyas | Accesorios Moda | si | 22 | 0 |
| Nerfis | Accesorios Moda | no | N/D | N/D |
| Orocash | Accesorios Moda | no | N/D | N/D |
| Pandora | Accesorios Moda | no | N/D | N/D |
| Schilling | Accesorios Moda | si | 166 | 0 |
| So Long! | Accesorios Moda | si | 6 | 0 |
| Swarovski | Accesorios Moda | si | 15 | 2 |
| TOTTO | Accesorios Moda | si | 130 | 81 |
| Adagio Teas | Alimentos y Bebidas | si | 25 | 0 |
| Booz | Alimentos y Bebidas | no | N/D | N/D |
| Deep Productivity & Performance | Alimentos y Bebidas | no | N/D | N/D |
| ExtraVirgen.Store | Alimentos y Bebidas | si | 21 | 0 |
| HUENTELAUQUEN | Alimentos y Bebidas | si | 0 | 0 |
| Juan Valdez | Alimentos y Bebidas | si | 52 | 0 |
| La Barra CCU | Alimentos y Bebidas | no | N/D | N/D |
| La Vinoteca | Alimentos y Bebidas | si | 64 | 11 |
| Marley Coffee | Alimentos y Bebidas | si | 47 | 27 |
| miCoca-Cola.cl | Alimentos y Bebidas | no | N/D | N/D |
| Nutriscomarket.cl | Alimentos y Bebidas | si | 0 | 0 |
| Outlet del cafe | Alimentos y Bebidas | si | 22 | 0 |
| Papa Johns | Alimentos y Bebidas | no es posible | N/D | N/D |
| Piwen | Alimentos y Bebidas | si | 40 | 0 |
| SALMON MARKETPLACE | Alimentos y Bebidas | si | 2 | 0 |
| Santa Rita Online | Alimentos y Bebidas | si | 7 | 7 |
| Tremus | Alimentos y Bebidas | no | N/D | N/D |
| Volka Chokolade | Alimentos y Bebidas | no | N/D | N/D |
| Chery | Automotriz | no es posible | N/D | N/D |
| Dercocenter | Automotriz | no es posible | N/D | N/D |
| Exeed | Automotriz | no es posible | N/D | N/D |
| Hyundai | Automotriz | no es posible | N/D | N/D |
| JAC | Automotriz | no es posible | N/D | N/D |
| Orion Lubricantes | Automotriz | no | N/D | N/D |
| Subaru | Automotriz | no es posible | N/D | N/D |
| Agrupemonos | Cuponeras | no es posible | N/D | N/D |
| Cuponatic | Cuponeras | no es posible | N/D | N/D |
| Andesgear | Deportes y Outdoor | si | 360 | 0 |
| Andesland | Deportes y Outdoor | no | N/D | N/D |
| Atletis | Deportes y Outdoor | si | 0 | 0 |
| AWL | Deportes y Outdoor | no | N/D | N/D |
| Bamo | Deportes y Outdoor | no | N/D | N/D |
| BossCamp | Deportes y Outdoor | si | 34 | 0 |
| Coleman | Deportes y Outdoor | si | 33 | 17 |
| Columbia | Deportes y Outdoor | no | N/D | N/D |
| Dimarine | Deportes y Outdoor | si | 197 | 30 |
| Discovery | Deportes y Outdoor | no | N/D | N/D |
| Getway | Deportes y Outdoor | si | 0 | 0 |
| Giant Bicycles | Deportes y Outdoor | no | N/D | N/D |
| Hakahonu | Deportes y Outdoor | si | 329 | 0 |
| Head (Tenis y Padel) | Deportes y Outdoor | si | 10 | 0 |
| Hoka | Deportes y Outdoor | no | N/D | N/D |
| Ironside | Deportes y Outdoor | si | 32 | 1 |
| Kannu | Deportes y Outdoor | si | 8 | 0 |
| Kano | Deportes y Outdoor | no | N/D | N/D |
| La Pica del Ski | Deportes y Outdoor | no | N/D | N/D |
| Lippi | Deportes y Outdoor | si | 1.189 | 3 |
| Mammut | Deportes y Outdoor | si | 114 | 0 |
| Marmot | Deportes y Outdoor | si | 59 | 0 |
| Merrell | Deportes y Outdoor | si | 296 | 0 |
| Mormaii | Deportes y Outdoor | si | 47 | 43 |
| Pesas Chile | Deportes y Outdoor | si | 50 | 6 |
| Sparta | Deportes y Outdoor | si | 24 | 0 |
| Speedo | Deportes y Outdoor | si | 9 | 0 |
| Sporting Brands | Deportes y Outdoor | si | 69 | 0 |
| Stoked | Deportes y Outdoor | si | 55 | 0 |
| The North Face | Deportes y Outdoor | si | 231 | 0 |
| Trail Store | Deportes y Outdoor | si | 0 | 0 |
| Trek | Deportes y Outdoor | si | 110 | 22 |
| Under Armour | Deportes y Outdoor | si | 407 | 4 |
| Volcano Trailer | Deportes y Outdoor | no | N/D | N/D |
| Volkanica | Deportes y Outdoor | si | 178 | 0 |
| Vulcano | Deportes y Outdoor | no | N/D | N/D |
| Weinbrenner | Deportes y Outdoor | no | N/D | N/D |
| Yonex | Deportes y Outdoor | si | 69 | 0 |
| Antártica Libros | Educación y Cultura | si | 1.009 | 0 |
| Bosque Chileno | Educación y Cultura | no es posible | N/D | N/D |
| BuscaLibre | Educación y Cultura | no es posible | N/D | N/D |
| Libreria Contrapunto | Educación y Cultura | no es posible | N/D | N/D |
| Metodo Speed Academy | Educación y Cultura | no es posible | N/D | N/D |
| Poliglota | Educación y Cultura | no es posible | N/D | N/D |
| Qcap | Educación y Cultura | no es posible | N/D | N/D |
| Baepink | Entretención | si | 0 | 0 |
| Full Sublimacion | Entretención | si | 2 | 0 |
| Fumetas Store | Entretención | no | N/D | N/D |
| Ozeta | Entretención | no | N/D | N/D |
| Punto Ticket | Entretención | no es posible | N/D | N/D |
| SOYPREMIUM | Entretención | no es posible | N/D | N/D |
| Ticketmaster | Entretención | no es posible | N/D | N/D |
| VADELL | Entretención | si | 92 | 0 |
| Zigzaboo | Entretención | no | N/D | N/D |
| Black Bubba | Equipaje, Bolsos y Maletas | si | 42 | 0 |
| Delsey | Equipaje, Bolsos y Maletas | si | 18 | 0 |
| Head | Equipaje, Bolsos y Maletas | si | 10 | 0 |
| Jansport | Equipaje, Bolsos y Maletas | si | 10 | 6 |
| Kipling | Equipaje, Bolsos y Maletas | si | 8 | 0 |
| PILGRIM TRAVEL STORE | Equipaje, Bolsos y Maletas | si | 74 | 0 |
| Construplaza | Ferretería y Construcción | si | 1.121 | 999 |
| Ferrelan | Ferretería y Construcción | no | N/D | N/D |
| Ferreteria Marsella | Ferretería y Construcción | si | 440 | 265 |
| FERRETERIA.CL | Ferretería y Construcción | no | N/D | N/D |
| Imperial | Ferretería y Construcción | no | N/D | N/D |
| Junheinrich | Ferretería y Construcción | no | N/D | N/D |
| Maktotal | Ferretería y Construcción | si | 0 | 0 |
| Maquep Chile | Ferretería y Construcción | no | N/D | N/D |
| Marienberg | Ferretería y Construcción | no | N/D | N/D |
| Mimbral | Ferretería y Construcción | si | 1.740 | 1.001 |
| MiService | Ferretería y Construcción | no | N/D | N/D |
| Oviedo Ferreteria | Ferretería y Construcción | no | N/D | N/D |
| Patio Ferretero | Ferretería y Construcción | si | 203 | 0 |
| RCR Ferreteria | Ferretería y Construcción | no | N/D | N/D |
| RSG INDUSTRIAL | Ferretería y Construcción | no | N/D | N/D |
| Tecnored | Ferretería y Construcción | si | 116 | 42 |
| Tehtools | Ferretería y Construcción | si | 0 | 0 |
| TOTALTOOLS | Ferretería y Construcción | si | 341 | 0 |
| van Beek | Ferretería y Construcción | si | 57 | 0 |
| Bazhars | Hogar | si | 5 | 0 |
| Bbq Grill | Hogar | si | 34 | 22 |
| Bestway | Hogar | no | N/D | N/D |
| Bix | Hogar | si | 283 | 0 |
| Blanik | Hogar | si | 0 | 0 |
| CHC | Hogar | no | N/D | N/D |
| Chef Lab | Hogar | si | 34 | 0 |
| Cic | Hogar | no | N/D | N/D |
| Cortinas Izurieta | Hogar | si | 0 | 0 |
| Covepa | Hogar | no | N/D | N/D |
| Dib | Hogar | si | 95 | 0 |
| DONDE NACEN LAS VELAS | Hogar | si | 0 | 0 |
| Drimkip | Hogar | si | 0 | 0 |
| Easy | Hogar | si | 14.452 | 7.242 |
| EITA Comercializadora | Hogar | no | N/D | N/D |
| El Castillo | Hogar | no | N/D | N/D |
| Electrolux | Hogar | si | 100 | 93 |
| Emma Sleep | Hogar | no | N/D | N/D |
| ENEL STORE | Hogar | no es posible | N/D | N/D |
| Flex | Hogar | si | 100 | 69 |
| Form Design | Hogar | si | 214 | 1 |
| GÜTEN BREW | Hogar | si | 5 | 0 |
| Hohos | Hogar | si | 27 | 6 |
| Igpro | Hogar | no | N/D | N/D |
| IKEA | Hogar | si | 868 | 0 |
| Imahe | Hogar | si | 243 | 0 |
| Importaciones Reus | Hogar | no | N/D | N/D |
| iRobot | Hogar | no | N/D | N/D |
| Kendal | Hogar | no | N/D | N/D |
| Kitchen House | Hogar | si | 152 | 1 |
| Kärcher | Hogar | no | N/D | N/D |
| LANCO PAINTS | Hogar | no | N/D | N/D |
| Mabe | Hogar | no | N/D | N/D |
| Mademsa | Hogar | si | 124 | 120 |
| Mi foto | Hogar | no | N/D | N/D |
| Milu | Hogar | si | 6 | 0 |
| MUEBLES Y TERRAZAS | Hogar | si | 12 | 4 |
| Oster | Hogar | si | 102 | 37 |
| Rincon Himalaya | Hogar | si | 87 | 0 |
| Rosen | Hogar | si | 181 | 0 |
| Sharkninja | Hogar | si | 23 | 0 |
| Sodimac | Hogar | si | 19.147 | 3.580 |
| Steward | Hogar | no | N/D | N/D |
| Thorben Store | Hogar | si | 73 | 0 |
| Toyotomi | Hogar | si | 13 | 3 |
| Tramontina | Hogar | si | 318 | 73 |
| Tu Tienda Metrogas | Hogar | no es posible | N/D | N/D |
| Vadell Home | Hogar | si | 92 | 0 |
| Ventus | Hogar | si | 66 | 47 |
| Ansaldo Toys | Infantil | si | 539 | 0 |
| Baby Rosen | Infantil | si | 0 | 0 |
| Bubblegummers | Infantil | no | N/D | N/D |
| Carestino | Infantil | no | N/D | N/D |
| Crescente | Infantil | no | N/D | N/D |
| Hasbro | Infantil | si | 0 | 0 |
| INFANTI | Infantil | si | 126 | 0 |
| Lego | Infantil | no | N/D | N/D |
| Mamas Mateas | Infantil | si | 280 | 0 |
| Mi primera Foto | Infantil | si | 0 | 0 |
| Pichintun | Infantil | si | 0 | 0 |
| SlimeHuum | Infantil | no | N/D | N/D |
| Toyng | Infantil | si | 83 | 0 |
| Capitalizarme.com | Inmobiliarias | no es posible | N/D | N/D |
| Exxacon Inmobiliaria | Inmobiliarias | no es posible | N/D | N/D |
| Grupo Hogares | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Aconcagua | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria BBL | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Bricsa | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Esepe | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Imagina | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Norte Verde | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Paz | Inmobiliarias | no es posible | N/D | N/D |
| Inmobiliaria Sento | Inmobiliarias | no es posible | N/D | N/D |
| Larrain Prieto | Inmobiliarias | no es posible | N/D | N/D |
| Leben Grupo Inmobiliario | Inmobiliarias | no es posible | N/D | N/D |
| Numancia Inmobiliaria | Inmobiliarias | no es posible | N/D | N/D |
| Portal Inmobiliario | Inmobiliarias | no es posible | N/D | N/D |
| Africa Dream | Instituciones Benéficas | no es posible | N/D | N/D |
| Aldeas Infantiles SOS | Instituciones Benéficas | no es posible | N/D | N/D |
| Aspaut | Instituciones Benéficas | no es posible | N/D | N/D |
| Ayuda bomberos | Instituciones Benéficas | no es posible | N/D | N/D |
| Chile Unido | Instituciones Benéficas | no es posible | N/D | N/D |
| Conecta Mayor | Instituciones Benéficas | no es posible | N/D | N/D |
| Corporacion Jesus Niño | Instituciones Benéficas | no es posible | N/D | N/D |
| Corporación MATER | Instituciones Benéficas | no es posible | N/D | N/D |
| DKMS | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Arturo Lopez Perez | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Aspade | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Beata Laura Vicuña | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Debra | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Gantz | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Las Rosas | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Nino y Patria | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion Nuestros Hijos | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion San Esteban Martir | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundacion San Jose | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundación Avanzar | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundación Cristo Vive | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundación Honra | Instituciones Benéficas | no es posible | N/D | N/D |
| Fundación María de la Luz | Instituciones Benéficas | no es posible | N/D | N/D |
| Good Neighbors Chile | Instituciones Benéficas | no es posible | N/D | N/D |
| Protectora de la Infancia | Instituciones Benéficas | no es posible | N/D | N/D |
| WWF Chile | Instituciones Benéficas | no es posible | N/D | N/D |
| Balustore.cl | Mascotas | no | N/D | N/D |
| Befoods | Mascotas | si | 4 | 0 |
| Braloy | Mascotas | si | 3 | 3 |
| Club de perros y gatos | Mascotas | no | N/D | N/D |
| DR. PET | Mascotas | no | N/D | N/D |
| Felinus | Mascotas | no | N/D | N/D |
| Laika Mascotas | Mascotas | no | N/D | N/D |
| Pawal | Mascotas | no | N/D | N/D |
| Petco | Mascotas | no | N/D | N/D |
| Petvet | Mascotas | si | 4 | 0 |
| Puppies & Kittens | Mascotas | si | 8 | 0 |
| Razas Pet | Mascotas | si | 6 | 5 |
| SuperZoo | Mascotas | no | N/D | N/D |
| Tus Mascotas | Mascotas | si | 11 | 7 |
| HomeMobili | Muebles | si | 88 | 0 |
| Kallfu | Muebles | si | 44 | 0 |
| Keter | Muebles | si | 38 | 0 |
| LaSilleria | Muebles | si | 10 | 8 |
| LIVING STORE | Muebles | no | N/D | N/D |
| Muebles Santa Ana | Muebles | no | N/D | N/D |
| Novahus | Muebles | si | 0 | 0 |
| Relan | Muebles | si | 126 | 0 |
| Spazzio Design | Muebles | si | 110 | 0 |
| Vekka Home | Muebles | no | N/D | N/D |
| Wayu | Muebles | si | 38 | 0 |
| Zoy Home | Muebles | si | 19 | 0 |
| ClubSoftys | Multitiendas y Supermercados | si | 22 | 16 |
| De todo y mas | Multitiendas y Supermercados | no | N/D | N/D |
| Dimarsa | Multitiendas y Supermercados | si | 2.225 | 603 |
| Elite Professional | Multitiendas y Supermercados | si | 0 | 0 |
| Falabella.com | Multitiendas y Supermercados | si | 34.992 | 3.726 |
| Gift Card Cencosud | Multitiendas y Supermercados | no es posible | N/D | N/D |
| Hites | Multitiendas y Supermercados | si | 5.642 | 3.945 |
| Jumbo | Multitiendas y Supermercados | si | 0 | 0 |
| Lider.cl | Multitiendas y Supermercados | si | 30.251 | 11.851 |
| Mercado Libre | Multitiendas y Supermercados | si | 84 | 27 |
| Paris.cl | Multitiendas y Supermercados | si | 23.908 | 10.281 |
| PedidosYa | Multitiendas y Supermercados | no es posible | N/D | N/D |
| Retail.cl | Multitiendas y Supermercados | si | 256 | 1 |
| Ripley | Multitiendas y Supermercados | si | 28.116 | 12.464 |
| Santa Isabel | Multitiendas y Supermercados | si | 0 | 0 |
| SuperStore | Multitiendas y Supermercados | si | 0 | 0 |
| Tienda Copec | Multitiendas y Supermercados | si | 693 | 0 |
| Tottus | Multitiendas y Supermercados | si | 3.091 | 739 |
| Audiomusica | Música y Audio | si | 170 | 73 |
| Blupoint Music | Música y Audio | no | N/D | N/D |
| Casa Amarilla | Música y Audio | no | N/D | N/D |
| Hitway Music | Música y Audio | si | 84 | 0 |
| Music World | Música y Audio | no | N/D | N/D |
| Polyphonik | Música y Audio | si | 46 | 0 |
| Promusic | Música y Audio | si | 129 | 0 |
| A.Zedan | Neumáticos y Accesorios | si | 0 | 0 |
| AmortiguadoresK | Neumáticos y Accesorios | no | N/D | N/D |
| Authievre Motors | Neumáticos y Accesorios | no | N/D | N/D |
| Autoplanet | Neumáticos y Accesorios | no | N/D | N/D |
| Bemarket | Neumáticos y Accesorios | no | N/D | N/D |
| Bigmoto | Neumáticos y Accesorios | no | N/D | N/D |
| Caren | Neumáticos y Accesorios | no | N/D | N/D |
| Chile Neumaticos | Neumáticos y Accesorios | no | N/D | N/D |
| Descuento Neumatico | Neumáticos y Accesorios | no | N/D | N/D |
| Mall del Neumatico | Neumáticos y Accesorios | no | N/D | N/D |
| Maxxis Chile | Neumáticos y Accesorios | no | N/D | N/D |
| Mitas | Neumáticos y Accesorios | no | N/D | N/D |
| Mundo Repuestos | Neumáticos y Accesorios | no | N/D | N/D |
| Neumaspot | Neumáticos y Accesorios | no | N/D | N/D |
| NEUMATICOSK | Neumáticos y Accesorios | no | N/D | N/D |
| Neumax | Neumáticos y Accesorios | si | 3 | 1 |
| Red Barrera | Neumáticos y Accesorios | no | N/D | N/D |
| Repuestos Boston | Neumáticos y Accesorios | si | 2 | 0 |
| Ruta Diferente | Neumáticos y Accesorios | si | 18 | 0 |
| Supermercado del Neumatico | Neumáticos y Accesorios | si | 0 | 0 |
| Tienda Salfa | Neumáticos y Accesorios | si | 0 | 0 |
| TIRES IMPORT | Neumáticos y Accesorios | si | 2 | 2 |
| Vitepal | Neumáticos y Accesorios | si | 23 | 7 |
| Flores | Ropa Interior y Pijamas | no | N/D | N/D |
| Kayser | Ropa Interior y Pijamas | si | 81 | 0 |
| Lenceria.cl | Ropa Interior y Pijamas | si | 31 | 0 |
| Victoria’s Secret | Ropa Interior y Pijamas | si | 0 | 0 |
| Alisha Perfumes | Salud y Belleza | si | 98 | 0 |
| All Nutrition | Salud y Belleza | si | 197 | 0 |
| Bath & Body Works | Salud y Belleza | si | 0 | 0 |
| Cherimoya | Salud y Belleza | no | N/D | N/D |
| Chile Perfume | Salud y Belleza | si | 13 | 13 |
| Clinica Altos del Desierto | Salud y Belleza | no es posible | N/D | N/D |
| Clinica Belenus | Salud y Belleza | no es posible | N/D | N/D |
| Clinica Cela | Salud y Belleza | no es posible | N/D | N/D |
| Clinica Cince | Salud y Belleza | no es posible | N/D | N/D |
| Clinica Syal | Salud y Belleza | no es posible | N/D | N/D |
| Coreana | Salud y Belleza | no | N/D | N/D |
| Cosmetic.cl | Salud y Belleza | si | 288 | 0 |
| DBS | Salud y Belleza | si | 4 | 1 |
| Dermotienda | Salud y Belleza | si | 116 | 0 |
| Dominame.cl SexShop | Salud y Belleza | si | 53 | 0 |
| DRA. SIERRALTA | Salud y Belleza | no es posible | N/D | N/D |
| Eco Farmacias | Salud y Belleza | si | 198 | 27 |
| Elite Perfumes | Salud y Belleza | si | 76 | 0 |
| Farmacias Ahumada | Salud y Belleza | si | 527 | 230 |
| Farmacias Knop | Salud y Belleza | no | N/D | N/D |
| Ho Nutrition | Salud y Belleza | si | 4 | 0 |
| Japi Jane | Salud y Belleza | si | 49 | 0 |
| JPT | Salud y Belleza | no | N/D | N/D |
| JPT Luxury | Salud y Belleza | no | N/D | N/D |
| Kliki | Salud y Belleza | si | 0 | 0 |
| Lasertam | Salud y Belleza | no es posible | N/D | N/D |
| LATTAFA PERFUMES | Salud y Belleza | no | N/D | N/D |
| Leche Pal Pelo | Salud y Belleza | si | 10 | 0 |
| Lodoro Perfumes | Salud y Belleza | si | 116 | 0 |
| Long Love | Salud y Belleza | no | N/D | N/D |
| L’bel | Salud y Belleza | no | N/D | N/D |
| Maison Niche | Salud y Belleza | si | 0 | 0 |
| Mayordent | Salud y Belleza | si | 8 | 0 |
| Mi tienda Cotidian | Salud y Belleza | no | N/D | N/D |
| Multimarcas Perfumes | Salud y Belleza | si | 82 | 0 |
| Mundo Aromas | Salud y Belleza | si | 126 | 0 |
| Natura | Salud y Belleza | no | N/D | N/D |
| Nooki | Salud y Belleza | si | 43 | 0 |
| Parfumerie d’Aquitaine | Salud y Belleza | si | 5 | 0 |
| Preunic | Salud y Belleza | si | 515 | 154 |
| Productos de Lujo | Salud y Belleza | si | 271 | 0 |
| Saideep | Salud y Belleza | si | 62 | 0 |
| Sairam Perfumes | Salud y Belleza | no | N/D | N/D |
| Salcobrand | Salud y Belleza | si | 516 | 262 |
| Santiago perfumes | Salud y Belleza | si | 0 | 0 |
| Secretos de amor | Salud y Belleza | no | N/D | N/D |
| Simmedical | Salud y Belleza | no es posible | N/D | N/D |
| Skar Cosmetics | Salud y Belleza | no | N/D | N/D |
| Sokobox | Salud y Belleza | si | 38 | 0 |
| Starsex | Salud y Belleza | si | 48 | 0 |
| The Beauty Box | Salud y Belleza | si | 31 | 0 |
| UltraEstetica | Salud y Belleza | no es posible | N/D | N/D |
| V&P Perfumeria | Salud y Belleza | no | N/D | N/D |
| Vesperstore | Salud y Belleza | si | 10 | 0 |
| Viuty | Salud y Belleza | si | 11 | 4 |
| Yauras | Salud y Belleza | si | 89 | 0 |
| ÉSIKA | Salud y Belleza | no | N/D | N/D |
| Banco Internacional | Seguros y Servicios | no es posible | N/D | N/D |
| Bci Seguros | Seguros y Servicios | no es posible | N/D | N/D |
| Consorcio | Seguros y Servicios | no es posible | N/D | N/D |
| HDI Seguros | Seguros y Servicios | no es posible | N/D | N/D |
| Queplan | Seguros y Servicios | no es posible | N/D | N/D |
| Seguros Falabella | Seguros y Servicios | no es posible | N/D | N/D |
| Seguros Ripley | Seguros y Servicios | no es posible | N/D | N/D |
| Zenit Seguros | Seguros y Servicios | no es posible | N/D | N/D |
| Acer | Tecnología | si | 29 | 0 |
| Amazing | Tecnología | no | N/D | N/D |
| Back Online | Tecnología | si | 0 | 0 |
| Belkin | Tecnología | si | 48 | 1 |
| Bestmart | Tecnología | si | 352 | 0 |
| BLU Store | Tecnología | si | 161 | 4 |
| Casa Royal | Tecnología | si | 618 | 468 |
| Dimacofi | Tecnología | no | N/D | N/D |
| Domotiz | Tecnología | si | 21 | 0 |
| Ebest | Tecnología | si | 392 | 0 |
| Emotions | Tecnología | no | N/D | N/D |
| EPSON | Tecnología | no | N/D | N/D |
| ETChile | Tecnología | si | 55 | 25 |
| Garmin | Tecnología | si | 39 | 0 |
| Globaltecno | Tecnología | no | N/D | N/D |
| HP | Tecnología | si | 85 | 0 |
| JBL | Tecnología | no | N/D | N/D |
| Lenovo | Tecnología | no | N/D | N/D |
| LG | Tecnología | no | N/D | N/D |
| Mac Online | Tecnología | no | N/D | N/D |
| Mi foto Pro | Tecnología | si | 6 | 0 |
| Motorola | Tecnología | si | 1 | 1 |
| Movistar | Tecnología | si | 10 | 0 |
| Mundotransfer | Tecnología | si | 146 | 0 |
| Reuse | Tecnología | si | 0 | 0 |
| SC Global | Tecnología | no | N/D | N/D |
| Sony | Tecnología | si | 0 | 0 |
| Tecno Lace | Tecnología | no | N/D | N/D |
| TodoToner.cl | Tecnología | no | N/D | N/D |
| Tu Gadget | Tecnología | no | N/D | N/D |
| Worbee | Tecnología | si | 12 | 0 |
| Zagg | Tecnología | si | 27 | 0 |
| Apro | Vestuario Industrial | si | 188 | 2 |
| Calzado de Seguridad | Vestuario Industrial | si | 0 | 0 |
| Edelbrock | Vestuario Industrial | si | 15 | 0 |
| Jayson | Vestuario Industrial | si | 13 | 0 |
| Safety Store | Vestuario Industrial | si | 223 | 0 |
| Treck | Vestuario Industrial | si | 163 | 99 |
| Tworld Store | Vestuario Industrial | no | N/D | N/D |
| 16 hrs | Vestuario y Calzado | no | N/D | N/D |
| Adidas | Vestuario y Calzado | no | N/D | N/D |
| American Eagle | Vestuario y Calzado | si | 148 | 68 |
| Antihuman | Vestuario y Calzado | no | N/D | N/D |
| Arrow | Vestuario y Calzado | si | 92 | 55 |
| Ash | Vestuario y Calzado | no | N/D | N/D |
| Azaleia | Vestuario y Calzado | si | 144 | 0 |
| Bamers | Vestuario y Calzado | si | 0 | 0 |
| Banana Republic | Vestuario y Calzado | si | 183 | 0 |
| Bata | Vestuario y Calzado | no | N/D | N/D |
| Belsport | Vestuario y Calzado | no | N/D | N/D |
| Bold | Vestuario y Calzado | no | N/D | N/D |
| Brooks Brothers | Vestuario y Calzado | si | 61 | 0 |
| Bruno Rossi | Vestuario y Calzado | no | N/D | N/D |
| Bsoul | Vestuario y Calzado | si | 130 | 0 |
| Calper | Vestuario y Calzado | no | N/D | N/D |
| Calvin Klein | Vestuario y Calzado | si | 221 | 102 |
| Cardinale | Vestuario y Calzado | si | 189 | 0 |
| Cat | Vestuario y Calzado | no | N/D | N/D |
| Crocs | Vestuario y Calzado | si | 176 | 0 |
| Dc Shoes | Vestuario y Calzado | si | 151 | 0 |
| Dockers | Vestuario y Calzado | si | 49 | 2 |
| Dolly | Vestuario y Calzado | si | 329 | 178 |
| Doxie Chile | Vestuario y Calzado | no | N/D | N/D |
| Ellus | Vestuario y Calzado | si | 138 | 57 |
| Family Shop | Vestuario y Calzado | no | N/D | N/D |
| Fashion’s Park | Vestuario y Calzado | si | 858 | 0 |
| Ferouch | Vestuario y Calzado | si | 179 | 91 |
| Florsheim | Vestuario y Calzado | si | 55 | 32 |
| Gap | Vestuario y Calzado | si | 457 | 0 |
| Globe | Vestuario y Calzado | no | N/D | N/D |
| Guess | Vestuario y Calzado | si | 86 | 0 |
| H&M | Vestuario y Calzado | no | N/D | N/D |
| Hardwork | Vestuario y Calzado | si | 82 | 0 |
| Hush Puppies | Vestuario y Calzado | si | 240 | 0 |
| IL Gioco | Vestuario y Calzado | si | 22 | 14 |
| iO | Vestuario y Calzado | si | 38 | 0 |
| Kliper | Vestuario y Calzado | si | 0 | 0 |
| Kotting | Vestuario y Calzado | si | 21 | 0 |
| Lacoste | Vestuario y Calzado | si | 0 | 0 |
| Levi’s | Vestuario y Calzado | si | 183 | 32 |
| Lineatre | Vestuario y Calzado | si | 94 | 0 |
| Ludovica | Vestuario y Calzado | si | 0 | 0 |
| MaGriffe | Vestuario y Calzado | si | 40 | 0 |
| Marathon | Vestuario y Calzado | no | N/D | N/D |
| Maui and Sons | Vestuario y Calzado | si | 15 | 0 |
| McGregor | Vestuario y Calzado | si | 6 | 0 |
| Mingo | Vestuario y Calzado | no | N/D | N/D |
| Mohicano jeans | Vestuario y Calzado | si | 17 | 0 |
| New Balance | Vestuario y Calzado | si | 11 | 0 |
| New Man | Vestuario y Calzado | si | 56 | 32 |
| North Star | Vestuario y Calzado | no | N/D | N/D |
| O’neill | Vestuario y Calzado | si | 0 | 0 |
| Panama Jack | Vestuario y Calzado | no | N/D | N/D |
| Penguin | Vestuario y Calzado | si | 0 | 0 |
| Perry Ellis | Vestuario y Calzado | si | 119 | 87 |
| PIERO BUTTI | Vestuario y Calzado | no | N/D | N/D |
| Pollini | Vestuario y Calzado | no | N/D | N/D |
| Potros | Vestuario y Calzado | si | 18 | 0 |
| Privilege | Vestuario y Calzado | si | 49 | 39 |
| Prune | Vestuario y Calzado | si | 51 | 26 |
| Pz.cl | Vestuario y Calzado | no | N/D | N/D |
| Quebec | Vestuario y Calzado | no | N/D | N/D |
| Rapsodia | Vestuario y Calzado | si | 53 | 0 |
| Reebok | Vestuario y Calzado | si | 229 | 63 |
| Renatta & Go | Vestuario y Calzado | no | N/D | N/D |
| Rip Curl | Vestuario y Calzado | si | 18 | 0 |
| Rockford | Vestuario y Calzado | no | N/D | N/D |
| Roly | Vestuario y Calzado | si | 38 | 0 |
| Rusty | Vestuario y Calzado | si | 0 | 0 |
| Singolare | Vestuario y Calzado | si | 31 | 0 |
| Sioux | Vestuario y Calzado | no | N/D | N/D |
| Skechers | Vestuario y Calzado | no | N/D | N/D |
| Surprice | Vestuario y Calzado | si | 0 | 0 |
| The Line | Vestuario y Calzado | si | 247 | 70 |
| TheLabstore | Vestuario y Calzado | si | 88 | 0 |
| Tommy Hilfiger | Vestuario y Calzado | si | 137 | 45 |
| Trial | Vestuario y Calzado | si | 169 | 101 |
| UGG | Vestuario y Calzado | no | N/D | N/D |
| Umbrale | Vestuario y Calzado | si | 0 | 0 |
| Vans | Vestuario y Calzado | si | 265 | 14 |
| Velez | Vestuario y Calzado | si | 125 | 34 |
| Volcom | Vestuario y Calzado | si | 18 | 0 |
| Wados | Vestuario y Calzado | si | 69 | 0 |
| Women’Secret | Vestuario y Calzado | si | 112 | 64 |
| Zapatos | Vestuario y Calzado | si | 0 | 0 |
| Zappa | Vestuario y Calzado | no | N/D | N/D |
| Aguas Calientes | Viajes y Turismo | no es posible | N/D | N/D |
| Assist Card | Viajes y Turismo | no es posible | N/D | N/D |
| ATLAS TRAVEL | Viajes y Turismo | no es posible | N/D | N/D |
| Atrapalo.cl | Viajes y Turismo | no es posible | N/D | N/D |
| Celebrity Cruises | Viajes y Turismo | no es posible | N/D | N/D |
| Club Med | Viajes y Turismo | no es posible | N/D | N/D |
| Cocha | Viajes y Turismo | no es posible | N/D | N/D |
| Despegar.com | Viajes y Turismo | no es posible | N/D | N/D |
| EL COPIHUE | Viajes y Turismo | no es posible | N/D | N/D |
| Hotel Radisson Puerto Varas | Viajes y Turismo | no es posible | N/D | N/D |
| Huilo Huilo | Viajes y Turismo | no es posible | N/D | N/D |
| Iberia | Viajes y Turismo | no es posible | N/D | N/D |
| Latam Airlines | Viajes y Turismo | no es posible | N/D | N/D |
| LEVEL | Viajes y Turismo | no es posible | N/D | N/D |
| MSC Cruceros | Viajes y Turismo | no es posible | N/D | N/D |
| Parque Futangue | Viajes y Turismo | no es posible | N/D | N/D |
| Puyehue | Viajes y Turismo | no es posible | N/D | N/D |
| RAYS TRAVEL | Viajes y Turismo | no es posible | N/D | N/D |
| Royal Caribbean | Viajes y Turismo | no es posible | N/D | N/D |
| Termas de Chillan | Viajes y Turismo | no es posible | N/D | N/D |
| Travel Security | Viajes y Turismo | no es posible | N/D | N/D |
| TU DESTINO | Viajes y Turismo | no es posible | N/D | N/D |
| Turismocity | Viajes y Turismo | no es posible | N/D | N/D |
| Universal Assistance | Viajes y Turismo | no es posible | N/D | N/D |
| Viajes El Corte Ingles | Viajes y Turismo | no es posible | N/D | N/D |
| Viajes Falabella | Viajes y Turismo | no es posible | N/D | N/D |
| Viajobien.com | Viajes y Turismo | no es posible | N/D | N/D |

## Relación con el código del proyecto

- Worker / grupo de queries: `retail/cyber_day.py` (`cyber_junio2026`, seed Sonic).
- Tiendas del grupo Cyber app: `cyber_store_ids()` ← `STORE_GROUP` ∩ `CYBER_STORE_GROUPS`.
- Preferidas para scrape en vivo del loop: `CYBER_DAY_STORES` (default `falabella,paris,ripley,hites,lider,abcdin`).
- UI admin: `/cyber-day`; ranking de confianza del «antes»: `/tiendas` (otro dashboard).

