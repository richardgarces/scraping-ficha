from retail.platforms.magento import make_magento_store, parse_magento_target

parse_ebest_target = parse_magento_target

EbestStore = make_magento_store(
    store_id="ebest",
    title="EBEST",
    site="www.ebest.cl",
    base="https://www.ebest.cl",
    category_help="Slug Magento, por ejemplo camaras",
)
