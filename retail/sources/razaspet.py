from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_razaspet_target = parse_woocommerce_target

RazaspetStore = make_woocommerce_store(
    store_id="razaspet",
    title="RazasPet",
    site="razaspet.cl",
    base="https://razaspet.cl",
    category_help="Slug WooCommerce, por ejemplo gatos",
)
