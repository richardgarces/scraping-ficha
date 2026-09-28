from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_chileperfume_target = parse_woocommerce_target

ChileperfumeStore = make_woocommerce_store(
    store_id="chileperfume",
    title="Chile Perfume",
    site="www.chileperfume.cl",
    base="https://www.chileperfume.cl",
    category_help="Slug WooCommerce, por ejemplo perfumes",
)
