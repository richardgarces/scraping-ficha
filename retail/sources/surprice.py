from retail.platforms.magento import make_magento_store, parse_magento_target

parse_surprice_target = parse_magento_target

SurpriceStore = make_magento_store(
    store_id="surprice",
    title="Surprice",
    site="www.surprice.cl",
    base="https://www.surprice.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
