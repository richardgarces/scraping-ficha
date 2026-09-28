from retail.platforms.magento import make_magento_store, parse_magento_target

parse_marmot_target = parse_magento_target

MarmotStore = make_magento_store(
    store_id="marmot",
    title="Marmot",
    site="www.marmot.cl",
    base="https://www.marmot.cl",
    category_help="Slug Magento, por ejemplo chaquetas",
)
