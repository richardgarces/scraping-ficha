from retail.platforms.magento import make_magento_store, parse_magento_target

parse_cannon_target = parse_magento_target

CannonStore = make_magento_store(
    store_id="cannon",
    title="Cannon Home",
    site="www.cannonhome.cl",
    base="https://www.cannonhome.cl",
    category_help="Slug Magento, por ejemplo sabanas",
)
