from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_tiresimport_target = parse_woocommerce_target

TiresimportStore = make_woocommerce_store(
    store_id="tiresimport",
    title="Tires Import",
    site="www.tiresimport.cl",
    base="https://www.tiresimport.cl",
    category_help="Slug WooCommerce, por ejemplo neumaticos",
)
