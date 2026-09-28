from retail.platforms.magento import make_magento_store, parse_magento_target

parse_jayson_target = parse_magento_target

JaysonStore = make_magento_store(
    store_id="jayson",
    title="Jayson",
    site="www.jayson.cl",
    base="https://www.jayson.cl",
    category_help="Slug Magento, por ejemplo calzado de seguridad",
)
