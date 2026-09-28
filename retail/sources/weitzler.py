from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_weitzler_target = parse_woocommerce_target

WeitzlerStore = make_woocommerce_store(
    store_id="weitzler",
    title="Weitzler",
    site="www.weitzler.cl",
    base="https://www.weitzler.cl",
    category_help="Slug WooCommerce, por ejemplo herramientas",
)
