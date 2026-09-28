from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lippi_target = parse_shopify_target

LippiStore = make_shopify_store(
    store_id="lippi",
    title="Lippi Outdoor",
    site="www.lippioutdoor.com",
    base="https://www.lippioutdoor.com",
    category_help="Handle de colección Shopify, por ejemplo chaquetas",
)
