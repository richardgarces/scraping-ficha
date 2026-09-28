from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_nuvac_target = parse_woocommerce_target

NuvacStore = make_woocommerce_store(
    store_id="nuvac",
    title="Nüvac",
    site="nuvac.cl",
    base="https://nuvac.cl",
    category_help="Slug WooCommerce, por ejemplo aspiradoras",
)
