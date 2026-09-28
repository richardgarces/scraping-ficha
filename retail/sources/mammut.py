from retail.platforms.magento import make_magento_store, parse_magento_target

parse_mammut_target = parse_magento_target

MammutStore = make_magento_store(
    store_id="mammut",
    title="Mammut",
    site="www.mammut.cl",
    base="https://www.mammut.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
