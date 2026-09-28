from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_toyotomi_target = parse_woocommerce_target

ToyotomiStore = make_woocommerce_store(
    store_id="toyotomi",
    title="Toyotomi",
    site="toyotomi.cl",
    base="https://toyotomi.cl",
    category_help="Slug WooCommerce, por ejemplo estufas",
)
