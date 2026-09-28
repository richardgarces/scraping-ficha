from retail.platforms.magento import make_magento_store, parse_magento_target

parse_thomas_target = parse_magento_target

ThomasStore = make_magento_store(
    store_id="thomas",
    title="Thomas",
    site="www.thomas.cl",
    base="https://www.thomas.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
