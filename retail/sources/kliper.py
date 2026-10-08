from retail.platforms.magento import make_magento_store, parse_magento_target

parse_kliper_target = parse_magento_target

KliperStore = make_magento_store(
    store_id="kliper",
    title="Kliper",
    site="www.kliper.cl",
    base="https://www.kliper.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
