from retail.platforms.magento import make_magento_store, parse_magento_target

parse_sparta_target = parse_magento_target

SpartaStore = make_magento_store(
    store_id="sparta",
    title="Sparta",
    site="www.sparta.cl",
    base="https://www.sparta.cl",
    category_help="Slug Magento de categoría",
)
