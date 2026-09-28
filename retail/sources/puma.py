from retail.platforms.magento import make_magento_store, parse_magento_target

parse_puma_target = parse_magento_target

PumaStore = make_magento_store(
    store_id="puma",
    title="Puma",
    site="cl.puma.com",
    base="https://cl.puma.com",
    category_help="Slug Magento, por ejemplo categoria.html",
)
