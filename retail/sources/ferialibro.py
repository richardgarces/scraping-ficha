from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_ferialibro_target = parse_woocommerce_target

FerialibroStore = make_woocommerce_store(
    store_id="ferialibro",
    title="Feria Chilena del Libro",
    site="www.feriachilenadellibro.cl",
    base="https://www.feriachilenadellibro.cl",
    category_help="Slug WooCommerce, por ejemplo categoria",
)
