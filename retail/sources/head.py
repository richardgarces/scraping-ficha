from retail.platforms.magento import make_magento_store, parse_magento_target

parse_head_target = parse_magento_target

HeadStore = make_magento_store(
    store_id="head",
    title="Head",
    site="www.head.cl",
    base="https://www.head.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
