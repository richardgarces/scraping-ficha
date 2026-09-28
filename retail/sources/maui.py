from retail.platforms.magento import make_magento_store, parse_magento_target

parse_maui_target = parse_magento_target

MauiStore = make_magento_store(
    store_id="maui",
    title="Maui and Sons",
    site="www.mauiandsons.cl",
    base="https://www.mauiandsons.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
