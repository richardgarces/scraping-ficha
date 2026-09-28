from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_etchile_target = parse_woocommerce_target

EtchileStore = make_woocommerce_store(
    store_id="etchile",
    title="ET Chile",
    site="etchile.net",
    base="https://etchile.net",
    category_help="Slug WooCommerce, por ejemplo perifericos",
)
