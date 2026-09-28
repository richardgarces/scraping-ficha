from retail.platforms.magento import make_magento_store, parse_magento_target

parse_mundotransfer_target = parse_magento_target

MundotransferStore = make_magento_store(
    store_id="mundotransfer",
    title="Mundo Transfer",
    site="www.mundotransfer.cl",
    base="https://www.mundotransfer.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
