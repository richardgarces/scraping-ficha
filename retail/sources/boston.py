from retail.platforms.magento import make_magento_store, parse_magento_target

parse_boston_target = parse_magento_target

BostonStore = make_magento_store(
    store_id="boston",
    title="Repuestos Boston",
    site="www.repuestosboston.cl",
    base="https://www.repuestosboston.cl",
    category_help="Slug Magento, por ejemplo repuestos",
)
