from retail.platforms.magento import make_magento_store, parse_magento_target

parse_varsovienne_target = parse_magento_target

VarsovienneStore = make_magento_store(
    store_id="varsovienne",
    title="Varsovienne",
    site="www.varsovienne.cl",
    base="https://www.varsovienne.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
