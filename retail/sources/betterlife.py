from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_betterlife_target = parse_shopify_target

BetterlifeStore = make_shopify_store(
    store_id="betterlife",
    title="Betterlife",
    site="www.betterlife.cl",
    base="https://www.betterlife.cl",
    category_help="Handle de colección Shopify",
)
