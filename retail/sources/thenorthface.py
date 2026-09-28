from retail.platforms.magento import make_magento_store, parse_magento_target

parse_thenorthface_target = parse_magento_target

ThenorthfaceStore = make_magento_store(
    store_id="thenorthface",
    title="The North Face",
    site="www.thenorthface.cl",
    base="https://www.thenorthface.cl",
    category_help="Slug Magento, por ejemplo categoria.html",
)
