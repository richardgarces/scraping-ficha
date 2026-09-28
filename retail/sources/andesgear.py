from retail.platforms.magento import make_magento_store, parse_magento_target

parse_andesgear_target = parse_magento_target

AndesgearStore = make_magento_store(
    store_id="andesgear",
    title="Andesgear",
    site="www.andesgear.cl",
    base="https://www.andesgear.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
