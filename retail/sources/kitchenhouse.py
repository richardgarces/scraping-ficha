from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kitchenhouse_target = parse_shopify_target

KitchenhouseStore = make_shopify_store(
    store_id="kitchenhouse",
    title="Kitchen House",
    site="www.kitchenhouse.cl",
    base="https://www.kitchenhouse.cl",
    category_help="Handle de colección Shopify, por ejemplo hornos",
)
