from retail.platforms.magento import make_magento_store, parse_magento_target

parse_potros_target = parse_magento_target

PotrosStore = make_magento_store(
    store_id="potros",
    title="Potros",
    site="www.potros.cl",
    base="https://www.potros.cl",
    category_help="Slug Magento, por ejemplo camisas",
)
