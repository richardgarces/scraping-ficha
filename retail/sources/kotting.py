from retail.platforms.magento import make_magento_store, parse_magento_target

parse_kotting_target = parse_magento_target

KottingStore = make_magento_store(
    store_id="kotting",
    title="Kotting",
    site="www.kotting.cl",
    base="https://www.kotting.cl",
    category_help="Slug Magento, por ejemplo poleras",
)
