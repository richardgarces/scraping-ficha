from retail.platforms.magento import make_magento_store, parse_magento_target

parse_iochile_target = parse_magento_target

IochileStore = make_magento_store(
    store_id="iochile",
    title="iO",
    site="www.iochile.cl",
    base="https://www.iochile.cl",
    category_help="Slug Magento, por ejemplo poleras",
)
