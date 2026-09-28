from retail.platforms.magento import make_magento_store, parse_magento_target

parse_stoked_target = parse_magento_target

StokedStore = make_magento_store(
    store_id="stoked",
    title="Stoked",
    site="www.stoked.cl",
    base="https://www.stoked.cl",
    category_help="Slug Magento, por ejemplo trajes-de-surf",
)
