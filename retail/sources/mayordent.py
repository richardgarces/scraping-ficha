from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_mayordent_target = parse_woocommerce_target

MayordentStore = make_woocommerce_store(
    store_id="mayordent",
    title="MayorDent",
    site="www.mayordent.cl",
    base="https://www.mayordent.cl",
    category_help="Slug WooCommerce, por ejemplo cepillos",
)
