from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_artenostro_target = parse_woocommerce_target

ArtenostroStore = make_woocommerce_store(
    store_id="artenostro",
    title="Arte Nostro",
    site="www.artenostro.cl",
    base="https://www.artenostro.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
