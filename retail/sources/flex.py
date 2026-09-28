from retail.platforms.magento import make_magento_store, parse_magento_target

parse_flex_target = parse_magento_target

FlexStore = make_magento_store(
    store_id="flex",
    title="Flex",
    site="www.flex.cl",
    base="https://www.flex.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
