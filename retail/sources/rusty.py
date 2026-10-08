from retail.platforms.magento import make_magento_store, parse_magento_target

parse_rusty_target = parse_magento_target

RustyStore = make_magento_store(
    store_id="rusty",
    title="Rusty",
    site="www.rusty.cl",
    base="https://www.rusty.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
