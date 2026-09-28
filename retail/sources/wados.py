from retail.platforms.magento import make_magento_store, parse_magento_target

parse_wados_target = parse_magento_target

WadosStore = make_magento_store(
    store_id="wados",
    title="Wados",
    site="www.wa2.cl",
    base="https://www.wa2.cl",
    category_help="Slug Magento, por ejemplo blusas",
)
