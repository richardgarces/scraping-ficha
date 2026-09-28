from retail.platforms.magento import make_magento_store, parse_magento_target

parse_tecnored_target = parse_magento_target

TecnoredStore = make_magento_store(
    store_id="tecnored",
    title="Tecnored",
    site="www.tiendatecnored.cl",
    base="https://www.tiendatecnored.cl",
    category_help="Slug Magento, por ejemplo ferreteria",
)
