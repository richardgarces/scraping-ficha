from retail.platforms.magento import make_magento_store, parse_magento_target

parse_kipling_target = parse_magento_target

KiplingStore = make_magento_store(
    store_id="kipling",
    title="Kipling",
    site="www.kipling.cl",
    base="https://www.kipling.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
