from retail.platforms.magento import make_magento_store, parse_magento_target

parse_econopticas_target = parse_magento_target

EconopticasStore = make_magento_store(
    store_id="econopticas",
    title="Econópticas",
    site="www.econopticas.cl",
    base="https://www.econopticas.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
