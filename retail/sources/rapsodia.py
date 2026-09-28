from retail.platforms.magento import make_magento_store, parse_magento_target

parse_rapsodia_target = parse_magento_target

RapsodiaStore = make_magento_store(
    store_id="rapsodia",
    title="Rapsodia",
    site="www.rapsodia.cl",
    base="https://www.rapsodia.cl",
    category_help="Slug Magento, por ejemplo vestidos",
)
