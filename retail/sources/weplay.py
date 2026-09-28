from retail.platforms.magento import make_magento_store, parse_magento_target

parse_weplay_target = parse_magento_target

WeplayStore = make_magento_store(
    store_id="weplay",
    title="WePlay",
    site="www.weplay.cl",
    base="https://www.weplay.cl",
    category_help="Slug Magento, por ejemplo consolas.html",
)
