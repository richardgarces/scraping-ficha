from retail.platforms.magento import make_magento_store, parse_magento_target

parse_rosen_target = parse_magento_target

RosenStore = make_magento_store(
    store_id="rosen",
    title="Rosen",
    site="www.rosen.cl",
    base="https://www.rosen.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
