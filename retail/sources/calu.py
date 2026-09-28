from retail.platforms.magento import make_magento_store, parse_magento_target

parse_calu_target = parse_magento_target

CaluStore = make_magento_store(
    store_id="calu",
    title="Calu",
    site="www.calubags.com",
    base="https://www.calubags.com",
    category_help="Slug Magento, por ejemplo carteras",
)
