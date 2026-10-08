from retail.platforms.magento import make_magento_store, parse_magento_target

parse_maktotal_target = parse_magento_target

MaktotalStore = make_magento_store(
    store_id="maktotal",
    title="Maktotal",
    site="www.maktotal.cl",
    base="https://www.maktotal.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
