from retail.platforms.magento import make_magento_store, parse_magento_target

parse_drimkip_target = parse_magento_target

DrimkipStore = make_magento_store(
    store_id="drimkip",
    title="Drimkip",
    site="www.drimkip.cl",
    base="https://www.drimkip.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
