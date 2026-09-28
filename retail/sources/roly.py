from retail.platforms.magento import make_magento_store, parse_magento_target

parse_roly_target = parse_magento_target

RolyStore = make_magento_store(
    store_id="roly",
    title="Roly",
    site="www.roly.cl",
    base="https://www.roly.cl",
    category_help="Slug Magento, por ejemplo poleras",
)
