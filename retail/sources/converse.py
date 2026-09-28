from retail.platforms.magento import make_magento_store, parse_magento_target

parse_converse_target = parse_magento_target

ConverseStore = make_magento_store(
    store_id="converse",
    title="Converse",
    site="www.converse.cl",
    base="https://www.converse.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
