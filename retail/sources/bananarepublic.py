from retail.platforms.magento import make_magento_store, parse_magento_target

parse_bananarepublic_target = parse_magento_target

BananarepublicStore = make_magento_store(
    store_id="bananarepublic",
    title="Banana Republic",
    site="www.bananarepublic.cl",
    base="https://www.bananarepublic.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
