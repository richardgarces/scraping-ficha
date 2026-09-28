from retail.platforms.magento import make_magento_store, parse_magento_target

parse_dbs_target = parse_magento_target

DbsStore = make_magento_store(
    store_id="dbs",
    title="DBS",
    site="www.dbs.cl",
    base="https://www.dbs.cl",
    category_help="Slug Magento, por ejemplo maquillaje",
)
