from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_worbee_target = parse_shopify_target

WorbeeStore = make_shopify_store(
    store_id="worbee",
    title="worbee",
    site="www.worbee.cl",
    base="https://www.worbee.cl",
    category_help="Handle de colección Shopify, por ejemplo cerraduras",
)
