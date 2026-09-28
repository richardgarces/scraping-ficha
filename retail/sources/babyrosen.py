from retail.platforms.magento import make_magento_store, parse_magento_target

parse_babyrosen_target = parse_magento_target

BabyrosenStore = make_magento_store(
    store_id="babyrosen",
    title="Baby Rosen",
    site="www.babyrosen.cl",
    base="https://www.babyrosen.cl",
    category_help="Slug Magento, por ejemplo ropa de cama",
)
