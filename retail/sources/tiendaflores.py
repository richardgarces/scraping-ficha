from retail.platforms.magento import make_magento_store, parse_magento_target

parse_tiendaflores_target = parse_magento_target

TiendaFloresStore = make_magento_store(
    store_id="tiendaflores",
    title="Tienda Flores",
    site="tiendaflores.cl",
    base="https://tiendaflores.cl",
    category_help="Slug Magento de categoría",
)
