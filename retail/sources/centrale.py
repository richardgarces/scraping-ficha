from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_centrale_target = parse_woocommerce_target

CentraleStore = make_woocommerce_store(
    store_id="centrale",
    title="Centrale",
    site="www.centrale.cl",
    base="https://www.centrale.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
