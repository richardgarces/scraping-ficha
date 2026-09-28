from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_dacsa_target = parse_woocommerce_target

DacsaStore = make_woocommerce_store(
    store_id="dacsa",
    title="Serviteca Dacsa",
    site="dacsa.cl",
    base="https://dacsa.cl",
    category_help="Slug WooCommerce, por ejemplo neumaticos",
)
