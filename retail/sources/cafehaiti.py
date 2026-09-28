from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_cafehaiti_target = parse_woocommerce_target

CafehaitiStore = make_woocommerce_store(
    store_id="cafehaiti",
    title="Café Haití",
    site="www.cafehaiti.cl",
    base="https://www.cafehaiti.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
