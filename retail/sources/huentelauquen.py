from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_huentelauquen_target = parse_woocommerce_target

HuentelauquenStore = make_woocommerce_store(
    store_id="huentelauquen",
    title="Huentelauquen",
    site="huentelauquen.cl",
    base="https://huentelauquen.cl",
    category_help="Slug WooCommerce, por ejemplo helados",
)
