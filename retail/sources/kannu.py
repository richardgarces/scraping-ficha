from retail.platforms.magento import make_magento_store, parse_magento_target

parse_kannu_target = parse_magento_target

KannuStore = make_magento_store(
    store_id="kannu",
    title="Kannú",
    site="www.kannu.cl",
    base="https://www.kannu.cl",
    category_help="Slug Magento, por ejemplo poleras",
)
