from retail.platforms.woocommerce import make_woocommerce_store, parse_woocommerce_target

parse_bodyshop_target = parse_woocommerce_target

BodyshopStore = make_woocommerce_store(
    store_id="bodyshop",
    title="The Body Shop",
    site="www.thebodyshop.cl",
    base="https://www.thebodyshop.cl",
    category_help="Slug WooCommerce, por ejemplo cremas",
)
