from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_daher_target = parse_woocommerce_target

DaherStore = make_woocommerce_store(
    store_id="daher",
    title="Daher",
    site="comercialdaher.cl",
    base="https://comercialdaher.cl",
    category_help="Slug WooCommerce, por ejemplo neumaticos",
)
