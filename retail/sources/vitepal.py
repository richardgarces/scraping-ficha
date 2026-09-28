from retail.platforms.magento import make_magento_store, parse_magento_target

parse_vitepal_target = parse_magento_target

VitepalStore = make_magento_store(
    store_id="vitepal",
    title="Vitepal",
    site="www.vitepal.cl",
    base="https://www.vitepal.cl",
    category_help="Slug Magento, por ejemplo herramientas",
)
