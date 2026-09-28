from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_indumac_target = parse_woocommerce_target

IndumacStore = make_woocommerce_store(
    store_id="indumac",
    title="Indumac",
    site="tienda.indumac.cl",
    base="https://tienda.indumac.cl",
    category_help="Slug WooCommerce, por ejemplo sillas-reunion-y-multiproposito",
)
