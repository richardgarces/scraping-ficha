from retail.platforms.magento import make_magento_store, parse_magento_target

parse_mcgregor_target = parse_magento_target

McgregorStore = make_magento_store(
    store_id="mcgregor",
    title="McGregor",
    site="www.mcgregor.cl",
    base="https://www.mcgregor.cl",
    category_help="Slug Magento, por ejemplo poleras",
)
