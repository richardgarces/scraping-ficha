from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_catalonia_target = parse_woocommerce_target

CataloniaStore = make_woocommerce_store(
    store_id="catalonia",
    title="Librería Catalonia",
    site="www.catalonia.cl",
    base="https://www.catalonia.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
