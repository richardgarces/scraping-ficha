from retail.platforms.magento import make_magento_store, parse_magento_target

parse_speedo_target = parse_magento_target

SpeedoStore = make_magento_store(
    store_id="speedo",
    title="Speedo",
    site="www.speedo.cl",
    base="https://www.speedo.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
