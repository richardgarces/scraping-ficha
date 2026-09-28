from retail.platforms.magento import make_magento_store, parse_magento_target

parse_schilling_target = parse_magento_target

SchillingStore = make_magento_store(
    store_id="schilling",
    title="Schilling",
    site="www.schilling.cl",
    base="https://www.schilling.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
