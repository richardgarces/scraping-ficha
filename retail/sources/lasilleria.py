from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_lasilleria_target = parse_woocommerce_target

LasilleriaStore = make_woocommerce_store(
    store_id="lasilleria",
    title="La Sillería",
    site="lasilleria.cl",
    base="https://lasilleria.cl",
    category_help="Slug WooCommerce, por ejemplo sillas",
)
