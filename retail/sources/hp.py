from retail.platforms.magento import make_magento_store, parse_magento_target

parse_hp_target = parse_magento_target

HpStore = make_magento_store(
    store_id="hp",
    title="HP",
    site="www.hp.com",
    base="https://www.hp.com/cl-es/shop",
    category_help="Slug Magento bajo /cl-es/shop, por ejemplo notebooks",
)
