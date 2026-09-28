from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_mueblesterrazas_target = parse_woocommerce_target

MueblesterrazasStore = make_woocommerce_store(
    store_id="mueblesterrazas",
    title="Muebles y Terrazas",
    site="mueblesyterrazas.cl",
    base="https://mueblesyterrazas.cl",
    category_help="Slug WooCommerce, por ejemplo terrazas",
)
