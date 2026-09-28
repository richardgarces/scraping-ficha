from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_wineclub_target = parse_woocommerce_target

WineclubStore = make_woocommerce_store(
    store_id="wineclub",
    title="Santiago Wine Club",
    site="www.santiagowineclub.cl",
    base="https://www.santiagowineclub.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
