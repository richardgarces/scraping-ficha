from retail.platforms.magento import make_magento_store, parse_magento_target

parse_brooks_target = parse_magento_target

BrooksStore = make_magento_store(
    store_id="brooks",
    title="Brooks Brothers",
    site="www.brooksbrothers.cl",
    base="https://www.brooksbrothers.cl",
    category_help="Slug Magento, por ejemplo camisas",
)
