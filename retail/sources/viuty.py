from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_viuty_target = parse_woocommerce_target

ViutyStore = make_woocommerce_store(
    store_id="viuty",
    title="Viuty",
    site="www.viuty.cl",
    base="https://www.viuty.cl",
    category_help="Slug WooCommerce, por ejemplo cabello",
)
