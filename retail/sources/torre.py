from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_torre_target = parse_woocommerce_target

TorreStore = make_woocommerce_store(
    store_id="torre",
    title="Torre",
    site="www.torre.cl",
    base="https://www.torre.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
