from retail.platforms.magento import make_magento_store, parse_magento_target

parse_cortinas_izurieta_target = parse_magento_target

CortinasIzurietaStore = make_magento_store(
    store_id="cortinas_izurieta",
    title="Cortinas Izurieta",
    site="www.cortinasizurieta.cl",
    base="https://www.cortinasizurieta.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
