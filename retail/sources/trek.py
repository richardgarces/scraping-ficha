from retail.platforms.magento import make_magento_store, parse_magento_target

parse_trek_target = parse_magento_target

TrekStore = make_magento_store(
    store_id="trek",
    title="Trek",
    site="trekbikeschile.com",
    base="https://trekbikeschile.com",
    category_help="Slug Magento, por ejemplo cascos",
)
