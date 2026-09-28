from retail.platforms.magento import make_magento_store, parse_magento_target

parse_volcom_target = parse_magento_target

VolcomStore = make_magento_store(
    store_id="volcom",
    title="Volcom",
    site="www.volcom.cl",
    base="https://www.volcom.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
