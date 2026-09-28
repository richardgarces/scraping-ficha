from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_hohos_target = parse_woocommerce_target

HohosStore = make_woocommerce_store(
    store_id="hohos",
    title="Hohos",
    site="www.hohos.cl",
    base="https://www.hohos.cl",
    category_help="Slug WooCommerce, por ejemplo toallas",
)
