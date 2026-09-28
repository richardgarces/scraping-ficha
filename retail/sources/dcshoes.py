from retail.platforms.magento import make_magento_store, parse_magento_target

parse_dcshoes_target = parse_magento_target

DcshoesStore = make_magento_store(
    store_id="dcshoes",
    title="DC Shoes",
    site="www.dcshoes.cl",
    base="https://www.dcshoes.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
