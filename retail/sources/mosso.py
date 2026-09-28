from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_mosso_target = parse_woocommerce_target

MossoStore = make_woocommerce_store(
    store_id="mosso",
    title="Mosso",
    site="www.mosso.cl",
    base="https://www.mosso.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
