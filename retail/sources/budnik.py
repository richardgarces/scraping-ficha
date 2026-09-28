from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_budnik_target = parse_woocommerce_target

BudnikStore = make_woocommerce_store(
    store_id="budnik",
    title="Budnik",
    site="www.budnik.cl",
    base="https://www.budnik.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
