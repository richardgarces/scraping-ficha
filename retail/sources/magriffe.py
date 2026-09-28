from retail.platforms.magento import make_magento_store, parse_magento_target

parse_magriffe_target = parse_magento_target

MagriffeStore = make_magento_store(
    store_id="magriffe",
    title="Ma Griffe",
    site="www.magriffe.cl",
    base="https://www.magriffe.cl",
    category_help="Slug Magento, por ejemplo blusas",
)
