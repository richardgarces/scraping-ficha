from retail.platforms.magento import make_magento_store, parse_magento_target

parse_supermercado_del_neumatico_target = parse_magento_target

SupermercadoDelNeumaticoStore = make_magento_store(
    store_id="supermercado_del_neumatico",
    title="Supermercado del Neumatico",
    site="www.supermercadodelneumatico.cl",
    base="https://www.supermercadodelneumatico.cl",
    category_help="Slug Magento, por ejemplo camas-y-colchones/colchones",
)
