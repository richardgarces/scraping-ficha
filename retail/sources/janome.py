from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_janome_target = parse_woocommerce_target

JanomeStore = make_woocommerce_store(
    store_id="janome",
    title="Janome",
    site="www.janome.cl",
    base="https://www.janome.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
