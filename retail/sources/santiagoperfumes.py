from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_santiagoperfumes_target = parse_woocommerce_target

SantiagoperfumesStore = make_woocommerce_store(
    store_id="santiagoperfumes",
    title="Santiago Perfumes",
    site="santiagoperfumes.cl",
    base="https://santiagoperfumes.cl",
    category_help="Slug WooCommerce, por ejemplo perfumes",
)
