from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_backonline_target = parse_shopify_target

BackonlineStore = make_shopify_store(
    store_id="backonline",
    title="Backonline",
    site="www.backonline.cl",
    base="https://www.backonline.cl",
    category_help="Handle de colección Shopify, por ejemplo tecnologia",
)
