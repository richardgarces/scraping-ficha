from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_ecofarmacias_target = parse_woocommerce_target

EcofarmaciasStore = make_woocommerce_store(
    store_id="ecofarmacias",
    title="Eco Farmacias",
    site="www.ecofarmacias.cl",
    base="https://www.ecofarmacias.cl",
    category_help="Slug WooCommerce, por ejemplo farmacia",
)
