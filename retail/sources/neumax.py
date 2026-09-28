from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_neumax_target = parse_woocommerce_target

NeumaxStore = make_woocommerce_store(
    store_id="neumax",
    title="Neumax",
    site="neumax.cl",
    base="https://neumax.cl",
    category_help="Slug WooCommerce, por ejemplo triangle",
)
