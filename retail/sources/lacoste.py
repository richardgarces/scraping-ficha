from retail.platforms.magento import make_magento_store, parse_magento_target

parse_lacoste_target = parse_magento_target

LacosteStore = make_magento_store(
    store_id="lacoste",
    title="Lacoste",
    site="www.lacoste.cl",
    base="https://www.lacoste.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
