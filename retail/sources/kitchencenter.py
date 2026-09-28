from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kitchencenter_target = parse_shopify_target

KitchencenterStore = make_shopify_store(
    store_id="kitchencenter",
    title="Kitchen Center",
    site="www.kitchencenter.cl",
    base="https://www.kitchencenter.cl",
    category_help="Handle de colección Shopify",
)
