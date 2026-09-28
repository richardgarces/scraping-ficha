from retail.platforms.magento import make_magento_store, parse_magento_target

parse_antartica_target = parse_magento_target

AntarticaStore = make_magento_store(
    store_id="antartica",
    title="Librería Antártica",
    site="www.antartica.cl",
    base="https://www.antartica.cl",
    category_help="Slug Magento, por ejemplo libros.html",
)
