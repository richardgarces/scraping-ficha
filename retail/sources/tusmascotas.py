from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_tusmascotas_target = parse_woocommerce_target

TusmascotasStore = make_woocommerce_store(
    store_id="tusmascotas",
    title="TusMascotas",
    site="www.tusmascotas.cl",
    base="https://www.tusmascotas.cl",
    category_help="Slug WooCommerce, por ejemplo perros",
)
