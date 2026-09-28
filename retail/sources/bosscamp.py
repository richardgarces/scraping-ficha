from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bosscamp_target = parse_shopify_target

BosscampStore = make_shopify_store(
    store_id="bosscamp",
    title="BossCamp",
    site="www.bosscamp.cl",
    base="https://www.bosscamp.cl",
    category_help="Handle de colección Shopify, por ejemplo outdoor",
)
