from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_getway_target = parse_shopify_target

GetwayStore = make_shopify_store(
    store_id="getway",
    title="Getway",
    site="www.getway.cl",
    base="https://www.getway.cl",
    category_help="Handle de colección Shopify",
)
