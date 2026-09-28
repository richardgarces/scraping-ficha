from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_azedan_target = parse_woocommerce_target

AzedanStore = make_woocommerce_store(
    store_id="azedan",
    title="A-Zedan",
    site="www.azedan.cl",
    base="https://www.azedan.cl",
    category_help="Slug WooCommerce, por ejemplo neumaticos",
)
